from rest_framework import viewsets, parsers, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Lead, Tag
from .serializers import LeadSerializer, TagSerializer

from django.utils import timezone
from .models import LeadScrapeJob
from .serializers import LeadScrapeJobSerializer

class LeadViewSet(viewsets.ModelViewSet):
    serializer_class = LeadSerializer
    queryset = Lead.objects.all()

    def get_queryset(self):
        # Do not rely only on thread-local tenant middleware for JWT requests.
        return Lead.objects.filter(organization=self.request.user.organization)

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
        
        # Trigger async celery task
        from .tasks import import_leads_from_csv
        file_contents = file_obj.read().decode('utf-8')
        
        # Ensure we pass the organization to the task
        import_leads_from_csv.delay(file_contents, request.user.organization.id)
        
        return Response({"message": "File received. Processing in background.", "filename": file_obj.name}, status=status.HTTP_202_ACCEPTED)
    
    @action(detail=False, methods=['post'], url_path='scrape')
    def scrape(self, request):
        query = request.data.get('query', '').strip()
        limit = int(request.data.get('limit', 50))
        
        if not query:
            return Response({"error": "A search query is required."}, status=status.HTTP_400_BAD_REQUEST)
        if limit > 200:
            limit = 200 # Enforce security constraint max limit

        org = request.user.organization

        # Constraint 1: Check for an active running job in this organization
        active_job = LeadScrapeJob.objects.filter(organization=org, status='RUNNING').exists()
        if active_job:
            return Response({"error": "Your organization already has an active lead scraping job running."}, status=status.HTTP_400_BAD_REQUEST)

        # Constraint 2: Enforce 5-minute cooldown period between completions
        five_minutes_ago = timezone.now() - timezone.timedelta(minutes=5)
        recent_job = LeadScrapeJob.objects.filter(organization=org, status='COMPLETED', completed_at__gte=five_minutes_ago).exists()
        if recent_job:
            return Response({"error": "Throttled. Please wait 5 minutes between lead generation queries."}, status=status.HTTP_429_TOO_MANY_REQUESTS)

        # Create tracking job record
        job = LeadScrapeJob.objects.create(
            organization=org,
            query=query,
            limit=limit,
            status='PENDING'
        )

        # Dispatch Celery background worker agent task
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

    @action(detail=False, methods=['get'], url_path='scrape/history')
    def scrape_history(self, request):
        jobs = LeadScrapeJob.objects.filter(organization=request.user.organization).order_by('-created_at')
        serializer = LeadScrapeJobSerializer(jobs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

class TagViewSet(viewsets.ModelViewSet):
    serializer_class = TagSerializer
    queryset = Tag.objects.all()

    def get_queryset(self):
        return Tag.objects.filter(organization=self.request.user.organization)

    def perform_create(self, serializer):
        serializer.save(organization=self.request.user.organization)
