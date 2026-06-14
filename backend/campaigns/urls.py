from django.urls import path
from . import views

app_name = 'campaigns'

urlpatterns = [
    path('campaigns/<uuid:campaign_id>/validate-launch/', views.validate_campaign_launch, name='validate_campaign_launch'),
]