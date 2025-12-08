"""
ASGI config for senextrader project.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/asgi/
"""

import faulthandler
import os
import sys

faulthandler.enable(file=sys.stderr, all_threads=True)

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "senextrader.settings.development")
django_asgi_app = get_asgi_application()

from django.conf import settings  # noqa: E402

from channels.auth import AuthMiddlewareStack  # noqa: E402
from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.security.websocket import (  # noqa: E402
    AllowedHostsOriginValidator,
    OriginValidator,
)

from streaming.routing import websocket_urlpatterns  # noqa: E402

websocket_router = URLRouter(websocket_urlpatterns)
if hasattr(settings, "WS_ALLOWED_ORIGINS") and settings.WS_ALLOWED_ORIGINS:
    websocket_router = OriginValidator(
        websocket_router, allowed_origins=settings.WS_ALLOWED_ORIGINS
    )
else:
    websocket_router = AllowedHostsOriginValidator(websocket_router)

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": AuthMiddlewareStack(websocket_router),
    }
)
