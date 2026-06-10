import logging

from rest_framework import viewsets, parsers, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Lead, Tag
from .serializers import LeadCRMRecordSerializer, LeadSerializer, TagSerializer
from .sync import sync_lead_records

logger = logging.getLogger(__name__)

class LeadViewSet(viewsets.ModelViewSet):
    serializer_class = LeadSerializer
    queryset = Lead.objects.all()

    def get_queryset(self):
        # Do not rely only on thread-local tenant middleware for JWT requests.
        return Lead.objects.filter(organization=self.request.user.organization)

    def perform_create(self, serializer):
        lead = serializer.save(organization=self.request.user.organization)
        try:
            from campaigns.tasks import auto_enroll_lead_into_active_campaigns

            auto_enroll_lead_into_active_campaigns(lead)
        except Exception as exc:
            # Lead creation should still succeed even if campaign automation is unavailable.
            logger.warning(f"Auto-enroll skipped for lead {lead.email}: {exc}")

    @action(detail=False, methods=['delete'], url_path='delete-all')
    def delete_all(self, request):
        deleted_count, _ = self.get_queryset().delete()
        return Response(
            {"message": f"Successfully deleted {deleted_count} leads."},
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=['post'], parser_classes=[parsers.MultiPartParser])
    def import_csv(self, request):
        file_obj = request.FILES.get('file')
        if not file_obj:
            return Response({"error": "No file provided"}, status=status.HTTP_400_BAD_REQUEST)

        # Trigger async celery task
        from .tasks import import_leads_from_csv

        file_contents = file_obj.read().decode('utf-8')

        # Ensure we pass the organization to the task
        import_leads_from_csv.delay(file_contents, request.user.organization.id)

        return Response(
            {"message": "File received. Processing in background.", "filename": file_obj.name},
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=False, methods=['post'], url_path='sync-crm')
    def sync_crm(self, request):
        source = str(
            request.data.get('source')
            or request.data.get('crm_source')
            or request.data.get('source_system')
            or 'crm-api'
        ).strip() or 'crm-api'
        raw_records = request.data.get('records', [])

        if not isinstance(raw_records, list) or not raw_records:
            return Response(
                {"error": "records must be a non-empty list"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        records = []
        errors = []
        for index, raw_record in enumerate(raw_records):
            serializer = LeadCRMRecordSerializer(data=raw_record)
            if not serializer.is_valid():
                errors.append({
                    'index': index,
                    'reason': serializer.errors,
                })
                continue
            records.append(serializer.validated_data)

        if not records:
            return Response(
                {"error": "No valid CRM records to sync", "errors": errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        summary = sync_lead_records(request.user.organization, records, source=source)
        summary['errors'] = errors + summary['errors']

        try:
            from campaigns.tasks import auto_enroll_lead_into_active_campaigns

            for lead in summary['leads']:
                auto_enroll_lead_into_active_campaigns(lead)
        except Exception as exc:
            logger.warning("Auto-enroll skipped after CRM sync for org %s: %s", request.user.organization_id, exc)

        response = {
            "message": "CRM records synced successfully.",
            "source": source,
            "created": summary['created'],
            "updated": summary['updated'],
            "skipped": summary['skipped'] + len(errors),
            "errors": summary['errors'],
            "synced": len(summary['leads']),
        }
        return Response(response, status=status.HTTP_200_OK)

class TagViewSet(viewsets.ModelViewSet):
    serializer_class = TagSerializer
    queryset = Tag.objects.all()

    def get_queryset(self):
        return Tag.objects.filter(organization=self.request.user.organization)

    def perform_create(self, serializer):
        serializer.save(organization=self.request.user.organization)
