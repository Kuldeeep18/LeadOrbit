import uuid
from django.db import models
from tenants.middleware import get_current_tenant

class Organization(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    billing_plan = models.CharField(max_length=50, default='FREE')
    created_at = models.DateTimeField(auto_now_add=True)
    gemini_api_key = models.CharField(max_length=255, blank=True, null=True)
    enable_ai_personalization = models.BooleanField(default=True)

    def __str__(self):
        return self.name

class TenantManager(models.Manager):
    def get_queryset(self):
        tenant = get_current_tenant()
        if tenant:
            return super().get_queryset().filter(organization=tenant)
        # If no tenant context is set (e.g. CLI operations without threading), return all
        return super().get_queryset()

class TenantModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = TenantManager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self.organization_id:
            tenant = get_current_tenant()
            if tenant:
                self.organization = tenant
            else:
                raise ValueError("TenantModel must be saved within a tenant context (or organization must be explicitly set).")
        super().save(*args, **kwargs)
