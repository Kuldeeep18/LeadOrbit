from uuid import UUID

from django.db.models import Q
from rest_framework import viewsets, parsers, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Lead, Tag
from .serializers import LeadSerializer, TagSerializer

class LeadViewSet(viewsets.ModelViewSet):
    serializer_class = LeadSerializer
    queryset = Lead.objects.all()

    def get_queryset(self):
        # Do not rely only on thread-local tenant middleware for JWT requests.
        return Lead.objects.filter(organization=self.request.user.organization)

    def _matches_search(self, lead, search_value):
        normalized = search_value.strip().casefold()
        searchable_values = [
            lead.email,
            lead.first_name,
            lead.last_name,
            lead.company,
        ]
        return any(
            normalized in str(value or '').casefold()
            for value in searchable_values
        )

    def _filter_by_tag(self, queryset, tag_value):
        value = (tag_value or '').strip()
        if not value:
            return queryset

        tag_tokens = [token.strip() for token in value.split(',') if token.strip()]
        if not tag_tokens:
            return queryset

        tag_ids = []
        tag_names = []
        for token in tag_tokens:
            try:
                tag_ids.append(UUID(token))
                continue
            except (TypeError, ValueError):
                pass
            tag_names.append(token)

        tag_filter = Q()
        has_filter = False
        if tag_ids:
            tag_filter |= Q(lead_tags__tag__id__in=tag_ids)
            has_filter = True
        if tag_names:
            name_filter = Q()
            for token in tag_names:
                name_filter |= Q(lead_tags__tag__name__iexact=token)
            tag_filter |= name_filter
            has_filter = True

        if not has_filter:
            return queryset

        return queryset.filter(tag_filter).distinct()

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset().prefetch_related('lead_tags__tag')

        tag_value = request.query_params.get('tag') or request.query_params.get('tag_id') or ''
        search_value = request.query_params.get('search') or request.query_params.get('q') or ''

        queryset = self._filter_by_tag(queryset, tag_value)
        leads = list(queryset)

        if search_value.strip():
            leads = [lead for lead in leads if self._matches_search(lead, search_value)]

        serializer = self.get_serializer(leads, many=True)
        return Response(serializer.data)

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
