from django.conf import settings
import logging

logger = logging.getLogger(__name__)


def _get_gemini_api_key():
    return (getattr(settings, 'GEMINI_API_KEY', '') or '').strip()


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
        import json
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
