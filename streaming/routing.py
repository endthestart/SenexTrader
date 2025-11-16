from django.urls import re_path

from .consumers import StreamingConsumer

# Production WebSocket routing
websocket_urlpatterns = [
    re_path(r"ws/streaming/$", StreamingConsumer.as_asgi()),
]
