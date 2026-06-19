"""
Management command to backfill cached counters on Campaign model.
This command should be run after the migration that adds the counter fields.

Usage:
    python manage.py backfill_campaign_counters
    python manage.py backfill_campaign_counters --batch-size=100
"""

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from campaigns.models import Campaign, CampaignLead


class Command(BaseCommand):
    help = 'Backfill cached counters on Campaign model from CampaignLead data'

    def add_arguments(self, parser):
        parser.add_argument(
            '--batch-size',
            type=int,
            default=50,
            help='Number of campaigns to process per batch (default: 50)',
        )
        parser.add_argument(
            '--campaign-id',
            type=str,
            default=None,
            help='Optional: backfill only a specific campaign by ID',
        )

    def handle(self, *args, **options):
        batch_size = options['batch_size']
        campaign_id = options.get('campaign_id')

        if campaign_id:
            try:
                campaigns = Campaign.objects.filter(id=campaign_id)
                if not campaigns.exists():
                    raise CommandError(f"Campaign with ID {campaign_id} not found")
            except Exception as e:
                raise CommandError(f"Invalid campaign ID: {e}")
        else:
            campaigns = Campaign.objects.all()

        total = campaigns.count()
        self.stdout.write(f"Backfilling counters for {total} campaign(s)...")

        processed = 0
        for i, campaign in enumerate(campaigns, 1):
            self._backfill_campaign(campaign)
            processed += 1

            if i % batch_size == 0:
                self.stdout.write(f"  Processed {i}/{total} campaigns...")

        self.stdout.write(
            self.style.SUCCESS(
                f'\nSuccessfully backfilled {processed} campaign(s)!'
            )
        )

    def _backfill_campaign(self, campaign):
        """Calculate and update all counters for a single campaign."""
        qs = CampaignLead.objects.filter(campaign=campaign)

        # Total enrolled leads
        leads_count = qs.count()

        # Sent: leads with status in ['ACTIVE', 'FINISHED', 'REPLIED', 'BOUNCED']
        sent_count = qs.filter(
            status__in=['ACTIVE', 'FINISHED', 'REPLIED', 'BOUNCED']
        ).count()

        # Opened: leads with last_opened_at not null
        open_count = qs.filter(last_opened_at__isnull=False).count()

        # Replied: leads with status 'REPLIED'
        reply_count = qs.filter(status='REPLIED').count()

        # Clicked: leads with last_clicked_at not null
        clicked_count = qs.filter(last_clicked_at__isnull=False).count()

        # Bounced: leads with status 'BOUNCED'
        bounced_count = qs.filter(status='BOUNCED').count()

        # Update campaign with all new counts
        campaign.leads_count = leads_count
        campaign.sent_count = sent_count
        campaign.open_count = open_count
        campaign.reply_count = reply_count
        campaign.clicked_count = clicked_count
        campaign.bounced_count = bounced_count
        campaign.save(
            update_fields=[
                'leads_count',
                'sent_count',
                'open_count',
                'reply_count',
                'clicked_count',
                'bounced_count',
            ]
        )
