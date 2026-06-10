from rest_framework import serializers
from .models import Lead, Tag, LeadTag

class TagSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tag
        fields = ['id', 'name']

class LeadSerializer(serializers.ModelSerializer):
    tags = serializers.SerializerMethodField()

    class Meta:
        model = Lead
        fields = [
            'id',
            'email',
            'first_name',
            'last_name',
            'company',
            'phone',
            'linkedin_url',
            'custom_data',
            'global_unsubscribe',
            'score',
            'crm_source',
            'crm_external_id',
            'crm_synced_at',
            'tags',
            'created_at',
        ]
        read_only_fields = ['organization', 'score', 'crm_source', 'crm_external_id', 'crm_synced_at']

    def get_tags(self, obj):
        tags = Tag.objects.filter(tagged_leads__lead=obj)
        return TagSerializer(tags, many=True).data


class LeadCRMRecordSerializer(serializers.Serializer):
    email = serializers.EmailField()
    external_id = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    first_name = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    last_name = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    company = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    phone = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    linkedin_url = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    custom_data = serializers.DictField(required=False, allow_null=True)
    global_unsubscribe = serializers.BooleanField(required=False)
