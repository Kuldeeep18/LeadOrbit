from rest_framework import viewsets, parsers, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import BlockedDomain, Lead, LeadImportJob, Tag
from .serializers import BlockedDomainSerializer, LeadImportJobSerializer, LeadSerializer, TagSerializer


class LeadImportJobPagination(PageNumberPagination):
    page_size = 10

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
