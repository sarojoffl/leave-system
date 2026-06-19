# accounts/middleware.py
from django.shortcuts import redirect
from django.urls import reverse

class ForcePasswordChangeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        exempt = {reverse("change_password"), reverse("logout")}
        if (
            request.user.is_authenticated
            and getattr(request.user, "must_change_password", False)
            and request.path not in exempt
        ):
            return redirect("change_password")
        return self.get_response(request)