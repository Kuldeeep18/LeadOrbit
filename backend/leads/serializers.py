from rest_framework import serializers
from django.core.exceptions import ValidationError as DjangoValidationError

from .models import BlockedDomain, Lead, LeadImportJob, Tag, LeadTag, validate_domain


class TagSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tag
        fields = ['id', 'name', 'color']


class LeadSerializer(serializers.ModelSerializer):
    tags = serializers.SerializerMethodField()
    # Write-only field: accept a list of Tag UUIDs to set on the lead.
    tag_ids = serializers.ListField(
        child=serializers.UUIDField(),
        write_only=True,
        required=False,
        help_text='List of Tag UUIDs to assign to this lead (replaces existing tags).',
    )

    class Meta:
        model = Lead
        fields = [
            'id', 'email', 'first_name', 'last_name', 'company', 'phone',
            'linkedin_url', 'custom_data', 'custom_variables',
<<<<<<< HEAD
            'global_unsubscribe', 'score', 'tags', 'tag_ids', 'created_at',
=======
            'global_unsubscribe', 'score', 'pipeline_status', 'tags', 'tag_ids',
            'created_at', 'updated_at',
>>>>>>> d1274af ( Add Quick Filters for Lead Status)
        ]
        read_only_fields = ['organization', 'score']

    def get_tags(self, obj):
        tags = Tag.objects.filter(tagged_leads__lead=obj)
        return TagSerializer(tags, many=True).data

    def _set_tags(self, lead, tag_ids):
        """Replace the lead's tags with the given list of Tag UUIDs."""
        org = lead.organization
        tags = Tag.objects.filter(id__in=tag_ids, organization=org)
        # Remove tags not in the new set
        LeadTag.objects.filter(lead=lead).exclude(tag__in=tags).delete()
        # Add new tags that are not already assigned
        existing_tag_ids = set(
            LeadTag.objects.filter(lead=lead).values_list('tag_id', flat=True)
        )
        for tag in tags:
            if tag.id not in existing_tag_ids:
                LeadTag.objects.create(lead=lead, tag=tag, organization=org)

    def create(self, validated_data):
        tag_ids = validated_data.pop('tag_ids', None)
        lead = super().create(validated_data)
        if tag_ids is not None:
            self._set_tags(lead, tag_ids)
        return lead

    def update(self, instance, validated_data):
        tag_ids = validated_data.pop('tag_ids', None)
        lead = super().update(instance, validated_data)
        if tag_ids is not None:
            self._set_tags(lead, tag_ids)
        return lead


class LeadImportJobSerializer(serializers.ModelSerializer):
    class Meta:
        model = LeadImportJob
        fields = [
            'id',
            'filename',
            'total_rows',
            'imported_count',
            'failed_count',
            'error_log',
            'created_at',
        ]
        read_only_fields = fields

class BlockedDomainSerializer(serializers.ModelSerializer):
    class Meta:
        model = BlockedDomain
        fields = ['id', 'domain', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate_domain(self, value):
        try:
            return validate_domain(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages)

    def validate(self, attrs):
        request = self.context.get('request')
        organization = getattr(getattr(request, 'user', None), 'organization', None)
        domain = attrs.get('domain', getattr(self.instance, 'domain', None))

        if organization and domain:
            existing = BlockedDomain.objects.filter(
                organization=organization,
                domain=domain,
            )
            if self.instance:
                existing = existing.exclude(id=self.instance.id)
            if existing.exists():
                raise serializers.ValidationError({'domain': 'This domain is already blocked.'})

        return attrs
