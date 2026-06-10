import csv
import io
from celery import shared_task
from tenants.models import Organization
import logging

from .sync import sync_lead_records

logger = logging.getLogger(__name__)


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
    lead_objects = []

    records = []
    for row in reader:
        records.append(row)

    summary = sync_lead_records(org, records, source='csv')
    lead_objects = summary['leads']
    leads_created = summary['created']
    leads_updated = summary['updated']
    skipped = summary['skipped']

    try:
        from campaigns.tasks import auto_enroll_lead_into_active_campaigns

        for lead in lead_objects:
            auto_enroll_lead_into_active_campaigns(lead)
    except Exception as exc:
        logger.warning("Auto-enroll skipped for CSV import in org %s: %s", org.id, exc)

    summary = f"Processed {leads_created} new, {leads_updated} updated, {skipped} skipped for organization {org.name}"
    logger.info(summary)
    return summary
