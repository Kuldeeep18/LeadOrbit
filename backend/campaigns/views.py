
import re
from django.http import JsonResponse
from .models import Campaign, SequenceStep, CampaignLead, Lead
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def validate_campaign_launch(request, campaign_id):
    try:
        campaign = Campaign.objects.get(id=campaign_id, organization=request.user.organization)
    except Campaign.DoesNotExist:
        return JsonResponse({"error": "Campaign not found"}, status=404)

    sequence_steps = SequenceStep.objects.filter(campaign=campaign)
    
    merge_tags = set()
    for step in sequence_steps:
        if step.template_body:
            tags = re.findall(r"\{\{(\w+)\}\}", step.template_body)
            merge_tags.update(tags)
        if step.template_subject:
            tags = re.findall(r"\{\{(\w+)\}\}", step.template_subject)
            merge_tags.update(tags)

    if not merge_tags:
        return JsonResponse({"valid": True, "message": "No merge tags to validate."})

    enrolled_leads = CampaignLead.objects.filter(campaign=campaign).select_related('lead')
    
    leads_with_missing_fields = []
    for campaign_lead in enrolled_leads:
        lead = campaign_lead.lead
        missing_fields = []
        for tag in merge_tags:
            if hasattr(lead, tag) and not getattr(lead, tag):
                missing_fields.append(tag)
            elif 'custom_data' in merge_tags and tag in lead.custom_data and not lead.custom_data.get(tag):
                missing_fields.append(tag)
            elif 'custom_variables' in merge_tags and tag in lead.custom_variables and not lead.custom_variables.get(tag):
                missing_fields.append(tag)

        if missing_fields:
            leads_with_missing_fields.append({
                "lead_id": str(lead.id),
                "email": lead.email,
                "missing_fields": missing_fields
            })

    if leads_with_missing_fields:
        return JsonResponse({
            "valid": False,
            "message": f"Found {len(leads_with_missing_fields)} leads with missing merge tag values.",
            "leads_with_missing_fields": leads_with_missing_fields
        })

    return JsonResponse({"valid": True, "message": "All leads have the required merge tag values."})