from django.db.models import Q
from rest_framework import viewsets, parsers, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.decorators import action
from rest_framework.response import Response
from users.permissions import IsOrgManager
from .models import BlockedDomain, Lead, LeadImportJob, Tag, LeadTag, LeadScrapeJob
from .serializers import BlockedDomainSerializer, LeadImportJobSerializer, LeadSerializer, TagSerializer, LeadScrapeJobSerializer

from django.utils import timezone
from datetime import timedelta

class LeadImportJobPagination(PageNumberPagination):
    page_size = 10


class LeadViewSet(viewsets.ModelViewSet):
    serializer_class = LeadSerializer
    queryset = Lead.objects.all()
    manager_actions = frozenset({
        'create',
        'update',
        'partial_update',
        'destroy',
        'delete_all',
        'import_csv',
        'assign_tags',
        'scrape_leads',
        'scrape_status',
        'scrape_history',
    })

    def get_permissions(self):
        permissions = super().get_permissions()
        if self.action in self.manager_actions:
            permissions.append(IsOrgManager())
        return permissions

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
    
    @action(detail=False, methods=['post'], url_path='scrape')
    def scrape_leads(self, request):
        org = request.user.organization
        query = request.data.get('query', '').strip()
        limit = request.data.get('limit', 50)

        if not query:
            return Response({"error": "Search query is required."}, status=status.HTTP_400_BAD_REQUEST)

        # Ensure limit is an integer and within the 1 to 200 safety bound
        try:
            limit = int(limit)
            if limit < 1 or limit > 200:
                return Response({"error": "Limit must be between 1 and 200."}, status=status.HTTP_400_BAD_REQUEST)
        except (ValueError, TypeError):
            return Response({"error": "Limit must be a valid number."}, status=status.HTTP_400_BAD_REQUEST)

        # Safety Check 1: Limit to 1 concurrent scrape job per organization
        if LeadScrapeJob.objects.filter(organization=org, status__in=['PENDING', 'RUNNING']).exists():
            return Response({
                "error": "Your organization already has an active lead scraping job running."
            }, status=status.HTTP_400_BAD_REQUEST)

        # Safety Check 2: Cooldown period of 5 minutes between completed scrape jobs
        five_minutes_ago = timezone.now() - timedelta(minutes=5)
        recent_job = LeadScrapeJob.objects.filter(
            organization=org, 
            status='COMPLETED', 
            completed_at__gte=five_minutes_ago
        ).exists()
        
        if recent_job:
            return Response({
                "error": "Please wait 5 minutes between lead generation requests."
            }, status=status.HTTP_400_BAD_REQUEST)

        # Create the tracking job model cleanly
        job = LeadScrapeJob.objects.create(
            organization=org,
            query=query,
            limit=limit,
            status='PENDING'
        )

        # Delay import to avoid circular dependency issues at runtime
        from .tasks import scrape_leads_task
        scrape_leads_task.delay(job.id, query, limit, org.id)

        return Response({
            "message": "AI Lead Generation background agent launched successfully.",
            "job_id": str(job.id)
        }, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['get'], url_path='scrape/(?P<job_id>[^/.]+)/status')
    def scrape_status(self, request, job_id=None):
        try:
            job = LeadScrapeJob.objects.get(organization=request.user.organization, id=job_id)
            serializer = LeadScrapeJobSerializer(job)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except LeadScrapeJob.DoesNotExist:
            return Response({"error": "Scrape job not found."}, status=status.HTTP_404_NOT_FOUND)

    @action(detail=False, methods=['get'], url_path='scrape_history')
    def scrape_history(self, request):
        jobs = LeadScrapeJob.objects.filter(organization=request.user.organization).order_by('-created_at')
        serializer = LeadScrapeJobSerializer(jobs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

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
    manager_actions = frozenset({'create', 'update', 'partial_update', 'destroy'})

    def get_permissions(self):
        permissions = super().get_permissions()
        if self.action in self.manager_actions:
            permissions.append(IsOrgManager())
        return permissions

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
