import imaplib
import logging
import smtplib
from email import policy
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.parser import BytesParser
from email.utils import formataddr, make_msgid

from .gmail_service import _extract_failed_recipients

logger = logging.getLogger(__name__)

BOUNCE_SUBJECT_KEYWORDS = (
    'undelivered mail returned to sender',
    'delivery status notification (failure)',
    'mail delivery failed',
    'failure notice',
    'returned mail',
    'delivery has failed',
)
BOUNCE_FROM_KEYWORDS = ('mailer-daemon', 'postmaster')


def _smtp_login_parts(account):
    """Return the SMTP username/password pair for a connected mailbox."""
    return (
        (account.smtp_username or account.email_address or '').strip(),
        account.smtp_password or '',
    )


def _imap_login_parts(account):
    """Return the IMAP username/password pair for a connected mailbox."""
    return (
        (account.imap_username or account.email_address or '').strip(),
        account.imap_password or '',
    )


def _connect_smtp(account):
    """Open and authenticate an SMTP client using the account settings."""
    if account.smtp_use_ssl:
        client = smtplib.SMTP_SSL(account.smtp_host, account.smtp_port, timeout=20)
    else:
        client = smtplib.SMTP(account.smtp_host, account.smtp_port, timeout=20)
        client.ehlo()
        if account.smtp_use_tls:
            client.starttls()
            client.ehlo()

    username, password = _smtp_login_parts(account)
    if username or password:
        client.login(username, password)
    return client


def send_smtp_email(account, to_email, subject, body_html, unsubscribe_url=None):
    """
    Send an HTML email via a custom SMTP account and return the RFC Message-ID.
    """
    message = MIMEMultipart('alternative')
    message['To'] = to_email
    message['From'] = formataddr(('LeadOrbit', account.email_address))
    message['Subject'] = subject

    message_id = make_msgid(domain=(account.email_address.split('@', 1)[-1] if '@' in account.email_address else None))
    message['Message-ID'] = message_id

    if unsubscribe_url:
        message['List-Unsubscribe'] = f"<{unsubscribe_url}>"
        body_html = (
            f"{body_html}"
            '<div style="margin-top:24px;padding-top:16px;border-top:1px solid #e5e7eb;'
            'font-size:0.9em;color:#6b7280;line-height:1.5;">'
            "If you'd like to stop receiving these emails, "
            f'<a href="{unsubscribe_url}" style="color:#1d4ed8;text-decoration:none;">unsubscribe here</a>.'
            '</div>'
        )

    message.attach(MIMEText(body_html, 'html'))

    client = _connect_smtp(account)
    try:
        client.sendmail(account.email_address, [to_email], message.as_string())
    finally:
        try:
            client.quit()
        except Exception:
            client.close()

    logger.info(f"SMTP sent to {to_email} | messageId={message_id}")
    return message_id.strip('<>')


def _connect_imap(account):
    """Open and authenticate an IMAP client using the account settings."""
    if account.imap_use_ssl:
        client = imaplib.IMAP4_SSL(account.imap_host, account.imap_port)
    else:
        client = imaplib.IMAP4(account.imap_host, account.imap_port)

    username, password = _imap_login_parts(account)
    client.login(username, password)
    return client


def _looks_like_bounce(message):
    """Heuristically identify common bounce messages from subject or sender."""
    subject = str(message.get('Subject', '') or '').lower()
    from_value = str(message.get('From', '') or '').lower()
    return any(keyword in subject for keyword in BOUNCE_SUBJECT_KEYWORDS) or any(
        keyword in from_value for keyword in BOUNCE_FROM_KEYWORDS
    )


def _extract_raw_bytes(fetch_data):
    """Pull the RFC822 byte payload out of an IMAP fetch response."""
    for item in fetch_data or []:
        if isinstance(item, tuple) and len(item) > 1 and isinstance(item[1], bytes):
            return item[1]
    return b''


def find_imap_bounce_candidates(account, max_results=25):
    """
    Return unread IMAP bounce-like messages and parsed failed recipients.
    """
    client = _connect_imap(account)
    try:
        status, _ = client.select('INBOX')
        if status != 'OK':
            return []

        status, data = client.uid('search', None, 'UNSEEN')
        if status != 'OK':
            return []

        message_ids = [item.decode('utf-8') for item in (data[0] or b'').split() if item]
        candidates = []
        for message_id in message_ids[-max_results:]:
            status, fetch_data = client.uid('fetch', message_id, '(RFC822)')
            if status != 'OK':
                continue

            try:
                raw_bytes = _extract_raw_bytes(fetch_data)
                if not raw_bytes:
                    continue

                parsed = BytesParser(policy=policy.default).parsebytes(raw_bytes)
                if not _looks_like_bounce(parsed):
                    continue

                candidates.append(
                    {
                        'message_id': message_id,
                        'subject': str(parsed.get('Subject', '') or ''),
                        'failed_recipients': _extract_failed_recipients(
                            parsed,
                            account_email=account.email_address,
                        ),
                    }
                )
            except Exception as exc:
                logger.warning(f"Skipping IMAP bounce candidate {message_id}: {exc}")
                continue

        return candidates
    finally:
        try:
            client.close()
        except Exception:
            pass
        try:
            client.logout()
        except Exception:
            pass


def mark_imap_message_as_read(account, message_id):
    """
    Mark an IMAP message as seen using its UID.
    """
    if not message_id:
        return

    client = _connect_imap(account)
    try:
        client.select('INBOX')
        client.uid('store', str(message_id), '+FLAGS', '(\\Seen)')
    finally:
        try:
            client.close()
        except Exception:
            pass
        try:
            client.logout()
        except Exception:
            pass
