from django.core.signing import Signer, BadSignature
from .models import SequenceStepEvent

signer = Signer()

def generate_unsubscribe_token(lead_id):
    return signer.sign(str(lead_id))

def verify_unsubscribe_token(token):
    try:
        return signer.unsign(token)
    except BadSignature:
        return None

def log_step_event(campaign_lead, step_order, channel_type, event_type):
    """Best-effort event log write; never let analytics logging break the caller."""
    try:
        SequenceStepEvent.objects.create(
            campaign=campaign_lead.campaign,
            campaign_lead=campaign_lead,
            step_order=step_order,
            channel_type=channel_type,
            event_type=event_type,
        )
    except Exception:
        import logging
        logging.getLogger(__name__).exception("Failed to log step event")