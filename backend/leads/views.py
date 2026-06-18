from django.db.models import Q
from rest_framework import viewsets, parsers, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import BlockedDomain, Lead, LeadImportJob, Tag, LeadTag
from .serializers import BlockedDomainSerializer, LeadImportJobSerializer, LeadSerializer, TagSerializer


class LeadImportJobPagination(PageNumberPagination):
    page_size = 10


class LeadViewSet(viewsets.ModelViewSet):
    serializer_class = LeadSerializer
    queryset = Lead.objects.all()

    def get_queryset(self):
        """
        Returns leads scoped to the current user's organization.

        Supported query parameters (Issue #244):
          ?tags=uuid1,uuid2         — leads that have ALL of the given tags
          ?created_after=YYYY-MM-DD — leads created on or after this date
          ?created_before=YYYY-MM-DD — leads created on or before this date
          ?status=active|unsubscribed — filter by subscription status
          ?search=<text>            — filter by name / email / company
        """
        qs = Lead.objects.filter(organization=self.request.user.organization)
        params = self.request.query_params

        # ── Tag filter ──────────────────────────────────────────────────────
        raw_tags = params.get('tags', '').strip()
        if raw_tags:
            tag_ids = [t.strip() for t in raw_tags.split(',') if t.strip()]
            for tag_id in tag_ids:
                qs = qs.filter(lead_tags__tag__id=tag_id)

        # ── Date range ──────────────────────────────────────────────────────
        created_after = params.get('created_after', '').strip()
        if created_after:
            qs = qs.filter(created_at__date__gte=created_after)

        created_before = params.get('created_before', '').strip()
        if created_before:
            qs = qs.filter(created_at__date__lte=created_before)

        # ── Status (pipeline stage) ──────────────────────────────────────────
        status_param = params.get('status', '').strip().lower()
        if status_param == 'active':
            qs = qs.filter(global_unsubscribe=False)
        elif status_param == 'unsubscribed':
            qs = qs.filter(global_unsubscribe=True)

        # ── Text search ──────────────────────────────────────────────────────
        search = params.get('search', '').strip()
        if search:
            qs = qs.filter(
                Q(first_name__icontains=search)
                | Q(last_name__icontains=search)
                | Q(email__icontains=search)
                | Q(company__icontains=search)
            )

        return qs.distinct()

    def perform_create(self, serializer):
        serializer.save(organization=self.request.user.organization)

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

        job = LeadImportJob.objects.create(
            organization=request.user.organization,
            filename=file_obj.name or 'lead-import.csv',
        )
        # Trigger async celery task
        from .tasks import import_leads_from_csv
        file_contents = file_obj.read().decode('utf-8')

        # Ensure we pass the organization to the task
        import_leads_from_csv.delay(file_contents, request.user.organization.id, str(job.id))

        return Response(
            {
                "message": "File received. Processing in background.",
                "filename": file_obj.name,
                "job_id": str(job.id),
            },
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=True, methods=['post'], url_path='tags')
    def assign_tags(self, request, pk=None):
        """
        POST /api/v1/leads/{id}/tags/
        Body: {"tag_ids": ["uuid1", "uuid2", ...]}

        Replaces the lead's full tag set with the provided UUIDs.
        Tags not belonging to the same organization are silently ignored.
        """
        lead = self.get_object()
        raw_ids = request.data.get('tag_ids', [])
        if not isinstance(raw_ids, list):
            return Response(
                {"error": "'tag_ids' must be a list of UUIDs."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        org = request.user.organization
        tags = Tag.objects.filter(id__in=raw_ids, organization=org)

        # Remove tags not in the new set
        LeadTag.objects.filter(lead=lead).exclude(tag__in=tags).delete()

        # Add tags not yet assigned
        existing_tag_ids = set(
            LeadTag.objects.filter(lead=lead).values_list('tag_id', flat=True)
        )
        for tag in tags:
            if tag.id not in existing_tag_ids:
                LeadTag.objects.create(lead=lead, tag=tag, organization=org)

        # Return the updated tag list
        updated_tags = Tag.objects.filter(tagged_leads__lead=lead)
        return Response(TagSerializer(updated_tags, many=True).data, status=status.HTTP_200_OK)


class LeadImportJobViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = LeadImportJobSerializer
    pagination_class = LeadImportJobPagination
    queryset = LeadImportJob.objects.all()

    def get_queryset(self):
        return LeadImportJob.objects.filter(organization=self.request.user.organization).order_by('-created_at')

class TagViewSet(viewsets.ModelViewSet):
    serializer_class = TagSerializer
    queryset = Tag.objects.all()

    def get_queryset(self):
        return Tag.objects.filter(organization=self.request.user.organization)

    def perform_create(self, serializer):
        serializer.save(organization=self.request.user.organization)


class BlockedDomainViewSet(viewsets.ModelViewSet):
    serializer_class = BlockedDomainSerializer
    queryset = BlockedDomain.objects.all()

    def get_queryset(self):
        return BlockedDomain.objects.filter(organization=self.request.user.organization)

    def perform_create(self, serializer):
        serializer.save(organization=self.request.user.organization)
