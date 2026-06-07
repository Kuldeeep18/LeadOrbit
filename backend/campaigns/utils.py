from django.core.signing import Signer, BadSignature

signer = Signer()

def generate_unsubscribe_token(lead_id):
    return signer.sign(str(lead_id))

def verify_unsubscribe_token(token):
    try:
        return signer.unsign(token)
    except BadSignature:
        return None