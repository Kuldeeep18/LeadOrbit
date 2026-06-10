import csv
import io
import re
from celery import shared_task
from .models import Lead
from tenants.models import Organization
import logging

logger = logging.getLogger(__name__)

STANDARD_FIELD_ALIASES = {
    'email': ('email', 'work_email', 'email_address'),
    'first_name': ('firstName', 'first_name', 'firstname', 'first name'),
    'last_name': ('lastName', 'last_name', 'lastname', 'last name'),
    'company': ('companyName', 'company', 'company_name', 'organization'),
    'linkedin_url': ('linkedinUrl', 'linkedin_url', 'linkedin', 'linkedin_profile'),
    'phone': ('phone', 'phoneNumber', 'phone_number', 'mobile', 'phone number'),
}


def _normalize_key(value):
    return re.sub(r'[^a-z0-9]', '', (value or '').strip().lower())


def _normalize_custom_variable_key(value):
    return re.sub(r'[^a-z0-9]+', '_', (value or '').strip().lower()).strip('_')


STANDARD_CSV_HEADERS = {
    _normalize_key(alias)
    for aliases in STANDARD_FIELD_ALIASES.values()
    for alias in aliases
}


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


def _extract_custom_variables(row):
    custom_variables = {}
    for key, value in row.items():
        if _normalize_key(key) in STANDARD_CSV_HEADERS:
            continue
        custom_key = _normalize_custom_variable_key(key)
        if not custom_key:
            continue
        custom_variables[custom_key] = (value or '').strip()
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
        custom_variables = _extract_custom_variables(row)

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
        _, created = Lead.objects.update_or_create(
            organization=org,
            email=email,
            defaults={
                'first_name': first_name,
                'last_name': last_name,
                'company': company,
                'linkedin_url': linkedin_url or None,
                'phone': phone or None,
                'custom_variables': custom_variables,
            }
        )
        if created:
            leads_created += 1
        else:
            leads_updated += 1

    summary = f"Processed {leads_created} new, {leads_updated} updated, {skipped} skipped for organization {org.name}"
    logger.info(summary)
    return summary
