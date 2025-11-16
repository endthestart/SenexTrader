from django.apps import AppConfig

from services.core.logging import get_logger

logger = get_logger(__name__)


class StreamingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "streaming"

    def ready(self):
        # Sessions are refreshed on-demand in TastyTradeSessionService.get_session_for_user
        pass
