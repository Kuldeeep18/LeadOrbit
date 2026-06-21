"""
Django signals to automatically maintain cached counters on Campaign model.
This ensures real-time consistency when CampaignLead records are modified.
"""

from django.db.models.signals import post_save, post_delete, pre_save
from django.dispatch import receiver
from .models import CampaignLead, Campaign
from leads.models import Lead


def _update_campaign_counters(campaign):
    """
    Recalculate and update all cached counters for a campaign.
    Called when a CampaignLead changes.
    """
    from django.db.models import Q
    
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


def _calculate_lead_score(lead):
    """
    Derive a simple engagement score for a lead from related CampaignLead rows.
    """
    qs = CampaignLead.objects.filter(lead=lead)
    open_count = qs.filter(last_opened_at__isnull=False).count()
    click_count = qs.filter(last_clicked_at__isnull=False).count()
    reply_count = qs.filter(status='REPLIED').count()
    bounced_count = qs.filter(status='BOUNCED').count()
    active_count = qs.filter(status='ACTIVE').count()

    score = (
        (open_count * 5)
        + (click_count * 7)
        + (reply_count * 10)
        + (active_count * 2)
        - (bounced_count * 5)
        - (5 if lead.global_unsubscribe else 0)
    )
    return max(score, 0)


def _update_lead_score(lead):
    lead.score = _calculate_lead_score(lead)
    lead.save(update_fields=['score'])


@receiver(post_save, sender=CampaignLead)
def update_campaign_counters_on_save(sender, instance, created, **kwargs):
    """
    When a CampaignLead is created or updated, recalculate campaign counters.
    """
    campaign = instance.campaign
    _update_campaign_counters(campaign)
    _update_lead_score(instance.lead)


@receiver(post_delete, sender=CampaignLead)
def update_campaign_counters_on_delete(sender, instance, **kwargs):
    """
    When a CampaignLead is deleted, recalculate campaign counters.
    We need to check if the campaign still exists (it might have been cascade deleted).
    """
    try:
        campaign = Campaign.objects.get(id=instance.campaign_id)
        _update_campaign_counters(campaign)
    except Campaign.DoesNotExist:
        # Campaign was already deleted, nothing to update
        pass
    try:
        lead = Lead.objects.get(id=instance.lead_id)
        _update_lead_score(lead)
    except Lead.DoesNotExist:
        # Lead was already deleted, nothing to update
        pass
