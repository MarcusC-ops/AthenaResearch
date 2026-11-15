from functools import wraps

from django.core.exceptions import PermissionDenied

from core.services import user_role


def staff_required(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if user_role(request.user) not in ('staff', 'admin'):
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if user_role(request.user) != 'admin':
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapped


def coordinator_required(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if user_role(request.user) != 'coordinator':
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapped
