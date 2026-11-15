from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.views import LogoutView
from django.core.exceptions import ValidationError
from django.http import Http404, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST, require_http_methods

from core.models import Study
from core.services import (
    create_pre_screen_question,
    create_study,
    delete_pre_screen_question,
    get_panel_study,
    list_notifications,
    mark_all_read,
    panel_studies,
    run_compliance_checks,
    set_auto_shortlist,
    sign_in_check,
    submit_study_for_review,
    update_pre_screen_question,
    update_study,
    user_role,
)

from .decorators import coordinator_required
from .forms import PreScreenQuestionForm, StudyForm


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


STUDY_STATUS_TABS = [
    ('', 'All', None),
    (Study.Status.DRAFT, 'Draft', Study.Status.DRAFT),
    (Study.Status.PENDING_REVIEW, 'Pending review', Study.Status.PENDING_REVIEW),
    (Study.Status.CHANGES_REQUESTED, 'Changes requested', Study.Status.CHANGES_REQUESTED),
    (Study.Status.PUBLISHED, 'Published', Study.Status.PUBLISHED),
    (Study.Status.FULL, 'Full', Study.Status.FULL),
    (Study.Status.PAUSED, 'Paused', Study.Status.PAUSED),
    (Study.Status.CLOSED, 'Closed', Study.Status.CLOSED),
]


def _panel_study_or_404(request, study_id):
    try:
        return get_panel_study(request.user, study_id)
    except Study.DoesNotExist:
        raise Http404


def _coordinator_organisation(request):
    return request.user.staff_profile.organisation


def study_list(request):
    status = request.GET.get('status', '')
    all_studies = panel_studies(request.user)
    studies = panel_studies(request.user, status)
    tabs = [
        {
            'value': value,
            'label': label,
            'count': all_studies.count() if value == '' else all_studies.filter(status=value).count(),
            'active': status == value,
        }
        for value, label, _ in STUDY_STATUS_TABS
    ]
    return render(request, 'adminpanel/studies.html', {
        'studies': studies,
        'tabs': tabs,
        'show_organisation': user_role(request.user) in ('staff', 'admin'),
    })


@coordinator_required
@require_http_methods(['GET', 'POST'])
def study_new(request):
    organisation = _coordinator_organisation(request)
    form = StudyForm(
        request.POST or None,
        organisation=organisation,
    )
    if request.method == 'POST' and form.is_valid():
        try:
            study = create_study(form, request.user)
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, 'Study saved as draft.')
            return redirect('adminpanel:study_detail', study_id=study.pk)
    return render(request, 'adminpanel/study_form.html', {
        'form': form,
        'heading': 'New study',
        'is_new': True,
    })


@coordinator_required
@require_http_methods(['GET', 'POST'])
def study_edit(request, study_id):
    study = _panel_study_or_404(request, study_id)
    if study.status not in (Study.Status.DRAFT, Study.Status.CHANGES_REQUESTED):
        messages.error(request, 'Only draft or returned listings can be edited.')
        return redirect('adminpanel:study_detail', study_id=study.pk)
    form = StudyForm(
        request.POST or None,
        instance=study,
        organisation=_coordinator_organisation(request),
    )
    if request.method == 'POST' and form.is_valid():
        try:
            study = update_study(form, request.user)
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, 'Study changes saved.')
            return redirect('adminpanel:study_detail', study_id=study.pk)
    return render(request, 'adminpanel/study_form.html', {
        'form': form,
        'heading': f'Edit {study.title}',
        'is_new': False,
        'study': study,
    })


def study_detail(request, study_id):
    study = _panel_study_or_404(request, study_id)
    if request.method == 'POST':
        if request.POST.get('action') != 'toggle_auto_shortlist':
            return HttpResponseNotAllowed(['GET', 'POST'])
        new_value = not study.auto_shortlist_high
        try:
            set_auto_shortlist(study, new_value, request.user)
        except ValidationError as error:
            messages.error(request, error.messages[0])
            return redirect('adminpanel:study_detail', study_id=study.pk)
        messages.success(
            request,
            'Auto-shortlist is on.' if new_value else 'Auto-shortlist is off.',
        )
        return redirect('adminpanel:study_detail', study_id=study.pk)
    return render(request, 'adminpanel/study_detail.html', {'study': study})


