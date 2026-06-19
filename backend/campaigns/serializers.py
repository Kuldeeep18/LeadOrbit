from rest_framework import serializers
from django.db.models import Q

from .models import Campaign, CampaignLead, ConnectedEmailAccount, SequenceStep, EmailTemplate

DELAY_UNIT_TO_MINUTES = {
    'minutes': 1,
    'hours': 60,
    'days': 1440,
}

CONDITION_TIME_TO_MINUTES = {
    '1 day': 1440,
    '2 days': 2880,
    '3 days': 4320,
    '1 week': 10080,
}


class SequenceStepSerializer(serializers.ModelSerializer):
    class Meta:
        model = SequenceStep
        fields = ['id', 'step_order', 'channel_type', 'delay_minutes', 'template_subject', 'template_body']


class CampaignSerializer(serializers.ModelSerializer):
    steps = serializers.SerializerMethodField()
    enrolled_count = serializers.IntegerField(source='leads_count', read_only=True)
    enrolled_lead_ids = serializers.SerializerMethodField()
    connected_account = serializers.SerializerMethodField()
    connected_account_id = serializers.UUIDField(write_only=True, required=False, allow_null=True)

    class Meta:
        model = Campaign
        fields = [
            'id',
            'name',
            'status',
            'settings',
            'steps',
            'enrolled_count',
            'enrolled_lead_ids',
            'sent_count',
            'open_count',
            'reply_count',
            'clicked_count',
            'bounced_count',
            'created_at',
            'connected_account',
            'connected_account_id',
        ]

    def get_steps(self, obj):
        return SequenceStepSerializer(obj.steps.all(), many=True).data

    def get_enrolled_lead_ids(self, obj):
        return [str(lead_id) for lead_id in obj.enrolled_leads.values_list('lead_id', flat=True)]

    def get_connected_account(self, obj):
        if not obj.connected_account:
            return None
        return {
            'id': str(obj.connected_account_id),
            'email': obj.connected_account.email_address,
            'provider': obj.connected_account.provider,
        }

    def validate_connected_account_id(self, value):
        if value is None:
            return None
        request = self.context.get('request')
        org = getattr(getattr(request, 'user', None), 'organization', None)
        user = getattr(request, 'user', None)
        exists = ConnectedEmailAccount.objects.filter(
            id=value,
            organization=org,
        ).filter(
            Q(connected_by=user) |
            Q(connected_by__isnull=True, email_address__iexact=getattr(user, 'email', ''))
        ).exists()
        if not exists:
            raise serializers.ValidationError("Connected account not found for the current user.")
        return value

    def create(self, validated_data):
        connected_account_id = validated_data.pop('connected_account_id', None)
        steps_payload = self._extract_steps_payload()

        if steps_payload is not None:
            validated_data['settings'] = self._with_steps_in_settings(
                validated_data.get('settings'),
                steps_payload,
            )

        campaign = Campaign.objects.create(**validated_data)

        if connected_account_id is not None:
            campaign.connected_account_id = connected_account_id
            campaign.save(update_fields=['connected_account'])

        if steps_payload is not None:
            self._sync_sequence_steps(campaign, steps_payload)

        return campaign

    def update(self, instance, validated_data):
        steps_payload = self._extract_steps_payload()
        has_connected_account = 'connected_account_id' in self.initial_data
        connected_account_id = validated_data.pop('connected_account_id', None)

        if steps_payload is not None:
            validated_data['settings'] = self._with_steps_in_settings(
                validated_data.get('settings', instance.settings),
                steps_payload,
            )

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        if has_connected_account:
            instance.connected_account_id = connected_account_id

        instance.save()

        if steps_payload is not None:
            self._sync_sequence_steps(instance, steps_payload)

        return instance

    def _extract_steps_payload(self):
        steps = self.initial_data.get('steps')
        if isinstance(steps, list):
            return steps

        settings = self.initial_data.get('settings')
        if isinstance(settings, dict):
            nested_steps = settings.get('steps')
            if isinstance(nested_steps, list):
                return nested_steps

        return None

    def _with_steps_in_settings(self, settings, steps_payload):
        value = settings.copy() if isinstance(settings, dict) else {}
        value['steps'] = steps_payload
        return value

    def _sync_sequence_steps(self, campaign, raw_steps):
        """
        Synchronise SequenceStep rows for a campaign using an upsert-by-step-order
        strategy instead of a blind delete + bulk_create.

        Why this matters
        ----------------
        ``SequenceStep`` rows are referenced by ``CampaignLead.current_step``
        (FK with ``on_delete=SET_NULL``).  The old implementation deleted every
        step unconditionally before re-creating them, which silently set
        ``current_step`` to NULL for every active lead.  On the next scheduler
        run those leads were detected as having no step and were reset back to
        step 1 — causing duplicate outreach.

        New strategy
        ------------
        1. Load existing steps keyed by ``step_order``.
        2. For each incoming step, update the existing row (same PK → no FK
           breakage) or create a new one.
        3. Delete only the steps whose ``step_order`` no longer appears in the
           new payload.
        4. Remap any ``CampaignLead`` whose ``current_step`` was just deleted to
           the nearest surviving step at or below its old order so active leads
           keep their approximate position in the sequence.
        """
        # ── 1. Index existing steps by step_order ──────────────────────────
        existing_by_order = {
            s.step_order: s
            for s in SequenceStep.objects.filter(campaign=campaign)
        }

        new_orders = set()
        steps_to_update = []
        steps_to_create = []

        for index, raw_step in enumerate(raw_steps):
            order = index + 1
            new_orders.add(order)
            normalized = self._normalize_step(raw_step, index)

            if order in existing_by_order:
                # Update in-place — preserves the PK so FK refs stay valid.
                existing = existing_by_order[order]
                existing.channel_type = normalized['channel_type']
                existing.delay_minutes = normalized['delay_minutes']
                existing.template_subject = normalized['template_subject']
                existing.template_body = normalized['template_body']
                steps_to_update.append(existing)
            else:
                steps_to_create.append(
                    SequenceStep(
                        organization=campaign.organization,
                        campaign=campaign,
                        step_order=order,
                        channel_type=normalized['channel_type'],
                        delay_minutes=normalized['delay_minutes'],
                        template_subject=normalized['template_subject'],
                        template_body=normalized['template_body'],
                    )
                )

        # ── 2. Persist updates and new rows ────────────────────────────────
        if steps_to_update:
            SequenceStep.objects.bulk_update(
                steps_to_update,
                ['channel_type', 'delay_minutes', 'template_subject', 'template_body'],
            )

        if steps_to_create:
            SequenceStep.objects.bulk_create(steps_to_create)

        # ── 3. Identify and delete obsolete steps ──────────────────────────
        obsolete_orders = set(existing_by_order.keys()) - new_orders
        if not obsolete_orders:
            return  # Nothing was removed — no FK repair needed.

        obsolete_steps = [existing_by_order[o] for o in obsolete_orders]
        obsolete_ids = [s.id for s in obsolete_steps]

        # ── 4. Remap active leads pointing at an about-to-be-deleted step ──
        # Fetch the surviving step IDs ordered so we can find the nearest one.
        surviving_steps = list(
            SequenceStep.objects.filter(campaign=campaign)
            .exclude(id__in=obsolete_ids)
            .order_by('step_order')
        )

        affected_leads = CampaignLead.objects.filter(
            campaign=campaign,
            current_step_id__in=obsolete_ids,
        ).select_related('current_step')

        leads_to_update = []
        for clead in affected_leads:
            old_order = clead.current_step.step_order if clead.current_step else 0
            # Find the closest surviving step at or below the lead's old position.
            replacement = None
            for step in reversed(surviving_steps):
                if step.step_order <= old_order:
                    replacement = step
                    break
            # If nothing is at or below, fall back to the first surviving step.
            if replacement is None and surviving_steps:
                replacement = surviving_steps[0]
            clead.current_step = replacement
            leads_to_update.append(clead)

        if leads_to_update:
            CampaignLead.objects.bulk_update(leads_to_update, ['current_step'])

        # ── 5. Now it's safe to delete the obsolete steps ──────────────────
        SequenceStep.objects.filter(id__in=obsolete_ids).delete()

    def _normalize_step(self, raw_step, index):
        if not isinstance(raw_step, dict):
            raw_step = {}

        channel_type = (raw_step.get('channel_type') or raw_step.get('type') or 'EMAIL').upper()
        valid_channels = dict(SequenceStep.CHANNEL_CHOICES)
        if channel_type not in valid_channels:
            channel_type = 'MANUAL'

        delay_minutes = self._extract_delay_minutes(raw_step, channel_type)

        template_subject = (
            raw_step.get('template_subject')
            or raw_step.get('subject')
            or ''
        )
        template_body = (
            raw_step.get('template_body')
            or raw_step.get('body')
            or raw_step.get('description')
            or ''
        )

        return {
            'step_order': index + 1,
            'channel_type': channel_type,
            'delay_minutes': delay_minutes,
            'template_subject': template_subject,
            'template_body': template_body,
        }

    def _extract_delay_minutes(self, raw_step, channel_type):
        delay_minutes = self._coerce_int(raw_step.get('delay_minutes'))
        if delay_minutes is not None:
            return max(delay_minutes, 0)

        if channel_type.startswith('CONDITION_'):
            condition_time = str(raw_step.get('condition_time') or '').strip().lower()
            return CONDITION_TIME_TO_MINUTES.get(condition_time, CONDITION_TIME_TO_MINUTES['1 day'])

        delay_value = self._coerce_int(raw_step.get('delay_value'))
        delay_unit = (raw_step.get('delay_unit') or 'minutes').lower()
        multiplier = DELAY_UNIT_TO_MINUTES.get(delay_unit, 1)

        if delay_value is not None:
            return max(delay_value, 0) * multiplier

        if channel_type == 'WAIT':
            return DELAY_UNIT_TO_MINUTES['days']

        return 0

    def _coerce_int(self, value):
        try:
            if value is None or value == '':
                return None
            return int(value)
        except (TypeError, ValueError):
            return None


class EmailTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmailTemplate
        fields = ['id', 'name', 'subject', 'body', 'category', 'usage_count', 'created_at']

class CampaignLeadSerializer(serializers.ModelSerializer):
    class Meta:
        model = CampaignLead
        fields = '__all__'
