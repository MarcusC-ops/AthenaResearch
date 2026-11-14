from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.views import LogoutView
from django.http import HttpResponseNotAllowed
from django.shortcuts import redirect, render

from core.services import list_notifications, mark_all_read, sign_in_check, user_role


def dashboard(request):
    role = user_role(request.user)
    if role == 'coordinator':
        role_line = f'Study coordinator at {request.user.staff_profile.organisation}'
    elif role == 'admin':
        role_line = 'Platform admin'
    else:
        role_line = 'Operations executive'
    return render(request, 'adminpanel/dashboard.html', {'role_line': role_line})


def panel_login(request):
    error = None
    next_url = request.GET.get('next') or request.POST.get('next') or ''
    if request.method == 'POST':
        user, error = sign_in_check(
            request.POST.get('email', ''), request.POST.get('password', '')
        )
        if user:
            if not user.has_perm('core.panel_access'):
                error = 'This sign-in is for research teams and Athena staff.'
            else:
                login(request, user)
                return redirect(next_url or '/panel/')
    return render(request, 'adminpanel/login.html', {'error': error, 'next': next_url})


class PanelLogoutView(LogoutView):
    next_page = '/panel/login/'

    def get(self, request, *args, **kwargs):
        return HttpResponseNotAllowed(['POST'])


def notifications(request):
    return render(
        request, 'adminpanel/notifications.html',
        {'notifications': list_notifications(request.user)},
    )


def mark_notifications_read(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    mark_all_read(request.user)
    messages.success(request, 'All notifications marked as read.')
    return redirect('/panel/notifications/')
