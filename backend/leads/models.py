from django.db import models
from tenants.models import TenantModel
import uuid
from .fields import EncryptedJSONField, EncryptedTextField

class Lead(TenantModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField()
    first_name = EncryptedTextField(blank=True, null=True)
    last_name = EncryptedTextField(blank=True, null=True)
    company = EncryptedTextField(blank=True, null=True)
    phone = EncryptedTextField(blank=True, null=True)
    linkedin_url = EncryptedTextField(blank=True, null=True)
    custom_data = EncryptedJSONField(default=dict, blank=True)
    global_unsubscribe = models.BooleanField(default=False)
    score = models.IntegerField(default=0)
    crm_source = models.CharField(max_length=80, blank=True, null=True)
    crm_external_id = models.CharField(max_length=255, blank=True, null=True)
    crm_synced_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        unique_together = ('organization', 'email')

    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.email})"

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
