from rest_framework import serializers
from django.db.models import Q
from django.db import transaction

from .models import (
    Campaign,
    CampaignLead,
    ConnectedEmailAccount,
    SequenceStep,
    EmailTemplate,
)

DELAY_UNIT_TO_MINUTES = {
    "minutes": 1,
    "hours": 60,
    "days": 1440,
}

CONDITION_TIME_TO_MINUTES = {
    "1 day": 1440,
    "2 days": 2880,
    "3 days": 4320,
    "1 week": 10080,
}


class SequenceStepSerializer(serializers.ModelSerializer):
    class Meta:
        model = SequenceStep
        fields = [
            "id",
            "step_order",
            "channel_type",
            "delay_minutes",
            "template_subject",
            "template_body",
        ]


class CampaignSerializer(serializers.ModelSerializer):
    steps = serializers.SerializerMethodField()
    enrolled_count = serializers.IntegerField(source="leads_count", read_only=True)
    enrolled_lead_ids = serializers.SerializerMethodField()
    connected_account = serializers.SerializerMethodField()
    connected_account_id = serializers.UUIDField(
        write_only=True, required=False, allow_null=True
    )

    class Meta:
        model = Campaign
        fields = [
            "id",
            "name",
            "status",
            "settings",
            "steps",
            "enrolled_count",
            "enrolled_lead_ids",
            "sent_count",
            "open_count",
            "reply_count",
            "clicked_count",
            "bounced_count",
            "created_at",
            "connected_account",
            "connected_account_id",
        ]

    def get_steps(self, obj):
        return SequenceStepSerializer(obj.steps.all(), many=True).data

    def get_enrolled_lead_ids(self, obj):
        return [
            str(lead_id)
            for lead_id in obj.enrolled_leads.values_list("lead_id", flat=True)
        ]

    def get_connected_account(self, obj):
        if not obj.connected_account:
            return None
        return {
            "id": str(obj.connected_account_id),
            "email": obj.connected_account.email_address,
            "provider": obj.connected_account.provider,
        }

    def validate_connected_account_id(self, value):
        if value is None:
            return None
        request = self.context.get("request")
        org = getattr(getattr(request, "user", None), "organization", None)
        user = getattr(request, "user", None)
        exists = (
            ConnectedEmailAccount.objects.filter(
                id=value,
                organization=org,
            )
            .filter(
                Q(connected_by=user)
                | Q(
                    connected_by__isnull=True,
                    email_address__iexact=getattr(user, "email", ""),
                )
            )
            .exists()
        )
        if not exists:
            raise serializers.ValidationError(
                "Connected account not found for the current user."
            )
        return value

    def create(self, validated_data):
        connected_account_id = validated_data.pop("connected_account_id", None)
        steps_payload = self._extract_steps_payload()

        if steps_payload is not None:
            validated_data["settings"] = self._with_steps_in_settings(
                validated_data.get("settings"),
                steps_payload,
            )

        campaign = Campaign.objects.create(**validated_data)

        if connected_account_id is not None:
            campaign.connected_account_id = connected_account_id
            campaign.save(update_fields=["connected_account"])

        if steps_payload is not None:
            self._sync_sequence_steps(campaign, steps_payload)

        return campaign

    def update(self, instance, validated_data):
        steps_payload = self._extract_steps_payload()
        has_connected_account = "connected_account_id" in self.initial_data
        connected_account_id = validated_data.pop("connected_account_id", None)

        if steps_payload is not None:
            validated_data["settings"] = self._with_steps_in_settings(
                validated_data.get("settings", instance.settings),
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
        steps = self.initial_data.get("steps")
        if isinstance(steps, list):
            return steps

        settings = self.initial_data.get("settings")
        if isinstance(settings, dict):
            nested_steps = settings.get("steps")
            if isinstance(nested_steps, list):
                return nested_steps

        return None

    def _with_steps_in_settings(self, settings, steps_payload):
        value = settings.copy() if isinstance(settings, dict) else {}
        value["steps"] = steps_payload
        return value

    def _sync_sequence_steps(self, campaign, raw_steps):
        """
        Synchronise SequenceStep rows for a campaign using stable-ID upserts.

        Strategy:
        1. Load existing steps keyed by stable `id`.
        2. Determine which existing IDs are absent from the incoming payload
           — these are `obsolete_ids` and must be remapped first.
        3. Remap any `CampaignLead.current_step` that references an obsolete
           ID to the nearest surviving step at or below the lead's old order
           (fallback: first surviving step).
        4. Update in-place any existing step that is referenced by an incoming
           `id`, create new rows for incoming items without `id`.
        5. Delete obsolete rows after remapping.
        """
        # Build maps of existing steps by id and record their old orders
        existing_steps = list(SequenceStep.objects.filter(campaign=campaign))
        existing_by_id = {str(s.id): s for s in existing_steps}
        existing_ids = set(existing_by_id.keys())

        # Normalize incoming steps and collect any provided stable ids
        normalized_steps = []  # tuples of (incoming_id_or_none, normalized_dict)
        incoming_ids = []
        for index, raw_step in enumerate(raw_steps):
            normalized = self._normalize_step(raw_step, index)
            incoming_id = None
            if isinstance(raw_step, dict) and raw_step.get("id"):
                incoming_id = str(raw_step.get("id"))
                incoming_ids.append(incoming_id)
            normalized_steps.append((incoming_id, normalized))

        incoming_id_set = set(incoming_ids)

        # Determine obsolete existing IDs (present before, not present in incoming payload)
        obsolete_ids = existing_ids - incoming_id_set

        # Apply remapping, updates/creates and deletions inside a single transaction
        with transaction.atomic():
            # Remap any CampaignLead.current_step that points to an obsolete step
            if obsolete_ids:
                # Map obsolete id -> old step_order
                obsolete_order = {
                    str(s.id): s.step_order
                    for s in existing_steps
                    if str(s.id) in obsolete_ids
                }

                # Determine surviving steps (those not obsolete) and sort by their old step_order
                surviving_steps = [
                    s for s in existing_steps if str(s.id) not in obsolete_ids
                ]
                if surviving_steps:
                    surviving_sorted = sorted(
                        surviving_steps, key=lambda s: s.step_order
                    )

                    leads_qs = CampaignLead.objects.filter(
                        campaign=campaign, current_step_id__in=obsolete_ids
                    )
                    leads_to_update = []
                    for lead in leads_qs.select_related("current_step"):
                        old_order = obsolete_order.get(str(lead.current_step_id), 1)
                        # Find nearest surviving step at or below old_order
                        candidate = None
                        for s in reversed(surviving_sorted):
                            if s.step_order <= old_order:
                                candidate = s
                                break
                        if candidate is None:
                            candidate = surviving_sorted[0]
                        lead.current_step = candidate
                        leads_to_update.append(lead)

                    if leads_to_update:
                        CampaignLead.objects.bulk_update(
                            leads_to_update, ["current_step"]
                        )
                else:
                    # No surviving steps: clear the current_step for affected leads
                    CampaignLead.objects.filter(
                        campaign=campaign, current_step_id__in=obsolete_ids
                    ).update(current_step=None)

            # Apply updates and creates
            to_create = []
            for incoming_id, normalized in normalized_steps:
                if incoming_id is None:
                    # create new step
                    to_create.append(
                        SequenceStep(
                            organization=campaign.organization,
                            campaign=campaign,
                            step_order=normalized["step_order"],
                            channel_type=normalized["channel_type"],
                            delay_minutes=normalized["delay_minutes"],
                            template_subject=normalized["template_subject"],
                            template_body=normalized["template_body"],
                        )
                    )
                else:
                    existing = existing_by_id.get(incoming_id)
                    if existing and existing.campaign_id == campaign.id:
                        # update in-place preserving PK
                        existing.step_order = normalized["step_order"]
                        existing.channel_type = normalized["channel_type"]
                        existing.delay_minutes = normalized["delay_minutes"]
                        existing.template_subject = normalized["template_subject"]
                        existing.template_body = normalized["template_body"]
                        existing.save()
                    else:
                        # incoming id not found or not owned by this campaign: create new
                        to_create.append(
                            SequenceStep(
                                organization=campaign.organization,
                                campaign=campaign,
                                step_order=normalized["step_order"],
                                channel_type=normalized["channel_type"],
                                delay_minutes=normalized["delay_minutes"],
                                template_subject=normalized["template_subject"],
                                template_body=normalized["template_body"],
                            )
                        )

            if to_create:
                SequenceStep.objects.bulk_create(to_create)

            # Now delete obsolete steps (they were remapped above)
            if obsolete_ids:
                SequenceStep.objects.filter(id__in=obsolete_ids).delete()

    def _normalize_step(self, raw_step, index):
        if not isinstance(raw_step, dict):
            raw_step = {}

        channel_type = (
            raw_step.get("channel_type") or raw_step.get("type") or "EMAIL"
        ).upper()
        valid_channels = dict(SequenceStep.CHANNEL_CHOICES)
        if channel_type not in valid_channels:
            channel_type = "MANUAL"

        delay_minutes = self._extract_delay_minutes(raw_step, channel_type)

        template_subject = (
            raw_step.get("template_subject") or raw_step.get("subject") or ""
        )
        template_body = (
            raw_step.get("template_body")
            or raw_step.get("body")
            or raw_step.get("description")
            or ""
        )

        return {
            "step_order": index + 1,
            "channel_type": channel_type,
            "delay_minutes": delay_minutes,
            "template_subject": template_subject,
            "template_body": template_body,
        }

    def _extract_delay_minutes(self, raw_step, channel_type):
        delay_minutes = self._coerce_int(raw_step.get("delay_minutes"))
        if delay_minutes is not None:
            return max(delay_minutes, 0)

        if channel_type.startswith("CONDITION_"):
            condition_time = str(raw_step.get("condition_time") or "").strip().lower()
            return CONDITION_TIME_TO_MINUTES.get(
                condition_time, CONDITION_TIME_TO_MINUTES["1 day"]
            )

        delay_value = self._coerce_int(raw_step.get("delay_value"))
        delay_unit = (raw_step.get("delay_unit") or "minutes").lower()
        multiplier = DELAY_UNIT_TO_MINUTES.get(delay_unit, 1)

        if delay_value is not None:
            return max(delay_value, 0) * multiplier

        if channel_type == "WAIT":
            return DELAY_UNIT_TO_MINUTES["days"]

        return 0

    def _coerce_int(self, value):
        try:
            if value is None or value == "":
                return None
            return int(value)
        except (TypeError, ValueError):
            return None


class EmailTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmailTemplate
        fields = [
            "id",
            "name",
            "subject",
            "body",
            "category",
            "usage_count",
            "created_at",
        ]


class CampaignLeadSerializer(serializers.ModelSerializer):
    class Meta:
        model = CampaignLead
        fields = "__all__"
