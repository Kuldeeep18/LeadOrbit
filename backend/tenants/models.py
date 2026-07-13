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
    custom_tracking_domain = models.CharField(max_length=255, blank=True, null=True, unique=True)

    def clean(self):
        super().clean()
        if self.custom_tracking_domain:
            self.custom_tracking_domain = self.custom_tracking_domain.lower().strip()
            
            from django.conf import settings
            from django.core.exceptions import ValidationError
            import dns.resolver
            from urllib.parse import urlparse

            from tenants.utils import is_local_tracking_domain

            if is_local_tracking_domain(self.custom_tracking_domain):
                return

            try:
                base_url = getattr(settings, 'BACKEND_BASE_URL', 'https://leadorbit.onrender.com')
                parsed = urlparse(base_url)
                target_domain = parsed.hostname or 'leadorbit.onrender.com'

                resolver = dns.resolver.Resolver()
                resolver.timeout = 2.0
                resolver.lifetime = 5.0
                answers = resolver.resolve(self.custom_tracking_domain, 'CNAME')
                
                valid = False
                for rdata in answers:
                    target = rdata.target.to_text().rstrip('.').lower()
                    if target == target_domain.lower():
                        valid = True
                        break
                        
                if not valid:
                    raise ValidationError({'custom_tracking_domain': f'CNAME record must point to {target_domain}'})
            except dns.resolver.NXDOMAIN as e:
                raise ValidationError({'custom_tracking_domain': 'Domain does not exist.'}) from e
            except dns.resolver.NoAnswer as e:
                raise ValidationError({'custom_tracking_domain': 'No CNAME record found for this domain.'}) from e
            except dns.resolver.Timeout as e:
                raise ValidationError({'custom_tracking_domain': 'DNS query timed out.'}) from e
            except ValidationError:
                raise
            except Exception as e:
                raise ValidationError({'custom_tracking_domain': f'DNS validation failed: {e}'}) from e

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
