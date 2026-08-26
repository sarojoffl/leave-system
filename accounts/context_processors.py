from django.conf import settings

from .utils import get_view_mode

def view_mode(request):
    if not request.user.is_authenticated:
        return {}
    is_proxy_logger = request.user.username in getattr(settings, "STAFF_MOVEMENT_PROXY_LOGGER_USERNAMES", [])
    return {
        "view_mode": get_view_mode(request),
        "is_proxy_logger": is_proxy_logger,
    }