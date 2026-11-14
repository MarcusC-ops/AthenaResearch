from functools import wraps

from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect

from core.services import user_role


def participant_required(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f'/accounts/login/?next={request.path}')
        if user_role(request.user) != 'participant':
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapped
