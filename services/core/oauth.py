import secrets
import time

from django.http import HttpRequest
from django.urls import reverse

STATE_SESSION_KEY = "oauth.state"
STATE_TS_SESSION_KEY = "oauth.state_ts"


def generate_state(request: HttpRequest) -> str:
    state = secrets.token_urlsafe(32)
    request.session[STATE_SESSION_KEY] = state
    request.session[STATE_TS_SESSION_KEY] = int(time.time())
    return state


def validate_state(
    request: HttpRequest, returned_state: str | None, ttl_seconds: int = 300
) -> bool:
    stored_state = request.session.get(STATE_SESSION_KEY)
    ts = request.session.get(STATE_TS_SESSION_KEY)
    if not returned_state or not stored_state or returned_state != stored_state:
        return False
    if ts is None:
        return False
    return not int(time.time()) - int(ts) > ttl_seconds


def clear_state(request: HttpRequest) -> None:
    request.session.pop(STATE_SESSION_KEY, None)
    request.session.pop(STATE_TS_SESSION_KEY, None)


def build_redirect_uri(request: HttpRequest, view_name: str) -> str:
    return request.build_absolute_uri(reverse(view_name))
