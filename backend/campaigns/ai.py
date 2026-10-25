import json
import logging
import re

import requests
from django.conf import settings

logger = logging.getLogger(__name__)
MERGE_TAG_PATTERN = re.compile(r'{{\s*([a-zA-Z0-9_]+)\s*}}')


def _get_gemini_api_key():
    return (getattr(settings, 'GEMINI_API_KEY', '') or '').strip()


def get_ai_provider():
    """Which LLM personalizes emails: 'ollama' (self-hosted), 'gemini' or 'none'."""
    return (getattr(settings, 'AI_PROVIDER', '') or 'none').strip().lower()


def ai_is_configured():
    provider = get_ai_provider()
    if provider == 'ollama':
        return bool((getattr(settings, 'OLLAMA_BASE_URL', '') or '').strip())
    if provider == 'gemini':
        return bool(_get_gemini_api_key())
    return False


def _get_ollama_model():
    return (getattr(settings, 'OLLAMA_MODEL', '') or 'qwen2.5:3b').strip()


def _ollama_chat(messages, temperature=0.7):
    """Call a self-hosted Ollama server and return the assistant's raw text."""
    base_url = (getattr(settings, 'OLLAMA_BASE_URL', '') or 'http://127.0.0.1:11434').rstrip('/')
    response = requests.post(
        f'{base_url}/api/chat',
        json={
            'model': _get_ollama_model(),
            'messages': messages,
            'stream': False,
            'format': 'json',
            'keep_alive': getattr(settings, 'OLLAMA_KEEP_ALIVE', '30m'),
            'options': {'temperature': temperature},
        },
        timeout=int(getattr(settings, 'OLLAMA_TIMEOUT_SECONDS', 60)),
    )
    response.raise_for_status()
    return (response.json().get('message') or {}).get('content', '')


def _strip_code_fences(text):
    if not text:
        return ''
    cleaned = text.strip()
    if cleaned.startswith('```'):
        cleaned = re.sub(r'^```[a-zA-Z0-9_-]*\s*', '', cleaned)
        cleaned = re.sub(r'\s*```$', '', cleaned)
    return cleaned.strip()


def _parse_json_payload(text):
    cleaned = _strip_code_fences(text)
    try:
        return json.loads(cleaned)
    except Exception:
        match = re.search(r'\{[\s\S]*\}', cleaned)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except Exception:
            return None


BRACKET_PLACEHOLDERS = {
    'firstname': '{{firstName}}', 'first name': '{{firstName}}', 'first_name': '{{firstName}}',
    'name': '{{firstName}}', 'recipient name': '{{firstName}}', "recipient's name": '{{firstName}}',
    'lastname': '{{lastName}}', 'last name': '{{lastName}}', 'last_name': '{{lastName}}',
    'company': '{{company}}', 'company name': '{{company}}', "recipient's company": '{{company}}',
}
BRACKET_PATTERN = re.compile(r'\[([A-Za-z_\' ]{3,25})\]')


def _normalize_placeholders(text):
    """Small models often write [FirstName]; turn known ones into real merge tags."""
    return BRACKET_PATTERN.sub(
        lambda m: BRACKET_PLACEHOLDERS.get(m.group(1).strip().lower(), m.group(0)),
        text or '',
    )


ANY_BRACKET_PLACEHOLDER = re.compile(r'\[[^\]\n]{2,40}\]')


def _sign_off(text):
    """The template's closing line (e.g. the sender's name), if it has a short one."""
    lines = [line.strip() for line in (text or '').splitlines() if line.strip()]
    if len(lines) < 2 or len(lines[-1]) > 40:
        return ''
    return lines[-1]


def _is_safe_personalization(original_body, subject, body):
    """Reject AI output that would reach a lead with unfilled placeholders or a lost sign-off."""
    if ANY_BRACKET_PLACEHOLDER.search(subject) or ANY_BRACKET_PLACEHOLDER.search(body):
        return False
    sign_off = _sign_off(original_body)
    return not sign_off or sign_off in body


