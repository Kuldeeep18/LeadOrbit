from django.db import models
from tenants.models import TenantModel
import uuid

class Lead(TenantModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField()
    first_name = models.CharField(max_length=100, blank=True, null=True)
    last_name = models.CharField(max_length=100, blank=True, null=True)
    company = models.CharField(max_length=255, blank=True, null=True)
    phone = models.CharField(max_length=50, blank=True, null=True)
    linkedin_url = models.URLField(max_length=255, blank=True, null=True)
    custom_data = models.JSONField(default=dict, blank=True)
    global_unsubscribe = models.BooleanField(default=False)
    score = models.IntegerField(default=0)

    class Meta:
        unique_together = ('organization', 'email')

    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.email})"

class LeadImportJob(TenantModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    filename = models.CharField(max_length=255)
    total_rows = models.IntegerField(default=0)
    imported_count = models.IntegerField(default=0)
    failed_count = models.IntegerField(default=0)
    error_log = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.filename} ({self.created_at:%Y-%m-%d %H:%M})"

class Tag(TenantModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=50)

    class Meta:
        unique_together = ('organization', 'name')

    def __str__(self):
        return self.name

class LeadTag(TenantModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name='lead_tags')
    tag = models.ForeignKey(Tag, on_delete=models.CASCADE, related_name='tagged_leads')

    class Meta:
        unique_together = ('lead', 'tag')
