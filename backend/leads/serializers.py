from rest_framework import serializers
from django.core.exceptions import ValidationError as DjangoValidationError

from .models import BlockedDomain, Lead, Tag, LeadTag, validate_domain

class TagSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tag
        fields = ['id', 'name']

class LeadSerializer(serializers.ModelSerializer):
    tags = serializers.SerializerMethodField()

    class Meta:
        model = Lead
        fields = ['id', 'email', 'first_name', 'last_name', 'company', 'phone', 'linkedin_url', 'custom_data', 'custom_variables', 'global_unsubscribe', 'score', 'tags', 'created_at']
        read_only_fields = ['organization', 'score']

    def get_tags(self, obj):
        tags = Tag.objects.filter(tagged_leads__lead=obj)
        return TagSerializer(tags, many=True).data

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