def _apply_merge_tags(text, lead):
    base = text or ""
    first_name = lead.first_name or ""
    last_name = lead.last_name or ""
    company = lead.company or ""
    email = lead.email or ""
    custom_variables = getattr(lead, 'custom_variables', {})

    standard_replacements = {
        "first_name": first_name,
        "firstName": first_name,
        "last_name": last_name,
        "lastName": last_name,
        "company": company,
        "email": email,
    }
    custom_replacements = {}
    if isinstance(custom_variables, dict):
        for key, value in custom_variables.items():
            normalized_key = re.sub(r'[^a-z0-9]+', '_', str(key or '').strip().lower()).strip('_')
            if not normalized_key:
                continue
            custom_replacements[normalized_key] = '' if value is None else str(value)

    def replace_match(match):
        token = match.group(1)
        if token in standard_replacements:
            return standard_replacements[token]
        normalized_token = re.sub(r'[^a-z0-9]+', '_', token.strip().lower()).strip('_')
        if normalized_token in custom_replacements:
            return custom_replacements[normalized_token]
        return match.group(0)

    return MERGE_TAG_PATTERN.sub(replace_match, base)


def personalize_email(template_subject, template_body, lead):
    """
    Personalize an email template for one lead with the configured AI provider.
    Falls back to plain merge-tag substitution whenever AI is off or fails.
    """
    merged_subject = _apply_merge_tags(template_subject, lead)
    merged_body = _apply_merge_tags(template_body, lead)
    if not template_body or not ai_is_configured():
        return merged_subject, merged_body

    try:
        organization = lead.organization
    except Exception:
        organization = None
    if organization and not getattr(organization, 'enable_ai_personalization', True):
        return merged_subject, merged_body

    prompt = f"""
You are an expert sales representative. Lightly personalize the cold email below.
The SENDER wrote this email. The RECIPIENT is the lead below, who works at a different company.

Recipient (the lead):
Name: {lead.first_name} {lead.last_name}
Company: {lead.company}

Original Subject: {merged_subject}
Original Body:
{merged_body}

Requirements:
- Write from the sender to the recipient. Never write as if the sender works at {lead.company or "the recipient's company"}.
- Keep the core message, the greeting and the original sign-off. Keep paragraph breaks.
- Make it sound natural and tailored to the recipient's company. Do not invent facts.
- Never add placeholders such as [Your Name].
- Return ONLY a JSON object with 'subject' and 'body' keys.
"""

    provider = get_ai_provider()
    # Two attempts: small local models occasionally ignore instructions, so a
    # rejected draft gets one retry before falling back to the plain template.
    for attempt in range(2):
        try:
            if provider == 'ollama':
                text = _ollama_chat([{'role': 'user', 'content': prompt}], temperature=0.4 if attempt == 0 else 0.2)
            elif provider == 'gemini':
                import google.generativeai as genai
                # A tenant-level key takes precedence over the global one.
                genai.configure(api_key=getattr(organization, 'gemini_api_key', None) or _get_gemini_api_key())
                # Model is configurable because Google retires model versions (gemini-2.0-flash now 404s)
                model = genai.GenerativeModel(getattr(settings, 'GEMINI_MODEL', 'gemini-3.8-flash'))
                text = model.generate_content(prompt).text
            else:
                return merged_subject, merged_body

            result = _parse_json_payload(text)
            if not isinstance(result, dict) or not result.get('body'):
                raise ValueError('AI response did not contain a usable subject/body JSON object.')
            subject = _apply_merge_tags(_normalize_placeholders(str(result.get('subject') or merged_subject)), lead)
            body = _apply_merge_tags(_normalize_placeholders(str(result['body'])), lead)
            if _is_safe_personalization(merged_body, subject, body):
                return subject, body
            logger.warning(f"AI personalization rejected for {lead.email} (placeholder or lost sign-off); attempt {attempt + 1}")
        except Exception as e:
            logger.error(f"AI personalization error ({provider}): {e}")
            break
    return merged_subject, merged_body