@coordinator_required
@require_http_methods(['GET', 'POST'])
def study_questions(request, study_id):
    study = _panel_study_or_404(request, study_id)
    can_edit = study.status in (
        Study.Status.DRAFT,
        Study.Status.CHANGES_REQUESTED,
    )
    if not can_edit:
        messages.error(
            request,
            'Pre-screen questions can only be changed on draft or returned listings.',
        )
        return redirect('adminpanel:study_detail', study_id=study.pk)
    form = PreScreenQuestionForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            create_pre_screen_question(study, form)
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, 'Pre-screen question added.')
            return redirect('adminpanel:study_questions', study_id=study.pk)
    return render(request, 'adminpanel/study_questions.html', {
        'study': study,
        'questions': study.pre_screen_questions.all(),
        'form': form,
    })


@coordinator_required
@require_http_methods(['GET', 'POST'])
def study_question_edit(request, study_id, question_id):
    study = _panel_study_or_404(request, study_id)
    if study.status not in (Study.Status.DRAFT, Study.Status.CHANGES_REQUESTED):
        messages.error(
            request,
            'Pre-screen questions can only be changed on draft or returned listings.',
        )
        return redirect('adminpanel:study_detail', study_id=study.pk)
    question = get_object_or_404(study.pre_screen_questions, pk=question_id)
    form = PreScreenQuestionForm(request.POST or None, instance=question)
    if request.method == 'POST' and form.is_valid():
        try:
            update_pre_screen_question(study, question, form)
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, 'Pre-screen question updated.')
            return redirect('adminpanel:study_questions', study_id=study.pk)
    return render(request, 'adminpanel/study_question_form.html', {
        'study': study,
        'question': question,
        'form': form,
    })


@coordinator_required
@require_http_methods(['GET', 'POST'])
def study_question_delete(request, study_id, question_id):
    study = _panel_study_or_404(request, study_id)
    if study.status not in (Study.Status.DRAFT, Study.Status.CHANGES_REQUESTED):
        messages.error(
            request,
            'Pre-screen questions can only be changed on draft or returned listings.',
        )
        return redirect('adminpanel:study_detail', study_id=study.pk)
    question = get_object_or_404(study.pre_screen_questions, pk=question_id)
    if request.method == 'POST':
        try:
            delete_pre_screen_question(study, question.pk)
        except ValidationError as error:
            messages.error(request, error.messages[0])
            return redirect('adminpanel:study_questions', study_id=study.pk)
        messages.success(request, 'Pre-screen question deleted.')
        return redirect('adminpanel:study_questions', study_id=study.pk)
    return render(request, 'adminpanel/study_question_delete.html', {
        'study': study,
        'question': question,
    })


def study_preview(request, study_id):
    study = _panel_study_or_404(request, study_id)
    return render(request, 'adminpanel/study_preview.html', {
        'study': study,
        'approved_reviews': [],
        'is_shortlisted': False,
        'application': None,
        'apply_step': None,
        'preview': True,
    })


@coordinator_required
@require_http_methods(['GET', 'POST'])
def study_submit(request, study_id):
    study = _panel_study_or_404(request, study_id)
    checks = run_compliance_checks(study)
    if request.method == 'POST':
        try:
            submit_study_for_review(study, request.user)
        except ValidationError as error:
            messages.error(request, error.messages[0])
        else:
            messages.success(request, 'Study submitted for review.')
            return redirect('adminpanel:study_detail', study_id=study.pk)
        return redirect('adminpanel:study_submit', study_id=study.pk)
    if study.status not in (Study.Status.DRAFT, Study.Status.CHANGES_REQUESTED):
        messages.error(request, 'Only draft or returned listings can be submitted.')
        return redirect('adminpanel:study_detail', study_id=study.pk)
    return render(request, 'adminpanel/study_submit.html', {
        'study': study,
        'checks': checks,
        'all_pass': all(check.passed for check in checks),
    })
