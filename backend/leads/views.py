from rest_framework import viewsets, parsers, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import BlockedDomain, Lead, Tag
from .serializers import BlockedDomainSerializer, LeadSerializer, TagSerializer

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
