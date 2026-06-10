import csv
import io
import re
from celery import shared_task
from .models import Lead
from tenants.models import Organization
import logging

logger = logging.getLogger(__name__)


def _normalize_key(value):
    return re.sub(r'[^a-z0-9]', '', (value or '').strip().lower())


def _normalize_row(row):
    normalized = {}
    for key, value in row.items():
        normalized[_normalize_key(key)] = (value or '').strip()
    return normalized


def _get_field(row, *keys):
    """Return the first non-empty value found for any of the given key aliases."""
    for key in keys:
        val = row.get(_normalize_key(key), '')
        if val:
            return val
    return ''


def _to_custom_variable_key(value):
    value = (value or '').strip().lower()
    value = re.sub(r'[^a-z0-9]+', '_', value)
    return value.strip('_')


def _collect_custom_variables(raw_row):
    custom_variables = {}
    standard_keys = {
        _normalize_key(alias)
        for aliases in (
            ('email', 'work_email', 'email_address'),
            ('firstName', 'first_name', 'firstname', 'first name'),
            ('lastName', 'last_name', 'lastname', 'last name'),
            ('companyName', 'company', 'company_name', 'organization'),
            ('linkedinUrl', 'linkedin_url', 'linkedin', 'linkedin_profile'),
            ('phone', 'phoneNumber', 'phone_number', 'mobile', 'phone number'),
        )
        for alias in aliases
    }

    for key, value in raw_row.items():
        if _normalize_key(key) in standard_keys:
            continue
        cleaned_value = (value or '').strip()
        if not cleaned_value:
            continue
        custom_key = _to_custom_variable_key(key)
        if custom_key:
            custom_variables[custom_key] = cleaned_value

    return custom_variables


@shared_task
def import_leads_from_csv(file_contents, organization_id):
    org = Organization.objects.get(id=organization_id)

    # Parse the CSV contents
    file_contents = file_contents.lstrip('\ufeff')
    stream = io.StringIO(file_contents)
    sample = file_contents[:2048]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=',;\t')
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(stream, dialect=dialect)

    leads_created = 0
    leads_updated = 0
    skipped = 0

    for row in reader:
        normalized_row = _normalize_row(row)
        email = _get_field(normalized_row, 'email', 'work_email', 'email_address')
        if not email:
            skipped += 1
            continue

        # Flexible aliases for common exports (Lemlist, HubSpot, custom CSVs)
        first_name = _get_field(normalized_row, 'firstName', 'first_name', 'firstname', 'first name')
        last_name = _get_field(normalized_row, 'lastName', 'last_name', 'lastname', 'last name')
        company = _get_field(normalized_row, 'companyName', 'company', 'company_name', 'organization')
        linkedin_url = _get_field(normalized_row, 'linkedinUrl', 'linkedin_url', 'linkedin', 'linkedin_profile')
        phone = _get_field(normalized_row, 'phone', 'phoneNumber', 'phone_number', 'mobile', 'phone number')

        # Normalize phone to E.164 format (add +91 for 10-digit Indian numbers)
        if phone and not phone.startswith('+'):
            phone = re.sub(r'[^0-9]', '', phone)  # strip non-digits
            if len(phone) == 10:
                phone = '+91' + phone
            elif len(phone) == 12 and phone.startswith('91'):
                phone = '+' + phone
            else:
                phone = '+' + phone  # best-effort prefix

        # Create or update Lead for this organization
        lead, created = Lead.objects.get_or_create(
            organization=org,
            email=email,
        )
        lead.first_name = first_name
        lead.last_name = last_name
        lead.company = company
        lead.linkedin_url = linkedin_url or None
        lead.phone = phone or None
        incoming_custom_variables = _collect_custom_variables(row)
        existing_custom_variables = lead.custom_variables if isinstance(lead.custom_variables, dict) else {}
        if incoming_custom_variables or existing_custom_variables:
            lead.custom_variables = {**existing_custom_variables, **incoming_custom_variables}
        lead.save()
        if created:
            leads_created += 1
        else:
            leads_updated += 1

    summary = f"Processed {leads_created} new, {leads_updated} updated, {skipped} skipped for organization {org.name}"
    logger.info(summary)
    return summary
