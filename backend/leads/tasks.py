import csv
import io
import re
from celery import shared_task
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from .models import Lead
from .models import LeadImportJob
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


@shared_task
def import_leads_from_csv(file_contents, organization_id, import_job_id=None, filename=''):
    org = Organization.objects.get(id=organization_id)
    import_job = None
    if import_job_id:
        try:
            import_job = LeadImportJob.objects.get(id=import_job_id, organization=org)
        except LeadImportJob.DoesNotExist:
            import_job = None

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
    total_rows = 0
    error_log = []
    seen_emails = set()

    for row_number, row in enumerate(reader, start=2):
        total_rows += 1
        normalized_row = _normalize_row(row)
        email = _get_field(normalized_row, 'email', 'work_email', 'email_address')
        if not email:
            skipped += 1
            error_log.append({
                'row': row_number,
                'email': '',
                'error': 'Email is required',
            })
            continue

        if email.lower() in seen_emails:
            skipped += 1
            error_log.append({
                'row': row_number,
                'email': email,
                'error': 'Duplicate email in CSV',
            })
            continue
        seen_emails.add(email.lower())

        try:
            validate_email(email)
        except ValidationError:
            skipped += 1
            error_log.append({
                'row': row_number,
                'email': email,
                'error': 'Invalid email format',
            })
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
        try:
            _, created = Lead.objects.update_or_create(
                organization=org,
                email=email,
                defaults={
                    'first_name': first_name,
                    'last_name': last_name,
                    'company': company,
                    'linkedin_url': linkedin_url or None,
                    'phone': phone or None,
                }
            )
        except Exception as exc:
            skipped += 1
            error_log.append({
                'row': row_number,
                'email': email,
                'error': str(exc),
            })
            logger.exception("Lead import failed for %s row %s", email, row_number)
            continue

        if created:
            leads_created += 1
        else:
            leads_updated += 1

    summary = f"Processed {leads_created} new, {leads_updated} updated, {skipped} skipped for organization {org.name}"
    if import_job:
        import_job.filename = filename or import_job.filename
        import_job.total_rows = total_rows
        import_job.imported_count = leads_created + leads_updated
        import_job.failed_count = skipped
        import_job.error_log = error_log
        import_job.save(update_fields=['filename', 'total_rows', 'imported_count', 'failed_count', 'error_log', 'updated_at'])
    logger.info(summary)
    return summary
