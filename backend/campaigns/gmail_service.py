"""
Gmail API service helpers.

Handles: token refresh, message composition (MIME), sending via Gmail API,
and inbox polling for reply detection.
"""
import base64
import logging
from email.mime.text import MIMEText

from django.conf import settings
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

GMAIL_API_VERSION = 'v1'


def _get_credentials(account):
    """
    Build google.oauth2.credentials.Credentials from a ConnectedEmailAccount.
    Auto-refreshes the token if expired.
    """
    creds = Credentials(
        token=account.access_token,
        refresh_token=account.refresh_token,
        token_uri='https://oauth2.googleapis.com/token',
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        scopes=settings.GOOGLE_SCOPES,
    )
    if creds.expired and creds.refresh_token:
        from google.auth.transport.requests import Request
        creds.refresh(Request())
        # Persist the refreshed token back to the database
        account.access_token = creds.token
        if creds.expiry:
            from django.utils import timezone
            account.token_expiry = creds.expiry
        account.save(update_fields=['access_token', 'token_expiry'])
    return creds


def _build_service(account):
    """Return an authenticated Gmail API service object."""
    creds = _get_credentials(account)
    return build('gmail', GMAIL_API_VERSION, credentials=creds)


def build_unsubscribe_url(lead):
    """
    Build a signed unsubscribe URL for a lead using the backend base URL.
    """
    from .utils import generate_unsubscribe_token

    token = generate_unsubscribe_token(lead.id)
    return f"{settings.BACKEND_BASE_URL}/api/v1/unsubscribe/{lead.id}/{token}/"


def send_gmail(account, to_email, subject, body_html, unsubscribe_url=None, thread_id=None):
    """
    Compose and send an email via the Gmail API.

    Returns the Message-ID string of the sent message (for reply tracking).
    """
    if unsubscribe_url:
        message_footer = (
            '<div style="margin-top:24px;padding-top:16px;border-top:1px solid #e5e7eb;'
            'font-size:0.9em;color:#6b7280;line-height:1.5;">'
            "If you'd like to stop receiving these emails, "
            f'<a href="{unsubscribe_url}" style="color:#1d4ed8;text-decoration:none;">unsubscribe here</a>.'
            '</div>'
        )
        body_html = f"{body_html}{message_footer}"
        message_headers = f"<{unsubscribe_url}>"
    else:
        message_headers = None

    service = _build_service(account)

    message = MIMEText(body_html, 'html')
    message['to'] = to_email
    message['from'] = account.email_address
    message['subject'] = subject
    if message_headers:
        message['List-Unsubscribe'] = message_headers

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    body = {'raw': raw}
    if thread_id:
        body['threadId'] = thread_id

    sent = service.users().messages().send(userId='me', body=body).execute()
    logger.info(f"Gmail sent → {to_email} | messageId={sent.get('id')}")
    return sent.get('id')


def check_for_replies(account, sent_message_ids):
    """
    Poll the Gmail inbox for replies to any of the given message IDs.

    Returns a dict: { sent_message_id: reply_snippet, ... }
    Only includes IDs that actually received a reply.
    """
    service = _build_service(account)
    replies = {}

    for msg_id in sent_message_ids:
        try:
            # Get the original message to find its threadId
            original = service.users().messages().get(
                userId='me', id=msg_id, format='metadata',
                metadataHeaders=['Message-ID']
            ).execute()
            thread_id = original.get('threadId')
            if not thread_id:
                continue

            # Get the thread
            thread = service.users().threads().get(
                userId='me', id=thread_id, format='metadata'
            ).execute()
            messages = thread.get('messages', [])

            # If the thread has more than one message, a reply exists
            if len(messages) > 1:
                # The last message in the thread that is NOT the original is the reply
                for m in reversed(messages):
                    if m['id'] != msg_id:
                        replies[msg_id] = m.get('snippet', '(reply detected)')
                        break
        except Exception as e:
            logger.warning(f"Error checking reply for {msg_id}: {e}")

    return replies
