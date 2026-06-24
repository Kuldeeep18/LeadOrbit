from django.core.management.base import BaseCommand

from leads.models import Lead
from campaigns.signals import _calculate_lead_score


class Command(BaseCommand):
    help = 'Backfill lead scores from related campaign engagement data.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--lead-id',
            type=str,
            default=None,
            help='Optional: backfill only a single lead by ID.',
        )

    def handle(self, *args, **options):
        lead_id = options.get('lead_id')
        leads = Lead.objects.all()
        if lead_id:
            leads = leads.filter(id=lead_id)

        processed = 0
        pending_updates = []
        batch_size = 500
        for lead in leads.iterator():
            lead.score = _calculate_lead_score(lead)
            processed += 1
            pending_updates.append(lead)

            if len(pending_updates) >= batch_size:
                Lead.objects.bulk_update(pending_updates, ['score'])
                self.stdout.write(f'Processed {processed} lead(s)...')
                pending_updates.clear()

        if pending_updates:
            Lead.objects.bulk_update(pending_updates, ['score'])
            self.stdout.write(f'Processed {processed} lead(s)...')

        self.stdout.write(self.style.SUCCESS(f'Successfully backfilled scores for {processed} lead(s).'))
