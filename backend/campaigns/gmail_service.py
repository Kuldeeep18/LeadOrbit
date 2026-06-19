"""
Gmail API service helpers.

Handles: token refresh, message composition (MIME), sending via Gmail API,
and inbox polling for reply detection.
"""
import base64
import logging
import re
from email import policy
from email.mime.text import MIMEText
from email.parser import BytesParser

from django.conf import settings
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

GMAIL_API_VERSION = 'v1'
BOUNCE_QUERY = (
    'is:unread ('
    'subject:"Undelivered Mail Returned to Sender" '
    'OR subject:"Delivery Status Notification (Failure)" '
    'OR subject:"Mail delivery failed" '
    'OR subject:"Failure Notice" '
    'OR from:mailer-daemon '
    'OR from:postmaster'
    ')'
)
EMAIL_REGEX = re.compile(r'([A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,})', re.IGNORECASE)
FAILED_RECIPIENT_PATTERNS = (
    re.compile(r'final-recipient:\s*rfc822;\s*<?([A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,})>?', re.IGNORECASE),
    re.compile(r'original-recipient:\s*rfc822;\s*<?([A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,})>?', re.IGNORECASE),
    re.compile(r'x-failed-recipients:\s*<?([A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,})>?', re.IGNORECASE),
    re.compile(
        r'delivery to the following recipient(?:s)? failed(?: permanently)?:\s*<?([A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,})>?',
        re.IGNORECASE,
    ),
    re.compile(
        r'the following message to\s*<?([A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,})>?\s*was undeliverable',
        re.IGNORECASE,
    ),
    re.compile(
        r"couldn't be delivered to\s*<?([A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,})>?",
        re.IGNORECASE,
    ),
    re.compile(
        r'address not found:\s*<?([A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,})>?',
        re.IGNORECASE,
    ),
)


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


def _decode_gmail_raw_message(raw_message):
    """Decode a Gmail API raw message payload into an email.message object."""
    if not raw_message:
        return None

    padded = raw_message + ('=' * (-len(raw_message) % 4))
    raw_bytes = base64.urlsafe_b64decode(padded.encode('utf-8'))
    return BytesParser(policy=policy.default).parsebytes(raw_bytes)


def _extract_text_from_message(message):
    """Collect relevant text content from a parsed MIME message."""
    if message is None:
        return ''

    parts = []
    for part in message.walk():
        content_type = part.get_content_type()
        if content_type not in {'text/plain', 'text/html', 'message/delivery-status'}:
            continue

        try:
            content = part.get_content()
        except Exception:
            payload = part.get_payload(decode=True)
            if isinstance(payload, bytes):
                charset = part.get_content_charset() or 'utf-8'
                content = payload.decode(charset, errors='ignore')
            else:
                content = payload or ''

        if isinstance(content, list):
            content = '\n'.join(str(item) for item in content)
        parts.append(str(content))

    return '\n'.join(parts)


def _normalize_email_list(values, account_email=None):
    """Normalize parsed addresses and drop duplicates plus sender/bounce aliases."""
    ignored = {(account_email or '').strip().lower(), 'mailer-daemon', 'postmaster'}
    normalized = []
    seen = set()

    for value in values:
        email = (value or '').strip().strip('<>').lower()
        if not email or email in ignored or email in seen:
            continue
        seen.add(email)
        normalized.append(email)

    return normalized


def _extract_failed_recipients(message, account_email=None):
    """Extract intended failed-recipient addresses from a bounce message."""
    if message is None:
        return []

    headers_text = '\n'.join(f'{key}: {value}' for key, value in message.items())
    body_text = _extract_text_from_message(message)
    combined_text = f'{headers_text}\n{body_text}'

    matches = []
    for pattern in FAILED_RECIPIENT_PATTERNS:
        matches.extend(pattern.findall(combined_text))

    if matches:
        return _normalize_email_list(matches, account_email=account_email)

    fallback_emails = _normalize_email_list(
        EMAIL_REGEX.findall(combined_text),
        account_email=account_email,
    )
    # Fail closed when free-text scanning finds multiple candidates.
    return fallback_emails if len(fallback_emails) == 1 else []


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


def find_gmail_bounce_candidates(account, max_results=25):
    """
    Return unread bounce-like Gmail messages and any failed recipients parsed from them.
    """
    service = _build_service(account)
    response = service.users().messages().list(
        userId='me',
        q=BOUNCE_QUERY,
        maxResults=max_results,
    ).execute()

    candidates = []
    for item in response.get('messages', []):
        message_id = item.get('id')
        if not message_id:
            continue

        try:
            raw_message = service.users().messages().get(
                userId='me',
                id=message_id,
                format='raw',
            ).execute()
            parsed = _decode_gmail_raw_message(raw_message.get('raw'))
            candidates.append(
                {
                    'message_id': message_id,
                    'subject': parsed.get('Subject', '') if parsed else '',
                    'failed_recipients': _extract_failed_recipients(
                        parsed,
                        account_email=account.email_address,
                    ),
                }
            )
        except Exception as exc:
            logger.warning(f"Skipping Gmail bounce candidate {message_id}: {exc}")
            continue

    return candidates


def mark_gmail_message_as_read(account, message_id):
    """Remove the UNREAD label from a Gmail message after processing it."""
    if not message_id:
        return

    service = _build_service(account)
    service.users().messages().modify(
        userId='me',
        id=message_id,
        body={'removeLabelIds': ['UNREAD']},
    ).execute()
