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


import json
from django.utils import timezone
import google.generativeai as genai
from .models import LeadScrapeJob, Lead


logger = logging.getLogger(__name__)

@shared_task
def scrape_leads_task(job_id, query, limit, organization_id):
    try:
        # 1. Update the job status to RUNNING
        job = LeadScrapeJob.objects.get(id=job_id)
        job.status = 'RUNNING'
        job.started_at = timezone.now()
        job.save()

        org = Organization.objects.get(id=organization_id)

        # 2. Configure the Gemini model
        # Using gemini-2.0-flash as specified in the issue architecture requirements
        model = genai.GenerativeModel('gemini-2.5-flash')
        
        prompt = f"""
        You are an advanced automated B2B lead generation assistant.
        Generate exactly {limit} highly realistic business or professional leads matching the prospecting query: "{query}".
        
        Return the response strictly as a JSON array containing objects with the following keys:
        - first_name (string or null)
        - last_name (string or null)
        - email (string, must be a valid email structure)
        - company (string or null)
        - phone (string, include country code if possible, or null)
        - linkedin_url (string, valid LinkedIn URL format, or null)
        
        Do not wrap the response in markdown code blocks like ```json ... ```. Output raw JSON only.
        """

        # 3. Call the API
        response = model.generate_content(prompt)
        
        # Clean response text in case markdown tags sneaked in
        clean_text = response.text.strip()
        if clean_text.startswith("```json"):
            clean_text = clean_text[7:]
        if clean_text.endswith("```"):
            clean_text = clean_text[:-3]
        clean_text = clean_text.strip()

        leads_data = json.loads(clean_text)
        
        if not isinstance(leads_data, list):
            raise ValueError("Gemini did not return a valid list array of leads.")

        leads_created = 0

        # 4. Filter and process records dynamically
        for item in leads_data:
            email = (item.get('email') or '').strip().lower()
            if not email:
                continue

            # Deduplicate against existing emails within this specific organization tenant
            if Lead.objects.filter(organization=org, email=email).exists():
                continue

            # Safely build standard parameters and provide structural defaults
            # Including 'custom_variables' fixes the NOT NULL constraint failure mentioned in the PR feedback
            Lead.objects.create(
                organization_id=organization_id,
                email=email,
                first_name=item.get('first_name'),
                last_name=item.get('last_name'),
                company=item.get('company'),
                phone=item.get('phone'),
                linkedin_url=item.get('linkedin_url'),
                custom_variables={}
            )
            leads_created += 1

        # 5. Finalize status tracking model
        job.status = 'COMPLETED'
        job.leads_found = leads_created
        job.completed_at = timezone.now()
        job.save()

        logger.info(f"Scrape job {job_id} finalized successfully. Found {leads_created} records.")

    except Exception as e:
        logger.exception(f"AI Lead Scraper crashed for job {job_id}")
        try:
            job = LeadScrapeJob.objects.get(id=job_id)
            job.status = 'FAILED'
            job.error_message = str(e)
            job.completed_at = timezone.now()
            job.save()
        except Exception:
            pass