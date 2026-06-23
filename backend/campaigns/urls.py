from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

app_name = 'campaigns'

router = DefaultRouter()
router.register(r'campaigns', views.CampaignViewSet)
router.register(r'email-templates', views.EmailTemplateViewSet)

urlpatterns = [
    path('', include(router.urls)),
]