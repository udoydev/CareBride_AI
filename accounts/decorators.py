from functools import wraps
from django.views.decorators.cache import never_cache
from django.shortcuts import redirect
from django.contrib import messages


def never_cache_auth(view_func):
    """
    Decorator for authentication views & protected routes that guarantees browsers,
    proxies, and BFCache NEVER cache authenticated state or sensitive HTML pages.
    Sets explicit Cache-Control, Pragma, and Expires headers.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        response = view_func(request, *args, **kwargs)
        response["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0, private"
        response["Pragma"] = "no-cache"
        response["Expires"] = "0"
        return response
    return _wrapped_view
