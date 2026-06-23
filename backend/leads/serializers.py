from rest_framework import serializers
from .models import Lead, Tag, LeadTag
from .models import LeadScrapeJob

class TagSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tag
        fields = ['id', 'name']

class LeadSerializer(serializers.ModelSerializer):
    tags = serializers.SerializerMethodField()

    class Meta:
        model = Lead
        fields = ['id', 'email', 'first_name', 'last_name', 'company', 'phone', 'linkedin_url', 'custom_data', 'global_unsubscribe', 'score', 'tags', 'created_at']
        read_only_fields = ['organization', 'score']

    def get_tags(self, obj):
        tags = Tag.objects.filter(tagged_leads__lead=obj)
        return TagSerializer(tags, many=True).data

class LeadScrapeJobSerializer(serializers.ModelSerializer):
    class Meta:
        model = LeadScrapeJob
        fields = ['id', 'query', 'limit', 'status', 'leads_found', 'error_message', 'started_at', 'completed_at', 'created_at']
        read_only_fields = ['organization', 'id', 'status', 'leads_found', 'error_message', 'started_at', 'completed_at', 'created_at']