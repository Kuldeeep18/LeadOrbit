from rest_framework import viewsets, parsers, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from django.http import StreamingHttpResponse
import csv
from .models import BlockedDomain, Lead, Tag
from .serializers import BlockedDomainSerializer, LeadSerializer, TagSerializer

class Echo:
    """An object that implements just the write method of the file-like interface."""
    def write(self, value):
        """Write the value by returning it, instead of storing in a buffer."""
        return value


class StandardResultsSetPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = 'page_size'

class LeadViewSet(viewsets.ModelViewSet):
    serializer_class = LeadSerializer
    queryset = Lead.objects.all()
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        # Do not rely only on thread-local tenant middleware for JWT requests.
        from django.db.models import Q
        queryset = Lead.objects.filter(organization=self.request.user.organization)

        search = self.request.query_params.get('search')
        tag = self.request.query_params.get('tag')

        if search:
            queryset = queryset.filter(
                Q(email__icontains=search) |
                Q(first_name__icontains=search) |
                Q(last_name__icontains=search) |
                Q(company__icontains=search)
            )

        if tag:
            queryset = queryset.filter(lead_tags__tag__id=tag)

        return queryset

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

    @action(detail=False, methods=['get'])
    def export(self, request):
        queryset = Lead.objects.filter(organization=request.user.organization).prefetch_related('lead_tags__tag')

        def iter_items():
            yield [
                'first_name', 'last_name', 'email', 'company', 'phone',
                'linkedin_url', 'score', 'tags', 'created_at'
            ]
            for lead in queryset:
                tags = ", ".join([lt.tag.name for lt in lead.lead_tags.all()])
                yield [
                    lead.first_name or '',
                    lead.last_name or '',
                    lead.email or '',
                    lead.company or '',
                    lead.phone or '',
                    lead.linkedin_url or '',
                    lead.score,
                    tags,
                    lead.created_at.strftime('%Y-%m-%d %H:%M:%S') if lead.created_at else ''
                ]

        pseudo_buffer = Echo()
        writer = csv.writer(pseudo_buffer)
        
        response = StreamingHttpResponse(
            (writer.writerow(row) for row in iter_items()),
            content_type="text/csv"
        )
        response['Content-Disposition'] = 'attachment; filename="leads_export.csv"'
        return response

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
