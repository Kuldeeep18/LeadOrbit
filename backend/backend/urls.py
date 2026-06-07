from django.contrib import admin
from django.http import JsonResponse
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView
from rest_framework_simplejwt.views import TokenObtainPairView as BaseTokenObtainPairView
from users.jwt import CustomTokenObtainSerializer

class CustomTokenObtainPairView(BaseTokenObtainPairView):
    serializer_class = CustomTokenObtainSerializer

from users.views import AuthViewSet
from leads.views import LeadViewSet, TagViewSet
from campaigns.views import (
    CampaignViewSet,
    SequenceStepViewSet,
    WebhookView,
    DashboardAnalyticsView,
    AIGenerateView,
    unsubscribe_view
)
from campaigns.google_auth_views import GoogleOAuthLoginView, GoogleOAuthCallbackView, ConnectedAccountsListView


def api_root(_request):
    return JsonResponse({
        'status': 'ok',
        'service': 'LeadOrbit backend API',
        'base_path': '/api/v1/',
    })

router = DefaultRouter()
router.register(r'auth', AuthViewSet, basename='auth')
router.register(r'leads', LeadViewSet, basename='leads')
router.register(r'tags', TagViewSet, basename='tags')
router.register(r'campaigns', CampaignViewSet, basename='campaigns')

urlpatterns = [
    path('', api_root, name='api_root'),
    path('admin/', admin.site.urls),
    path('api/v1/token/', CustomTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/v1/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('api/v1/webhooks/email/', WebhookView.as_view(), name='email_webhook'),
    path('api/v1/analytics/dashboard/', DashboardAnalyticsView.as_view(), name='dashboard_analytics'),
    path('api/v1/campaigns/ai-generate/', AIGenerateView.as_view(), name='ai_generate'),
    # Google OAuth
    path('api/v1/auth/google/login', GoogleOAuthLoginView.as_view(), name='google_oauth_login'),
    path('api/v1/auth/google/callback', GoogleOAuthCallbackView.as_view(), name='google_oauth_callback'),
    path('auth/google/login', GoogleOAuthLoginView.as_view(), name='google_oauth_login_fallback'),
    path('auth/google/callback', GoogleOAuthCallbackView.as_view(), name='google_oauth_callback_fallback'),
    path('api/v1/connected-accounts/', ConnectedAccountsListView.as_view(), name='connected_accounts'),
    path('api/v1/unsubscribe/<uuid:lead_id>/<str:token>/', unsubscribe_view, name='unsubscribe'),
    path('api/v1/', include(router.urls)),
]

