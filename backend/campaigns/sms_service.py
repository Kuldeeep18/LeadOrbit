"""
Twilio SMS & Voice service helpers.

Handles: sending SMS messages and initiating voice calls via Twilio API.
"""
import logging

from django.conf import settings

logger = logging.getLogger(__name__)


def _get_client():
    """Return an authenticated Twilio REST client."""
    from twilio.rest import Client

    account_sid = getattr(settings, 'TWILIO_ACCOUNT_SID', '')
    auth_token = getattr(settings, 'TWILIO_AUTH_TOKEN', '')

    if not account_sid or not auth_token:
        raise RuntimeError(
            'Twilio credentials not configured. '
            'Set TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN in your .env file.'
        )

    return Client(account_sid, auth_token)


def send_sms(to_number, body):
    """
    Send an SMS message via Twilio.

    Args:
        to_number: Recipient phone number in E.164 format (e.g. +1234567890)
        body: SMS message text (max 1600 chars, 160 for single segment)

    Returns:
        The Twilio message SID string.
    """
    from_number = getattr(settings, 'TWILIO_PHONE_NUMBER', '')
    if not from_number:
        raise RuntimeError(
            'TWILIO_PHONE_NUMBER not configured. '
            'Set it in your .env file.'
        )

    client = _get_client()
    message = client.messages.create(
        body=body,
        from_=from_number,
        to=to_number,
    )
    logger.info(f"SMS sent to {to_number} | sid={message.sid}")
    return message.sid


def initiate_call(to_number, call_script=None):
    """
    Initiate an outbound voice call via Twilio.

    Uses TwiML to either read a script or connect the call.

    Args:
        to_number: Recipient phone number in E.164 format
        call_script: Optional text for Twilio to read (TwiML <Say>).
                     If None, a default greeting is used.

    Returns:
        The Twilio call SID string.
    """
    from_number = getattr(settings, 'TWILIO_PHONE_NUMBER', '')
    if not from_number:
        raise RuntimeError(
            'TWILIO_PHONE_NUMBER not configured. '
            'Set it in your .env file.'
        )

    if not call_script:
        call_script = 'Hello, this is a call from your outreach campaign. Please hold while we connect you.'

    # Build inline TwiML
    twiml = f'<Response><Say voice="alice">{call_script}</Say></Response>'

    client = _get_client()
    call = client.calls.create(
        twiml=twiml,
        from_=from_number,
        to=to_number,
    )
    logger.info(f"Call initiated to {to_number} | sid={call.sid}")
    return call.sid
