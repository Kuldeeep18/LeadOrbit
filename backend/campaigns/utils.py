from django.core.signing import Signer, BadSignature
import random
import re

signer = Signer()


def generate_unsubscribe_token(lead_id):
    return signer.sign(str(lead_id))


def verify_unsubscribe_token(token):
    try:
        return signer.unsign(token)
    except BadSignature:
        return None


def parse_spintax(text):
    if not text:
        return text

    pattern = r"\{([^{}]+)\}"

    while re.search(pattern, text):
        text = re.sub(
            pattern,
            lambda match: random.choice(
                match.group(1).split("|")
            ),
            text,
            count=1,
        )

    return text