from django.urls import path

from . import views

app_name = "streaming"

urlpatterns = [
    path("test/", views.WebSocketTestView.as_view(), name="test"),
    path("health/", views.StreamingHealthView.as_view(), name="health"),
    path("cache/", views.CacheMonitorView.as_view(), name="cache_monitor"),
    path("api/session-status/", views.SessionStatusView.as_view(), name="session_status"),
    path(
        "api/session-control/",
        views.SessionControlView.as_view(),
        name="session_control",
    ),
]
