import json
import logging
import re

from django.utils import timezone

from .models import Lead

logger = logging.getLogger(__name__)

_MISSING = object()


def _normalize_key(value):
    return re.sub(r'[^a-z0-9]', '', (value or '').strip().lower())


def _normalize_phone(phone):
    if not phone:
        return None

    phone = str(phone).strip()
    if not phone:
        return None

    if phone.startswith('+'):
        return phone

    phone = re.sub(r'[^0-9]', '', phone)
    if not phone:
        return None

    # Preserve the previous import behavior so CSV and CRM sync stay aligned.
    if len(phone) == 10:
        return '+91' + phone
    if len(phone) == 12 and phone.startswith('91'):
        return '+' + phone
    return '+' + phone


def _normalize_payload(record):
    normalized = {}
    for key, value in (record or {}).items():
        normalized[_normalize_key(key)] = value
    return normalized


def _extract_value(record, *keys):
    for key in keys:
        value = record.get(_normalize_key(key), _MISSING)
        if value is _MISSING:
            continue
        if isinstance(value, str):
            value = value.strip()
            if not value:
                continue
        return value
    return _MISSING


def sync_lead_record(organization, record, source='crm-api'):
    normalized = _normalize_payload(record)
    email = _extract_value(normalized, 'email', 'work_email', 'email_address')
    if email is _MISSING:
        return {
            'status': 'skipped',
            'reason': 'Missing email',
            'lead': None,
            'created': False,
        }

    lead, created = Lead.objects.get_or_create(
        organization=organization,
        email=email,
    )

    for field_name, aliases in (
        ('first_name', ('first_name', 'firstname', 'first name')),
        ('last_name', ('last_name', 'lastname', 'last name')),
        ('company', ('company', 'company_name', 'companyname', 'organization')),
        ('phone', ('phone', 'phone_number', 'phone number', 'phonenumber')),
        ('linkedin_url', ('linkedin_url', 'linkedin', 'linkedinurl', 'linkedin profile', 'linkedin_profile')),
    ):
        value = _extract_value(normalized, *aliases)
        if value is _MISSING:
            continue
        if field_name == 'phone':
            value = _normalize_phone(value)
        setattr(lead, field_name, value)

    custom_data = _extract_value(normalized, 'custom_data', 'customdata', 'metadata')
    if custom_data is not _MISSING:
        if isinstance(custom_data, str):
            try:
                custom_data = json.loads(custom_data)
            except json.JSONDecodeError:
                logger.warning(
                    "Skipping malformed custom_data payload for %s in org %s",
                    email,
                    organization.id,
                )
                custom_data = None
        if isinstance(custom_data, dict):
            existing_custom_data = lead.custom_data if isinstance(lead.custom_data, dict) else {}
            lead.custom_data = {**existing_custom_data, **custom_data}

    external_id = _extract_value(
        normalized,
        'external_id',
        'externalid',
        'crm_id',
        'crm_id',
        'source_id',
        'id',
    )
    if external_id is not _MISSING:
        lead.crm_external_id = str(external_id)

    global_unsubscribe = _extract_value(normalized, 'global_unsubscribe', 'globalunsubscribe', 'unsubscribed')
    if global_unsubscribe is not _MISSING:
        lead.global_unsubscribe = bool(global_unsubscribe)

    lead.crm_source = source
    lead.crm_synced_at = timezone.now()

    lead.save()

    return {
        'status': 'created' if created else 'updated',
        'reason': None,
        'lead': lead,
        'created': created,
    }


def sync_lead_records(organization, records, source='crm-api'):
    summary = {
        'created': 0,
        'updated': 0,
        'skipped': 0,
        'errors': [],
        'leads': [],
    }

    for index, record in enumerate(records):
        outcome = sync_lead_record(organization, record, source=source)
        if outcome['status'] == 'skipped':
            summary['skipped'] += 1
            summary['errors'].append({
                'index': index,
                'reason': outcome['reason'],
            })
            continue

        summary[outcome['status']] += 1
        summary['leads'].append(outcome['lead'])

    return summary
