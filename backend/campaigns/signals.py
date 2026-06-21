"""
Django signals to automatically maintain cached counters on Campaign model.
This keeps campaign metrics in sync without re-counting every lead on each write.
"""

from django.db import models
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from .models import Campaign, CampaignLead


def _counter_snapshot_from_values(values):
    if not values:
        return None

    return {
        'campaign_id': values['campaign_id'],
        'leads_count': 1,
        'sent_count': int(values['status'] in ['ACTIVE', 'FINISHED', 'REPLIED', 'BOUNCED']),
        'open_count': int(values['last_opened_at'] is not None),
        'reply_count': int(values['status'] == 'REPLIED'),
        'clicked_count': int(values['last_clicked_at'] is not None),
        'bounced_count': int(values['status'] == 'BOUNCED'),
    }


def _counter_snapshot_from_instance(instance):
    return _counter_snapshot_from_values({
        'campaign_id': instance.campaign_id,
        'status': instance.status,
        'last_opened_at': instance.last_opened_at,
        'last_clicked_at': instance.last_clicked_at,
    })


def _campaign_counter_delta(before, after):
    keys = ['leads_count', 'sent_count', 'open_count', 'reply_count', 'clicked_count', 'bounced_count']
    return {key: after[key] - before[key] for key in keys}


def _counter_values(snapshot):
    return {key: value for key, value in snapshot.items() if key != 'campaign_id'}


def _apply_campaign_counter_delta(campaign_id, delta):
    if campaign_id is None:
        return

    update_kwargs = {}
    for field, value in delta.items():
        if value:
            update_kwargs[field] = models.F(field) + value

    if update_kwargs:
        Campaign.objects.filter(id=campaign_id).update(**update_kwargs)


@receiver(pre_save, sender=CampaignLead)
def store_previous_campaign_counter_snapshot(sender, instance, **kwargs):
    """
    Cache the previous row state so we can apply incremental counter deltas.
    """
    if not instance.pk:
        instance._counter_snapshot_before = None
        return

    previous = CampaignLead.objects.filter(pk=instance.pk).values(
        'campaign_id',
        'status',
        'last_opened_at',
        'last_clicked_at',
    ).first()
    instance._counter_snapshot_before = _counter_snapshot_from_values(previous)


@receiver(post_save, sender=CampaignLead)
def update_campaign_counters_on_save(sender, instance, created, **kwargs):
    """
    When a CampaignLead is created or updated, apply the counter delta instead
    of recalculating the full campaign aggregate.
    """
    after = _counter_snapshot_from_instance(instance)
    before = getattr(instance, '_counter_snapshot_before', None)

    if created or before is None:
        _apply_campaign_counter_delta(instance.campaign_id, _counter_values(after))
        return

    if before['campaign_id'] == after['campaign_id']:
        _apply_campaign_counter_delta(after['campaign_id'], _campaign_counter_delta(before, after))
        return

    _apply_campaign_counter_delta(before['campaign_id'], {key: -value for key, value in _counter_values(before).items()})
    _apply_campaign_counter_delta(after['campaign_id'], _counter_values(after))


@receiver(post_delete, sender=CampaignLead)
def update_campaign_counters_on_delete(sender, instance, **kwargs):
    """
    When a CampaignLead is deleted, subtract its contribution from the campaign.
    We need to check if the campaign still exists (it might have been cascade deleted).
    """
    try:
        campaign = Campaign.objects.get(id=instance.campaign_id)
    except Campaign.DoesNotExist:
        return

    snapshot = _counter_snapshot_from_instance(instance)
    negated = {key: -value for key, value in _counter_values(snapshot).items()}
    _apply_campaign_counter_delta(campaign.id, negated)
