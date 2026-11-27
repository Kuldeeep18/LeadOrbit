from django.db import models
from django.core.exceptions import ValidationError
from tenants.models import TenantModel
import uuid
import re
import unicodedata

DOMAIN_PATTERN = re.compile(r'^(?!-)[a-z0-9-]+(?:\.[a-z0-9-]+)+$')


def normalize_domain(value):
    domain = (value or '').strip().lower()
    domain = re.sub(r'^https?://', '', domain)
    if '@' in domain:
        domain = domain.rsplit('@', 1)[-1]
    domain = domain.split('/', 1)[0].split(':', 1)[0].strip('.')
    return domain


def validate_domain(value):
    domain = normalize_domain(value)
    if not domain or not DOMAIN_PATTERN.match(domain):
        raise ValidationError('Enter a valid domain, for example competitor.com.')
    return domain

def _continues_name_part(char):
    """Letters, digits and combining marks (Unicode category M*, e.g. the accent in
    a decomposed "josé") belong to the current name part; anything else, such as
    whitespace or punctuation, starts a new one. U+02BC is a letter (Lm) to Unicode
    but is used as an apostrophe in names, so it is treated as a separator."""
    if char == 'ʼ':
        return False
    return char.isalnum() or unicodedata.category(char).startswith('M')


def _upper_same_length(char):
    """Uppercase ``char`` only if that keeps it one character long.

    Some characters expand when uppercased ("ß" -> "SS", "ŉ" -> "ʼN"). Keeping those
    as typed means capitalization never changes a name's length, so a name that fit
    the column's max_length before saving still fits after.
    """
    upper = char.upper()
    return upper if len(upper) == 1 else char


def capitalize_name(value):
    """Capitalize each part of a name: "mary-jane o'neil" -> "Mary-Jane O'Neil".

    The result always has the same length as ``value``.
    """
    result = []
    at_part_start = True
    for char in value:
        if _continues_name_part(char):
            result.append(_upper_same_length(char) if at_part_start else char)
            at_part_start = False
        else:
            result.append(char)
            at_part_start = True
    return ''.join(result)


class Lead(TenantModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField()
    first_name = models.CharField(max_length=100, blank=True, null=True)
    last_name = models.CharField(max_length=100, blank=True, null=True)
    company = models.CharField(max_length=255, blank=True, null=True)
    phone = models.CharField(max_length=50, blank=True, null=True)
    linkedin_url = models.URLField(max_length=255, blank=True, null=True)
    custom_data = models.JSONField(default=dict, blank=True)
    custom_variables = models.JSONField(default=dict, blank=True)
    global_unsubscribe = models.BooleanField(default=False)
    score = models.IntegerField(default=0)

    class Meta:
        unique_together = ('organization', 'email')

    def _trim_string_fields(self):
        """Remove leading and trailing whitespace from lead string fields."""
        string_fields = [
            'email',
            'first_name',
            'last_name',
            'company',
            'phone',
            'linkedin_url',
        ]

        for field in string_fields:
            value = getattr(self, field)
            if isinstance(value, str):
                setattr(self, field, value.strip())

    def _capitalize_names(self):
        """Capitalize all-lowercase first/last names so merge tags read "Hi John".

        Names that already contain capitals (e.g. "McDonald", "DeShawn") are left
        alone, since their casing was chosen on purpose.
        """
        for field in ('first_name', 'last_name'):
            value = getattr(self, field)
            if isinstance(value, str) and value and value == value.lower():
                setattr(self, field, capitalize_name(value))

    def clean(self):
        self._trim_string_fields()
        self._capitalize_names()
        super().clean()

    def save(self, *args, **kwargs):
        self._trim_string_fields()
        self._capitalize_names()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.email})"

    def save(self, *args, **kwargs):
        if self.first_name:
            self.first_name = self.first_name.strip().title()
        if self.last_name:
            self.last_name = self.last_name.strip().title()
        super().save(*args, **kwargs)

class LeadImportJob(TenantModel):
    filename = models.CharField(max_length=255)
    total_rows = models.IntegerField(default=0)
    imported_count = models.IntegerField(default=0)
    failed_count = models.IntegerField(default=0)
    error_log = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.filename} ({self.imported_count}/{self.total_rows})"

class Tag(TenantModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=50)
    color = models.CharField(
        max_length=7,
        default='#6366f1',
        help_text='Hex color code for the tag badge, e.g. #6366f1',
    )

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

class BlockedDomain(TenantModel):
    domain = models.CharField(max_length=255)

    class Meta:
        unique_together = ('organization', 'domain')
        ordering = ['domain']

    def clean(self):
        self.domain = validate_domain(self.domain)

    def save(self, *args, **kwargs):
        self.domain = validate_domain(self.domain)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.domain
