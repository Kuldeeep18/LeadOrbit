import json
import logging
import re

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def _get_gemini_api_key():
    return (getattr(settings, 'GEMINI_API_KEY', '') or '').strip()


def _get_openrouter_api_key():
    return (getattr(settings, 'OPENROUTER_API_KEY', '') or '').strip()


def _get_openrouter_model():
    return (getattr(settings, 'OPENROUTER_MODEL', '') or 'openai/gpt-4o-mini').strip()


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


def _fallback_email_copy(prompt, current_subject='', current_body=''):
    topic = (prompt or 'your outreach goal').strip()
    subject = (current_subject or 'Quick idea for {{company}}').strip()
    body = (current_body or (
        'Hi {{firstName}},\n\n'
        'I wanted to reach out with a short note about how we can help {{company}}. '
        'I believe there is a practical opportunity to improve results without adding process overhead.\n\n'
        'If this is relevant, would you be open to a quick conversation next week?\n\n'
        'Best,\n'
        'Your Name'
    )).strip()
    assistant_message = (
        'I drafted a concise outreach email based on your request. '
        f'Focus used: {topic}.'
    )
    return {
        'assistant_message': assistant_message,
        'subject': subject,
        'body': body,
        'provider': 'fallback',
        'model': 'template',
        'fallback': True,
    }


def _coerce_email_result(payload, prompt='', current_subject='', current_body=''):
    if not isinstance(payload, dict):
        return _fallback_email_copy(prompt, current_subject, current_body)

    subject = str(payload.get('subject') or current_subject or 'Quick idea for {{company}}').strip()
    body = str(payload.get('body') or current_body or '').strip()
    assistant_message = str(
        payload.get('assistant_message')
        or payload.get('message')
        or 'I generated an email draft you can review and insert.'
    ).strip()
    if not body:
        return _fallback_email_copy(prompt, subject, current_body)

    return {
        'assistant_message': assistant_message,
        'subject': subject,
        'body': body,
    }


def generate_email_chat_completion(prompt, current_subject='', current_body='', messages=None):
    prompt = (prompt or '').strip()
    messages = messages or []
    if not prompt and not messages:
        raise ValueError('A prompt is required.')

    system_prompt = (
        'You are Lime AI, an expert outbound email assistant for B2B sales teams. '
        'The user will describe what kind of email they want. '
        'Pay close attention to every detail in the user\'s prompt — company names, '
        'product descriptions, value propositions, tone requests, and any specific '
        'information they mention. Incorporate ALL of those details directly into '
        'the email subject and body. Do NOT write generic sales copy. '
        'The email must feel custom-written for the exact scenario the user described. '
        'You may use merge tags like {{firstName}} for the recipient\'s first name '
        'only where it makes sense (e.g. the greeting), but always use the real '
        'company/product/service names the user provides — never replace them with {{company}}. '
        'Respond ONLY with valid JSON using exactly these keys: '
        'assistant_message, subject, body. '
        'assistant_message should be a brief explanation of what you wrote. '
        'subject should be concise and specific to the user\'s request. '
        'body should be plain text email copy with natural line breaks. '
        'Do not include markdown fences or code blocks.'
    )

    conversation = [
        {'role': 'system', 'content': system_prompt},
        {
            'role': 'system',
            'content': (
                f'Current draft subject: {current_subject or "(empty)"}\n'
                f'Current draft body:\n{current_body or "(empty)"}'
            ),
        },
    ]

    for message in messages:
        role = (message or {}).get('role')
        content = ((message or {}).get('content') or '').strip()
        if role in {'user', 'assistant'} and content:
            conversation.append({'role': role, 'content': content})

    if prompt:
        conversation.append({'role': 'user', 'content': prompt})

    openrouter_api_key = _get_openrouter_api_key()
    logger.info('OpenRouter key present: %s, model: %s', bool(openrouter_api_key), _get_openrouter_model())
    if openrouter_api_key:
        try:
            response = requests.post(
                'https://openrouter.ai/api/v1/chat/completions',
                headers={
                    'Authorization': f'Bearer {openrouter_api_key}',
                    'Content-Type': 'application/json',
                    'HTTP-Referer': getattr(settings, 'OPENROUTER_APP_URL', 'http://localhost:8080'),
                    'X-Title': getattr(settings, 'OPENROUTER_APP_NAME', 'Lime Campaign Builder'),
                },
                json={
                    'model': _get_openrouter_model(),
                    'messages': conversation,
                    'temperature': 0.7,
                },
                timeout=60,
            )
            response.raise_for_status()
            payload = response.json()
            raw_content = (
                payload.get('choices', [{}])[0]
                .get('message', {})
                .get('content', '')
            )
            result = _coerce_email_result(
                _parse_json_payload(raw_content),
                prompt=prompt,
                current_subject=current_subject,
                current_body=current_body,
            )
            result['provider'] = 'openrouter'
            result['model'] = _get_openrouter_model()
            return result
        except Exception as exc:
            logger.exception('OpenRouter email generation failed: %s', exc)

    return _fallback_email_copy(prompt, current_subject, current_body)


def _apply_merge_tags(text, lead):
    base = text or ""
    first_name = lead.first_name or ""
    last_name = lead.last_name or ""
    company = lead.company or ""
    email = lead.email or ""

    replacements = {
        "{{first_name}}": first_name,
        "{{firstName}}": first_name,
        "{{last_name}}": last_name,
        "{{lastName}}": last_name,
        "{{company}}": company,
        "{{email}}": email,
    }

    for token, value in replacements.items():
        base = base.replace(token, value)
    return base


def personalize_email(template_subject, template_body, lead):
    """
    Uses Gemini to personalize the given email template for a specific lead.
    """
    api_key = _get_gemini_api_key()
    if not api_key or not template_body:
        # Fallback to simple formatting if no real key is set
        subject = _apply_merge_tags(template_subject, lead)
        body = _apply_merge_tags(template_body, lead)
        return subject, body
        
    prompt = f"""
You are an expert sales representative. Personalize the following email template for a lead.
Lead details:
Name: {lead.first_name} {lead.last_name}
Company: {lead.company}

Original Subject: {template_subject}
Original Body:
{template_body}

Requirements:
- Keep the core message intact.
- Make it sound natural and tailored to the lead's company.
- Return ONLY a JSON object with 'subject' and 'body' keys.
"""

    try:
        import google.generativeai as genai

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(prompt)
        # Parse basic JSON from response...
        # For MVP we will just do simple replacement if JSON parsing fails
        text = response.text.strip()
        if text.startswith("```json"):
            text = text[7:-3]
        
        result = json.loads(text)
        return result.get("subject", template_subject), result.get("body", template_body)
    except Exception as e:
        logger.error(f"Gemini Personalization Error: {e}")
        # Fallback to standard merge tags
        subject = _apply_merge_tags(template_subject, lead)
        body = _apply_merge_tags(template_body, lead)
        return subject, body
