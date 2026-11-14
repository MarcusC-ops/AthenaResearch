from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render

from core.services import user_role


class PanelAccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith('/panel/') and request.path != '/panel/login/':
            if not request.user.is_authenticated:
                return redirect(f'/panel/login/?next={request.path}')
            if user_role(request.user) not in ('coordinator', 'staff', 'admin'):
                return render(
                    request,
                    '403.html',
                    {'message': 'You do not have access to this page.'},
                    status=403,
                )
        return self.get_response(request)
