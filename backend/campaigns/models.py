from django.db import models
from django.conf import settings
from tenants.models import TenantModel
from leads.models import Lead
import uuid

class ConnectedEmailAccount(TenantModel):
    PROVIDER_CHOICES = (
        ('GOOGLE', 'Google'),
        ('MICROSOFT', 'Microsoft')
    )
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email_address = models.EmailField()
    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES, default='GOOGLE')
    connected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='connected_email_accounts',
    )
    access_token = models.TextField()
    refresh_token = models.TextField(blank=True, null=True)
    token_expiry = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.email_address} ({self.get_provider_display()})"

class Campaign(TenantModel):
    STATUS_CHOICES = (
        ('DRAFT', 'Draft'),
        ('ACTIVE', 'Active'),
        ('PAUSED', 'Paused'),
        ('COMPLETED', 'Completed')
    )
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DRAFT')
    settings = models.JSONField(default=dict, blank=True)
    connected_account = models.ForeignKey(ConnectedEmailAccount, on_delete=models.SET_NULL, null=True, blank=True, related_name='campaigns')

    def __str__(self):
        return self.name

class SequenceStep(TenantModel):
    CHANNEL_CHOICES = (
        ('EMAIL', 'Email'),
        ('SMS', 'SMS'),
        ('WHATSAPP', 'WhatsApp'),
        ('LINKEDIN', 'LinkedIn'),
        ('WAIT', 'Wait'),
        ('MANUAL', 'Manual Task'),
        ('CONDITION_OPEN', 'Condition: Opened Email'),
        ('CONDITION_REPLY', 'Condition: Replied'),
        ('CONDITION_CLICK', 'Condition: Clicked Link'),
    )
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name='steps')
    step_order = models.IntegerField()
    channel_type = models.CharField(max_length=20, choices=CHANNEL_CHOICES)
    delay_minutes = models.IntegerField(default=0)
    template_subject = models.TextField(blank=True, null=True)
    template_body = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['step_order']

    def __str__(self):
        return f"{self.campaign.name} - Step {self.step_order} ({self.channel_type})"

class CampaignLead(TenantModel):
    STATUS_CHOICES = (
        ('ENROLLED', 'Enrolled'),
        ('ACTIVE', 'Active'),
        ('PAUSED', 'Paused'),
        ('REPLIED', 'Replied'),
        ('BOUNCED', 'Bounced'),
        ('FINISHED', 'Finished')
    )
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name='enrolled_leads')
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name='campaigns')
    current_step = models.ForeignKey(SequenceStep, on_delete=models.SET_NULL, null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ENROLLED')
    next_execution_time = models.DateTimeField(null=True, blank=True)
    last_sent_message_id = models.CharField(max_length=255, null=True, blank=True)
    last_opened_at = models.DateTimeField(null=True, blank=True)
    last_clicked_at = models.DateTimeField(null=True, blank=True)
    last_replied_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ('campaign', 'lead')
        indexes = [
            models.Index(fields=['status', 'next_execution_time']),
        ]

    def __str__(self):
        return f"{self.lead.email} in {self.campaign.name}"
