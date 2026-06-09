from django.db import models
from tenants.models import TenantModel
import uuid

class Lead(TenantModel):
    SCORE_SENT = 1
    SCORE_OPENED = 5
    SCORE_CLICKED = 10
    SCORE_REPLIED = 25
    SCORE_BOUNCED = -10

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

    def recalculate_score(self, save=True):
        from campaigns.models import CampaignLead

        score = 0
        campaign_leads = CampaignLead.objects.filter(lead=self)

        for campaign_lead in campaign_leads:
            if campaign_lead.last_sent_message_id:
                score += self.SCORE_SENT
            if campaign_lead.last_opened_at:
                score += self.SCORE_OPENED
            if campaign_lead.last_clicked_at:
                score += self.SCORE_CLICKED
            if campaign_lead.last_replied_at or campaign_lead.status == 'REPLIED':
                score += self.SCORE_REPLIED
            if campaign_lead.status == 'BOUNCED':
                score += self.SCORE_BOUNCED

        self.score = score
        if save:
            self.save(update_fields=['score'])
        return score


def update_lead_score(lead):
    return lead.recalculate_score()

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
