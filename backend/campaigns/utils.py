
import re

# Mapping from common merge tags to Lead model fields
MERGE_TAG_FIELD_MAP = {
    'firstName': 'first_name',
    'lastName': 'last_name',
    'company': 'company',
    'email': 'email',
    'jobTitle': 'job_title',
    'phone': 'phone',
    # add more as needed
}

def extract_merge_tags(text):
    """Return a list of tag names inside {{ }} in text (e.g., ['firstName', 'company'])."""
    return re.findall(r'\{\{\s*(\w+)\s*\}\}', text)

def get_all_step_merge_tags(campaign):
    """Return set of all merge tag field names used in a campaign's steps."""
    tags = set()
    for step in campaign.sequence_steps.all():
        tags.update(extract_merge_tags(step.template_subject or ''))
        tags.update(extract_merge_tags(step.template_body or ''))
    return tags
