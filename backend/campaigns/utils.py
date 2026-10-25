import hashlib
import hmac

from django.core.signing import Signer, BadSignature

signer = Signer()
click_signer = Signer(salt='leadorbit.click-tracking')

def generate_unsubscribe_token(lead_id):
    return signer.sign(str(lead_id))

def verify_unsubscribe_token(token):
    try:
        return signer.unsign(token)
    except BadSignature:
        return None


def _destination_digest(url):
    return hashlib.sha256(url.encode('utf-8')).hexdigest()[:32]


def generate_click_token(campaign_lead_id, step_id, destination):
    """Signed click token that is only valid for this one destination URL."""
    return click_signer.sign(f"{campaign_lead_id}:{step_id}:{_destination_digest(destination)}")


def read_click_token(token, destination):
    """
    Return (campaign_lead_id, step_id, destination_verified), or None if the token is invalid.

    Tokens in emails sent before destinations were signed carry no digest; they
    still identify the click but cannot vouch for the destination.
    """
    try:
        campaign_lead_id, step_id, digest = click_signer.unsign(token).split(':')
    except BadSignature:
        try:
            campaign_lead_id, step_id = signer.unsign(token).split(':')
        except (BadSignature, ValueError):
            return None
        return campaign_lead_id, step_id, False
    except ValueError:
        return None

    if not hmac.compare_digest(digest, _destination_digest(destination)):
        return None
    return campaign_lead_id, step_id, True
