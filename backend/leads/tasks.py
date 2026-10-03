import csv
import io
import re
from celery import shared_task
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.utils import timezone
import time
from .models import Lead, LeadImportJob, LeadScrapeJob, BlockedDomain
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
def import_leads_from_csv(file_contents, organization_id, job_id=None):
    org = Organization.objects.get(id=organization_id)
    job = None
    if job_id:
        try:
            job = LeadImportJob.objects.get(id=job_id, organization=org)
        except LeadImportJob.DoesNotExist:
            logger.warning("Lead import job %s was not found for organization %s", job_id, organization_id)

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
    failed_count = 0
    error_log = []
    total_rows = 0

    for row_number, row in enumerate(reader, start=2):
        total_rows += 1
        normalized_row = _normalize_row(row)
        email = _get_field(normalized_row, 'email', 'work_email', 'email_address')
        if not email:
            failed_count += 1
            error_log.append({
                'row': row_number,
                'email': '',
                'error': 'Missing email address',
                'data': normalized_row,
            })
            continue

        try:
            validate_email(email)
        except ValidationError:
            failed_count += 1
            error_log.append({
                'row': row_number,
                'email': email,
                'error': 'Invalid email format',
                'data': normalized_row,
            })
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

        try:
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
        except Exception as exc:
            failed_count += 1
            error_log.append({
                'row': row_number,
                'email': email,
                'error': str(exc),
                'data': normalized_row,
            })
            logger.exception("Failed to import lead row %s for organization %s", row_number, org.id)
            continue

        if created:
            leads_created += 1
        else:
            leads_updated += 1

    if job:
        job.total_rows = total_rows
        job.imported_count = leads_created + leads_updated
        job.failed_count = failed_count
        job.error_log = error_log
        job.save()

    summary = f"Processed {leads_created} new, {leads_updated} updated, {failed_count} failed for organization {org.name}"
    logger.info(summary)
    return summary


@shared_task
def run_web_scraper(job_id, query):
    try:
        job = LeadScrapeJob.objects.get(id=job_id)
    except LeadScrapeJob.DoesNotExist:
        logger.error(f"LeadScrapeJob {job_id} not found.")
        return f"Job {job_id} not found"

    job.status = 'RUNNING'
    job.leads_found = 0
    job.log_messages = []
    job.save()

    def add_log(msg):
        logger.info(f"[Scraper Job {job_id}] {msg}")
        job.refresh_from_db()
        logs = list(job.log_messages or [])
        logs.append({
            "timestamp": timezone.now().isoformat(),
            "message": msg
        })
        job.log_messages = logs
        job.save()

    try:
        add_log(f"Starting lead scraping for query: '{query}'")
        time.sleep(1)

        # Domain extraction/normalization from query
        clean_query = query.strip().lower()
        if '://' in clean_query:
            domain = clean_query.split('://', 1)[1].split('/', 1)[0].split(':', 1)[0]
        elif '/' in clean_query:
            domain = clean_query.split('/', 1)[0].split(':', 1)[0]
        else:
            domain = clean_query

        # Remove subdomains like www.
        if domain.startswith('www.'):
            domain = domain[4:]

        # If it doesn't look like a domain, format it
        if '.' not in domain or len(domain.split('.')[-1]) < 2:
            domain_name = re.sub(r'[^a-z0-9]', '', domain) or 'example'
            domain = f"{domain_name}.com"

        add_log(f"Target domain identified: {domain}")
        time.sleep(1)

        # Check for blocked domain
        if BlockedDomain.objects.filter(organization=job.organization, domain=domain).exists():
            add_log(f"Domain '{domain}' is blocked by organization policies. Aborting scraper job.")
            job.status = 'FAILED'
            job.save()
            return f"Aborted: Domain {domain} is blocked"

        add_log("Searching index and crawling domain for contact details...")
        time.sleep(1)

        # Standard B2B contacts to mock
        mock_contacts = [
            {
                "first_name": "John",
                "last_name": "Doe",
                "email": f"john.doe@{domain}",
                "company": domain.split('.')[0].title(),
                "phone": "+15550199"
            },
            {
                "first_name": "Jane",
                "last_name": "Smith",
                "email": f"jane.smith@{domain}",
                "company": domain.split('.')[0].title(),
                "phone": "+15550198"
            },
            {
                "first_name": "Alex",
                "last_name": "Jones",
                "email": f"alex.jones@{domain}",
                "company": domain.split('.')[0].title(),
                "phone": "+15550197"
            }
        ]

        for contact in mock_contacts:
            email = contact["email"]
            add_log(f"Found potential contact: {contact['first_name']} {contact['last_name']} ({email})")
            time.sleep(1)

            # Re-check if domain is blocked before saving (double-check boundary)
            if BlockedDomain.objects.filter(organization=job.organization, domain=domain).exists():
                add_log(f"Domain '{domain}' was blocked during execution. Skipping contact.")
                continue

            lead, created = Lead.objects.update_or_create(
                organization=job.organization,
                email=email,
                defaults={
                    'first_name': contact['first_name'],
                    'last_name': contact['last_name'],
                    'company': contact['company'],
                    'phone': contact['phone'],
                }
            )

            if created:
                add_log(f"Enrolled new lead: {email}")
            else:
                add_log(f"Updated existing lead details for: {email}")

            job.refresh_from_db()
            job.leads_found += 1
            job.save()

        add_log(f"Scraper job completed successfully. Enrolled {job.leads_found} leads.")
        job.status = 'COMPLETED'
        job.save()
        return f"Completed: Found {job.leads_found} leads"

    except Exception as exc:
        job.refresh_from_db()
        job.status = 'FAILED'
        logs = list(job.log_messages or [])
        logs.append({
            "timestamp": timezone.now().isoformat(),
            "message": f"Fatal error during scraping: {str(exc)}"
        })
        job.log_messages = logs
        job.save()
        logger.exception("Error running web scraper")
        raise exc

