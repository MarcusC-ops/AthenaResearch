from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.views import LogoutView
from django.http import HttpResponseNotAllowed
from django.shortcuts import redirect, render

from core.services import register_participant, register_researcher, sign_in_check, user_role

from .forms import ParticipantRegistrationForm, ResearcherRegistrationForm

def register(request):
    audience = request.GET.get('as', 'participant')
    if audience not in ('participant', 'researcher'):
        audience = 'participant'
    form_class = ParticipantRegistrationForm if audience == 'participant' else ResearcherRegistrationForm
    form = form_class(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        data = form.cleaned_data
        if audience == 'participant':
            user = register_participant(
                data['first_name'], data['last_name'], data['email'],
                data['mobile'], data['password'],
            )
            login(request, user)
            messages.success(
                request,
                'Welcome to Athena. Complete your profile to see studies picked for you.',
            )
            return redirect('/onboarding/')
        register_researcher(
            data['first_name'], data['last_name'], data['email'],
            data['organisation'].id, data['job_title'], data['mobile'],
            data['password'],
        )
        return render(request, 'accounts/researcher_thanks.html')
    return render(request, 'accounts/register.html', {'form': form, 'audience': audience})


def sign_in(request):
    error = None
    next_url = request.GET.get('next') or request.POST.get('next') or ''
    if request.method == 'POST':
        user, error = sign_in_check(
            request.POST.get('email', ''), request.POST.get('password', '')
        )
        if user:
            login(request, user)
            return redirect(next_url or ('/account/' if user_role(user) == 'participant' else '/panel/'))
    return render(request, 'accounts/login.html', {'error': error, 'next': next_url})


class AccountLogoutView(LogoutView):
    next_page = '/'

    def get(self, request, *args, **kwargs):
        return HttpResponseNotAllowed(['POST'])


def profile(request):
    from storefront.decorators import participant_required
    return participant_required(_profile)(request)


def _profile(request):
    return render(request, 'accounts/profile.html', {'profile': request.user.participant_profile})
