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
        fields = ['id', 'email', 'first_name', 'last_name', 'company', 'phone', 'linkedin_url', 'custom_data', 'global_unsubscribe', 'score', 'tags', 'created_at']
        read_only_fields = ['organization', 'score']

    def get_tags(self, obj):
        tags = Tag.objects.filter(tagged_leads__lead=obj)
        return TagSerializer(tags, many=True).data
