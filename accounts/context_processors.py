from .utils import get_view_mode

def view_mode(request):
    if not request.user.is_authenticated:
        return {}
    return {"view_mode": get_view_mode(request)}