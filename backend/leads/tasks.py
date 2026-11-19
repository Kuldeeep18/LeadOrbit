import csv
import io
import re
import json
import unicodedata
from celery import shared_task
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction, IntegrityError
from .models import Lead, LeadTag, Tag
from .models import LeadImportJob
from tenants.models import Organization
import logging

logger = logging.getLogger(__name__)

STANDARD_FIELD_ALIASES = {
    'email': ('email', 'work_email', 'email_address'),
    'first_name': ('firstName', 'first_name', 'firstname', 'first name'),
    'last_name': ('lastName', 'last_name', 'lastname', 'last name'),
    'company': ('companyName', 'company', 'company_name', 'organization'),
    'title': ('title', 'job_title', 'jobtitle'),
    'status': ('status',),
    'tags': ('tags',),
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


def _unprotect_csv_formula(value):
    if not value or not value.startswith("'"):
        return value
    remainder = value[1:]
    index = 0
    while index < len(remainder):
        char = remainder[index]
        category = unicodedata.category(char)
        if char.isspace() or ord(char) < 32 or 127 <= ord(char) <= 159 or category in ('Cf', 'Zl', 'Zp'):
            index += 1
            continue
        break
    if index < len(remainder) and remainder[index] in ('=', '+', '-', '@'):
        return remainder
    return value


def _parse_import_tags(value):
    if not value:
        return []

    value = str(value)
    if value.startswith('json:'):
        try:
            parsed = json.loads(value[5:])
        except (json.JSONDecodeError, TypeError):
            parsed = None
        if isinstance(parsed, list):
            names = []
            seen = set()
            for raw_name in parsed:
                name = _unprotect_csv_formula(str(raw_name).strip())
                key = name.casefold()
                if name and key not in seen:
                    seen.add(key)
                    names.append(name)
            return names

    names = []
    seen = set()
    for name in str(value).split(';'):
        name = _unprotect_csv_formula(name.strip())
        key = name.casefold()
        if name and key not in seen:
            seen.add(key)
            names.append(name)
    return names


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
        first_name = _unprotect_csv_formula(
            _get_field(normalized_row, 'firstName', 'first_name', 'firstname', 'first name')
        )
        last_name = _unprotect_csv_formula(
            _get_field(normalized_row, 'lastName', 'last_name', 'lastname', 'last name')
        )
        company = _unprotect_csv_formula(
            _get_field(normalized_row, 'companyName', 'company', 'company_name', 'organization')
        )
        title = _unprotect_csv_formula(
            _get_field(normalized_row, 'title', 'job_title', 'jobtitle')
        )
        linkedin_url = _get_field(normalized_row, 'linkedinUrl', 'linkedin_url', 'linkedin', 'linkedin_profile')
        phone = _unprotect_csv_formula(
            _get_field(normalized_row, 'phone', 'phoneNumber', 'phone_number', 'mobile', 'phone number')
        )
        status_value = _get_field(normalized_row, 'status').strip().lower()
        tags_value = _unprotect_csv_formula(
            _get_field(normalized_row, 'tags')
        )
        import_tags = _parse_import_tags(tags_value)
        has_tags_column = any(_normalize_key(key) == 'tags' for key in row)
        custom_variables = _extract_custom_variables(row)

        export_headers = {'email', 'firstname', 'lastname', 'company', 'title', 'phone', 'status', 'tags', 'createdat'}
        normalized_headers = {_normalize_key(key) for key in row}
        round_trip_export = export_headers.issubset(normalized_headers)

        # Preserve phone formatting for exporter round trips. Retain the existing
        # best-effort normalization for legacy imports that predate status/tags.
        if phone and not phone.startswith('+') and not round_trip_export:
            phone = re.sub(r'[^0-9]', '', phone)
            if len(phone) == 10:
                phone = '+91' + phone
            elif len(phone) == 12 and phone.startswith('91'):
                phone = '+' + phone
            else:
                phone = '+' + phone

        try:
            with transaction.atomic():
                org_lock = Organization.objects.select_for_update().filter(pk=org.pk).first()
                if org_lock is not None:
                    org = org_lock
                # Create or update the Lead for this organization. Matching is case-insensitive
                # so "John@Acme.com" and "john@acme.com" stay one lead and get one email.
                fields = {
                    'first_name': first_name,
                    'last_name': last_name,
                    'company': company,
                    'linkedin_url': linkedin_url or None,
                    'phone': phone or None,
                    'custom_variables': custom_variables,
                }
                if title:
                    fields['custom_variables'] = {
                        **custom_variables,
                        'title': title,
                    }
                if status_value == 'unsubscribed':
                    fields['global_unsubscribe'] = True
                elif status_value == 'active':
                    fields['global_unsubscribe'] = False

                lead = Lead.objects.select_for_update().filter(
                    organization=org,
                    email__iexact=email,
                ).first()
                created = lead is None
                if created:
                    try:
                        with transaction.atomic():
                            lead = Lead.objects.create(organization=org, email=email, **fields)
                    except IntegrityError:
                        lead = Lead.objects.select_for_update().filter(
                            organization=org,
                            email__iexact=email,
                        ).first()
                        if lead is None:
                            raise
                        created = False
                        for name, value in fields.items():
                            setattr(lead, name, value)
                        lead.save(update_fields=[*fields.keys()])
                else:
                    for name, value in fields.items():
                        setattr(lead, name, value)
                    lead.save()

                if has_tags_column:
                    desired_tags = []
                    seen_tag_ids = set()
                    for tag_name in import_tags:
                        tag = Tag.objects.filter(
                            organization=org,
                            name__iexact=tag_name,
                        ).first()
                        if tag is None:
                            try:
                                with transaction.atomic():
                                    tag, _ = Tag.objects.get_or_create(
                                        organization=org,
                                        name=tag_name,
                                        defaults={'color': '#6366f1'},
                                    )
                            except IntegrityError:
                                tag = Tag.objects.filter(
                                    organization=org,
                                    name__iexact=tag_name,
                                ).first()
                                if tag is None:
                                    raise
                        if tag.id not in seen_tag_ids:
                            seen_tag_ids.add(tag.id)
                            desired_tags.append(tag)

                    LeadTag.objects.filter(lead=lead).exclude(
                        tag_id__in=[tag.id for tag in desired_tags]
                    ).delete()
                    for tag in desired_tags:
                        LeadTag.objects.get_or_create(
                            organization=org,
                            lead=lead,
                            tag=tag,
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
