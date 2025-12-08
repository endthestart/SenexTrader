"""URL configuration for senextrader project."""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import TemplateView

from accounts.views import health_check, health_check_simple
from trading.views import dashboard_view

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("api/accounts/", include("accounts.api_urls")),  # Accounts API endpoints
    path("trading/", include("trading.urls")),
    # Note: WebSocket routing for streaming is in asgi.py, not HTTP URLs
    path("dashboard/", dashboard_view, name="dashboard"),  # Direct dashboard route
    path("", TemplateView.as_view(template_name="home.html"), name="home"),
    # Health check endpoints for container orchestration
    path("health/", health_check, name="health"),
    path("health/simple/", health_check_simple, name="health-simple"),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
