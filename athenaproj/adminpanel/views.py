from io import StringIO

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.models import Group, User
from django.contrib.auth.views import LogoutView
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db.models import Count, Q
from django.http import Http404, HttpResponseBadRequest, HttpResponseNotAllowed
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from core.models import (
    Application, Appointment, Condition, Organisation, ParticipantProfile,
    Payout, Site, Study, StudyCategory, SupportRequest, Review,
    PredictionLog,
)
from core.services import (
    InvalidStatusMove,
    age_band,
    applicant_queue,
    amount_due,
    applicant_mix,
    band_distribution,
    band_pass_rates,
    check_eligibility,
    complete_participation,
    coordinator_dashboard,
    coordinator_withdraw,
    approve_researcher,
    approve_study,
    add_coordinator,
    create_organisation,
    create_pre_screen_question,
    create_study,
    delete_unused_record,
    delete_pre_screen_question,
    enrol_applicant,
    enrolled_count,
    earned_amount,
    get_panel_application,
    get_panel_study,
    get_settings,
    ml1_first_pick_counts,
    override_rate,
    add_staff_account,
    identity_unlocked,
    list_notifications,
    mark_not_selected,
    mark_all_read,
    mark_visit,
    model_inputs,
    move_to_review,
    override_band,
    panel_studies,
    record_screening_outcome,
    request_payout,
    approve_review,
    demand_supply_by_category,
    pay_payouts,
    platform_insights,
    reject_payout,
    reject_review,
    reply_to_support,
    run_compliance_checks,
    ops_dashboard,
    save_site,
    save_taxonomy_form,
    search_participants,
    set_coordinator_active,
    set_staff_active,
    set_staff_role,
    set_organisation_active,
    set_record_active,
    update_organisation,
    update_thresholds,
    update_study_as_staff,
    return_study,
    unpublish_study,
    save_visit_date,
    schedule_screening,
    shortlist_applicant,
    set_auto_shortlist,
    sign_in_check,
    study_funnel,
    submit_study_for_review,
    update_pre_screen_question,
    update_study,
    user_role,
    waitlist_applicant,
)

from .decorators import (
    admin_required,
    coordinator_required,
    panel_staff_or_coordinator_required,
    staff_required,
)
from .forms import (
    ApplicantFilterForm,
    CategoryForm,
    ConditionForm,
    CoordinatorForm,
    CoordinatorWithdrawForm,
    ModerationCommentsForm,
    NotSelectedForm,
    OrganisationForm,
    OverrideBandForm,
    ParticipationFilterForm,
    PayoutRejectForm,
    PlatformInsightsFilterForm,
    PreScreenQuestionForm,
    ReasonForm,
    ScreeningOutcomeForm,
    ScreeningScheduleForm,
    SupportReplyForm,
    SiteForm,
    StudyForm,
    VisitDateForm,
    ThresholdForm,
    StaffAccountForm,
)
from ml.services import model_card, prediction_stats


def dashboard(request):
    role = user_role(request.user)
    if role in ('staff', 'admin'):
        return operations_dashboard(request)
    if role == 'coordinator':
        dashboard_data = coordinator_dashboard(request.user)
        if dashboard_data:
            return render(request, 'adminpanel/dashboard_coordinator.html', dashboard_data)
        else:
            role_line = f'Study coordinator at {request.user.staff_profile.organisation}'
    else:
        role_line = 'Study coordinator'
    return render(request, 'adminpanel/dashboard_welcome.html', {'role_line': role_line})


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


@require_http_methods(['GET', 'POST'])
def study_edit(request, study_id):
    if user_role(request.user) in ('staff', 'admin'):
        return staff_study_edit(request, study_id)
    if user_role(request.user) != 'coordinator':
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied
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


@staff_required
@require_http_methods(['GET', 'POST'])
def staff_study_edit(request, study_id):
    study = get_object_or_404(
        Study.objects.select_related('organisation', 'category'),
        pk=study_id,
    )
    form = StudyForm(
        request.POST or None,
        instance=study,
        organisation=study.organisation,
        staff_mode=True,
    )
    if request.method == 'POST' and form.is_valid():
        try:
            study = update_study_as_staff(form, request.user)
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
        'staff_mode': True,
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


APPLICANT_TABS = (
    ('needs_action', 'Needs action'),
    ('under_review', 'Under review'),
    ('shortlisted', 'Shortlisted'),
    ('screening_scheduled', 'Screening scheduled'),
    ('screening_passed', 'Screening passed'),
    ('waitlisted', 'Waitlisted'),
)


def _applicant_queue_url(study_id):
    return f'/panel/studies/{study_id}/applicants/'


@require_http_methods(['GET', 'POST'])
def applicants(request, study_id):
    study = _panel_study_or_404(request, study_id)
    if request.method == 'POST':
        if request.POST.get('action') != 'toggle_auto_shortlist':
            return HttpResponseBadRequest('Unknown action.')
        new_value = not study.auto_shortlist_high
        try:
            set_auto_shortlist(study, new_value, request.user)
        except ValidationError as error:
            messages.error(request, error.messages[0])
        else:
            messages.success(
                request,
                'Auto-shortlist is on.' if new_value else 'Auto-shortlist is off.',
            )
        return redirect(_applicant_queue_url(study.pk))

    filter_form = ApplicantFilterForm(request.GET or None, study=study)
    filter_values = {'band': '', 'site': '', 'availability': ''}
    if filter_form.is_valid():
        cleaned = filter_form.cleaned_data
        filter_values = {
            'band': cleaned['band'],
            'site': cleaned['site'].pk if cleaned['site'] else '',
            'availability': cleaned['availability'],
        }
    tab = request.GET.get('tab', 'needs_action')
    if tab not in dict((value, label) for value, label in APPLICANT_TABS):
        tab = 'needs_action'

    def filtered_queue(selected_tab):
        return applicant_queue(study, selected_tab, **filter_values)

    applications = list(filtered_queue(tab))
    for application in applications:
        application.identity_is_unlocked = identity_unlocked(application)
        application.applicant_age_band = age_band(application.participant.age)
        application.priority_percentage = (
            round(application.ml2_probability * 100)
            if application.ml2_probability is not None else None
        )

    tabs = [
        {
            'value': value,
            'label': label,
            'count': filtered_queue(value).count(),
            'active': tab == value,
        }
        for value, label in APPLICANT_TABS
    ]
    settings = get_settings()
    high_threshold = round(settings.ml2_high_threshold * 100)
    medium_threshold = round(settings.ml2_medium_threshold * 100)
    return render(request, 'adminpanel/applicants.html', {
        'study': study,
        'applications': applications,
        'filter_form': filter_form,
        'filter_values': filter_values,
        'tab': tab,
        'tabs': tabs,
        'enrolled_count': enrolled_count(study),
        'high_threshold': high_threshold,
        'medium_threshold': medium_threshold,
    })


def _panel_application_or_404(request, application_id):
    try:
        return get_panel_application(request.user, application_id)
    except Application.DoesNotExist:
        raise Http404


def _report_action_error(request, error):
    if isinstance(error, ValidationError):
        messages.error(request, error.messages[0])
    else:
        messages.error(request, str(error))


@require_http_methods(['GET', 'POST'])
def application_detail(request, application_id):
    application = _panel_application_or_404(request, application_id)
    study = application.study
    screening_form = ScreeningScheduleForm(study=study)
    if request.method == 'POST':
        action = request.POST.get('action', '')
        try:
            if action == 'shortlist':
                shortlist_applicant(application, request.user)
                messages.success(request, 'Applicant shortlisted.')
            elif action == 'schedule_screening':
                screening_form = ScreeningScheduleForm(
                    request.POST, study=study
                )
                if not screening_form.is_valid():
                    messages.error(request, 'Enter a valid screening date, time and site.')
                    return redirect(
                        'adminpanel:application_detail',
                        application_id=application.pk,
                    )
                schedule_screening(
                    application,
                    screening_form.cleaned_data['when'],
                    screening_form.cleaned_data['site'],
                    request.user,
                )
                messages.success(request, 'Screening scheduled.')
            elif action == 'screening_passed':
                record_screening_outcome(application, True, request.user)
                messages.success(request, 'Screening result recorded.')
            elif action == 'enrol':
                enrol_applicant(application, request.user)
                messages.success(request, 'Applicant enrolled.')
            elif action == 'waitlist':
                waitlist_applicant(application, request.user)
                messages.success(request, 'Applicant waitlisted.')
            elif action == 'move_to_review':
                move_to_review(application, request.user)
                messages.success(request, 'Application moved to review.')
            else:
                return HttpResponseBadRequest('Unknown action.')
        except (InvalidStatusMove, ValidationError) as error:
            _report_action_error(request, error)
        return redirect(
            'adminpanel:application_detail',
            application_id=application.pk,
        )

    unlocked = identity_unlocked(application)
    profile = application.participant
    priority_percentage = (
        round(application.ml2_probability * 100)
        if application.ml2_probability is not None else None
    )
    override_message = ''
    if application.band_overridden:
        old_band = dict(Application.Band.choices).get(
            application.original_band, application.original_band
        )
        new_band = application.get_ml2_band_display()
        actor_name = (
            application.overridden_by.get_full_name()
            if application.overridden_by_id else 'Unknown'
        )
        override_date = timezone.localtime(
            application.overridden_at
        ).strftime('%d %b %Y').lstrip('0')
        override_message = (
            f'Band changed from {old_band} to {new_band} by {actor_name} on '
            f'{override_date}: {application.override_reason}'
        )
    return render(request, 'adminpanel/application_detail.html', {
        'application': application,
        'study': study,
        'identity_unlocked': unlocked,
        'age_band': age_band(profile.age),
        'profile': profile,
        'condition_count': profile.conditions.count(),
        'answers': application.answers.select_related('question').order_by(
            'question__order'
        ),
        'eligibility_rows': check_eligibility(profile, study),
        'status_events': application.status_events.select_related('actor').order_by(
            'created_at', 'pk'
        ),
        'screening_appointments': application.appointments.filter(
            kind='screening'
        ).select_related('site').order_by('-created_at', '-pk'),
        'screening_form': screening_form,
        'screening_outcome_form': ScreeningOutcomeForm(),
        'is_study_full': enrolled_count(study) >= study.target_enrolment,
        'priority_percentage': priority_percentage,
        'model_inputs': model_inputs(application),
        'override_message': override_message,
    })


@require_http_methods(['GET', 'POST'])
def application_not_selected(request, application_id):
    application = _panel_application_or_404(request, application_id)
    form = NotSelectedForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            mark_not_selected(
                application,
                request.user,
                form.cleaned_data['reason'],
            )
        except (InvalidStatusMove, ValidationError) as error:
            _report_action_error(request, error)
            return redirect(
                'adminpanel:application_detail',
                application_id=application.pk,
            )
        messages.success(request, 'Application marked as not selected.')
        return redirect(
            'adminpanel:application_detail',
            application_id=application.pk,
        )
    return render(request, 'adminpanel/application_not_selected.html', {
        'application': application,
        'form': form,
    })


@require_http_methods(['GET', 'POST'])
def application_screening_failed(request, application_id):
    application = _panel_application_or_404(request, application_id)
    form = ScreeningOutcomeForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            record_screening_outcome(
                application,
                False,
                request.user,
                note=form.cleaned_data['note'],
            )
        except (InvalidStatusMove, ValidationError) as error:
            _report_action_error(request, error)
            return redirect(
                'adminpanel:application_detail',
                application_id=application.pk,
            )
        messages.success(request, 'Screening result recorded.')
        return redirect(
            'adminpanel:application_detail',
            application_id=application.pk,
        )
    return render(request, 'adminpanel/application_screening_failed.html', {
        'application': application,
        'form': form,
    })


def _override_session_key(application):
    return f'override_{application.pk}'


@require_http_methods(['GET', 'POST'])
def application_override(request, application_id):
    application = _panel_application_or_404(request, application_id)
    form = OverrideBandForm(
        request.POST or None,
        current_band=application.ml2_band,
    )
    if request.method == 'POST' and form.is_valid():
        request.session[_override_session_key(application)] = {
            'new_band': form.cleaned_data['new_band'],
            'reason': form.cleaned_data['reason'],
        }
        messages.info(request, 'Review the band change before confirming.')
        return redirect(
            'adminpanel:application_override_confirm',
            application_id=application.pk,
        )
    return render(request, 'adminpanel/application_override.html', {
        'application': application,
        'form': form,
    })


@require_http_methods(['GET', 'POST'])
def application_override_confirm(request, application_id):
    application = _panel_application_or_404(request, application_id)
    key = _override_session_key(application)
    if request.method == 'POST' and request.POST.get('action') == 'cancel':
        request.session.pop(key, None)
        messages.info(request, 'Band change cancelled.')
        return redirect(
            'adminpanel:application_detail',
            application_id=application.pk,
        )
    saved = request.session.get(key)
    if not isinstance(saved, dict) or not saved.get('new_band') or not saved.get('reason'):
        messages.error(request, 'Choose a new band and reason first.')
        return redirect(
            'adminpanel:application_override',
            application_id=application.pk,
        )
    form = OverrideBandForm(saved, current_band=application.ml2_band)
    if not form.is_valid():
        request.session.pop(key, None)
        messages.error(request, 'Choose a new band and reason first.')
        return redirect(
            'adminpanel:application_override',
            application_id=application.pk,
        )
    if request.method == 'POST':
        try:
            override_band(
                application,
                form.cleaned_data['new_band'],
                form.cleaned_data['reason'],
                request.user,
            )
        except ValidationError as error:
            request.session.pop(key, None)
            _report_action_error(request, error)
            return redirect(
                'adminpanel:application_override',
                application_id=application.pk,
            )
        request.session.pop(key, None)
        messages.success(request, 'Band changed.')
        return redirect(
            'adminpanel:application_detail',
            application_id=application.pk,
        )
    return render(request, 'adminpanel/application_override_confirm.html', {
        'application': application,
        'current_band': application.get_ml2_band_display(),
        'new_band': dict(Application.Band.choices).get(
            form.cleaned_data['new_band'], form.cleaned_data['new_band']
        ),
        'reason': form.cleaned_data['reason'],
    })


@panel_staff_or_coordinator_required
def participation(request):
    role = user_role(request.user)
    org = (
        request.user.staff_profile.organisation
        if role == 'coordinator' else None
    )
    applications_qs = Application.objects.filter(
        status__in=[Application.Status.ENROLLED, Application.Status.COMPLETED],
    ).select_related('participant__user', 'study').order_by('-created_at')
    if org is not None:
        applications_qs = applications_qs.filter(study__organisation=org)

    form = ParticipationFilterForm(
        request.GET or None,
        organisation=org,
    )
    if form.is_valid() and form.cleaned_data.get('study_id'):
        applications_qs = applications_qs.filter(study=form.cleaned_data['study_id'])

    applications_with_amounts = []
    for app in applications_qs:
        attended_count = app.appointments.filter(
            kind=Appointment.Kind.VISIT,
            status=Appointment.Status.ATTENDED,
        ).count()
        due = amount_due(app)
        applications_with_amounts.append({
            'app': app,
            'attended_count': attended_count,
            'total_visits': app.study.total_visits,
            'due': due,
            'paid': sum(
                p.amount for p in app.payouts.filter(status=Payout.Status.PAID)
            ),
        })

    return render(request, 'adminpanel/participation.html', {
        'applications': applications_with_amounts,
        'filter_form': form,
    })


@panel_staff_or_coordinator_required
def participation_detail(request, application_id):
    applications = Application.objects.select_related(
        'participant__user',
        'study__organisation',
    )
    if user_role(request.user) == 'coordinator':
        applications = applications.filter(
            study__organisation=request.user.staff_profile.organisation,
        )
    application = get_object_or_404(applications, pk=application_id)

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'save_date':
            appointment_id = request.POST.get('appointment_id')
            appointment = get_object_or_404(
                Appointment,
                pk=appointment_id,
                application=application,
            )
            form = VisitDateForm(request.POST, appointment=appointment)
            if form.is_valid():
                try:
                    save_visit_date(
                        appointment,
                        form.cleaned_data['scheduled_for'],
                        request.user,
                    )
                    messages.success(request, 'Visit date saved.')
                except ValidationError as e:
                    messages.error(request, str(e))
            return redirect('adminpanel:participation_detail', application_id=application.pk)

        elif action == 'mark_attended':
            appointment_id = request.POST.get('appointment_id')
            appointment = get_object_or_404(
                Appointment,
                pk=appointment_id,
                application=application,
            )
            try:
                mark_visit(appointment, True, request.user)
                messages.success(request, 'Visit marked as attended.')
            except ValidationError as e:
                messages.error(request, str(e))
            return redirect('adminpanel:participation_detail', application_id=application.pk)

        elif action == 'mark_missed':
            appointment_id = request.POST.get('appointment_id')
            appointment = get_object_or_404(
                Appointment,
                pk=appointment_id,
                application=application,
            )
            try:
                mark_visit(appointment, False, request.user)
                messages.success(request, 'Visit marked as missed.')
            except ValidationError as e:
                messages.error(request, str(e))
            return redirect('adminpanel:participation_detail', application_id=application.pk)

        elif action == 'request_payout':
            try:
                request_payout(application, request.user)
                messages.success(request, 'Payout requested.')
            except ValidationError as e:
                messages.error(request, str(e))
            return redirect('adminpanel:participation_detail', application_id=application.pk)

        elif action == 'complete':
            try:
                complete_participation(application, request.user)
                messages.success(request, 'Participant marked as completed.')
            except ValidationError as e:
                messages.error(request, str(e))
            return redirect('adminpanel:participation_detail', application_id=application.pk)

        elif action == 'withdraw':
            return redirect('adminpanel:participation_withdraw', application_id=application.pk)

    visits = application.appointments.filter(kind=Appointment.Kind.VISIT).order_by('visit_number')
    screening = application.appointments.filter(kind=Appointment.Kind.SCREENING).first()
    due_now = amount_due(application)
    payouts = application.payouts.order_by('-created_at', '-id')

    return render(request, 'adminpanel/participation_detail.html', {
        'application': application,
        'screening': screening,
        'visits': visits,
        'due_now': due_now,
        'payouts': payouts,
    })


@panel_staff_or_coordinator_required
def participation_withdraw(request, application_id):
    applications = Application.objects.select_related('study__organisation')
    if user_role(request.user) == 'coordinator':
        applications = applications.filter(
            study__organisation=request.user.staff_profile.organisation,
        )
    application = get_object_or_404(applications, pk=application_id)

    if request.method == 'POST':
        form = CoordinatorWithdrawForm(request.POST)
        if form.is_valid():
            try:
                coordinator_withdraw(
                    application,
                    request.user,
                    form.cleaned_data['reason'],
                )
                messages.success(request, 'Participant withdrawn.')
            except ValidationError as e:
                messages.error(request, str(e))
            return redirect('adminpanel:participation_detail', application_id=application.pk)
    else:
        form = CoordinatorWithdrawForm()

    return render(request, 'adminpanel/participation_withdraw.html', {
        'application': application,
        'form': form,
    })


@panel_staff_or_coordinator_required
def insights(request):
    if user_role(request.user) in ('staff', 'admin'):
        form = PlatformInsightsFilterForm(request.GET or None)
        if form.is_valid():
            organisation = form.cleaned_data.get('organisation_id')
            study = form.cleaned_data.get('study_id')
            data = platform_insights(
                organisation.pk if organisation else None,
                study.pk if study else None,
            )
        else:
            data = platform_insights()
        return render(request, 'adminpanel/platform_insights.html', {
            **data,
            'form': form,
            'demand_supply': demand_supply_by_category(),
        })

    org = request.user.staff_profile.organisation
    studies = Study.objects.filter(
        organisation=org,
        status__in=[Study.Status.PUBLISHED, Study.Status.PAUSED, Study.Status.FULL],
    ).order_by('title')

    applications_qs = Application.objects.filter(study__in=studies)

    study_id = request.GET.get('study_id')
    if study_id:
        try:
            study = Study.objects.get(pk=study_id, organisation=org)
            applications_qs = applications_qs.filter(study=study)
        except Study.DoesNotExist:
            pass

    funnel = study_funnel(applications_qs)
    pass_rates = band_pass_rates(applications_qs)
    distribution = band_distribution(applications_qs)
    mix = applicant_mix(applications_qs)

    return render(request, 'adminpanel/insights.html', {
        'studies': studies,
        'selected_study_id': study_id,
        'funnel': funnel,
        'pass_rates': pass_rates,
        'distribution': distribution,
        'mix': mix,
    })


@staff_required
@require_http_methods(['GET', 'POST'])
def payouts(request):
    status = request.GET.get('status', Payout.Status.REQUESTED)
    if status not in dict(Payout.Status.choices):
        status = Payout.Status.REQUESTED
    queryset = Payout.objects.filter(status=status).select_related(
        'application__participant__user',
        'application__study__organisation',
    ).order_by('-created_at', '-id')
    if request.method == 'POST':
        ids = request.POST.getlist('ids')
        if not ids:
            messages.error(request, 'Select at least one payout.')
            return redirect('adminpanel:payouts')
        selected = queryset.filter(pk__in=ids)
        return render(request, 'adminpanel/payout_confirm.html', {
            'payouts': selected,
            'total': sum(payout.amount for payout in selected),
            'ids': ids,
        })
    return render(request, 'adminpanel/payouts.html', {
        'payouts': queryset,
        'status': status,
    })


@staff_required
@require_http_methods(['GET', 'POST'])
def payout_pay(request):
    ids = request.POST.getlist('ids') if request.method == 'POST' else request.GET.getlist('ids')
    if request.method == 'POST':
        try:
            count, total = pay_payouts(ids, request.user)
        except ValidationError as error:
            messages.error(request, error.messages[0])
            return redirect('adminpanel:payouts')
        messages.success(request, f'{count} payout{"s" if count != 1 else ""} paid.')
        return redirect('adminpanel:payouts',)
    payouts = Payout.objects.filter(
        pk__in=ids,
        status=Payout.Status.REQUESTED,
    ).select_related('application__study')
    return render(request, 'adminpanel/payout_confirm.html', {
        'payouts': payouts,
        'total': sum(payout.amount for payout in payouts),
        'ids': ids,
    })


@staff_required
@require_http_methods(['GET', 'POST'])
def payout_reject(request, payout_id):
    payout = get_object_or_404(
        Payout.objects.select_related('application__study'),
        pk=payout_id,
    )
    form = PayoutRejectForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            reject_payout(payout, request.user, form.cleaned_data['reason'])
        except ValidationError as error:
            form.add_error('reason', error.messages[0])
        else:
            messages.success(request, 'Payout rejected.')
            return redirect('adminpanel:payouts')
    return render(request, 'adminpanel/payout_reject.html', {
        'payout': payout,
        'form': form,
    })


@staff_required
@require_http_methods(['GET', 'POST'])
def reviews(request):
    status = request.GET.get('status', Review.Status.PENDING)
    if status not in dict(Review.Status.choices):
        status = Review.Status.PENDING
    review_list = Review.objects.filter(status=status).select_related(
        'participant', 'study',
    ).order_by('-created_at', '-id')
    if request.method == 'POST':
        review = get_object_or_404(Review, pk=request.POST.get('review_id'))
        try:
            approve_review(review, request.user)
        except ValidationError as error:
            messages.error(request, error.messages[0])
        else:
            messages.success(request, 'Review approved.')
        return redirect('adminpanel:reviews')
    return render(request, 'adminpanel/reviews.html', {
        'reviews': review_list,
        'status': status,
    })


@staff_required
@require_http_methods(['GET', 'POST'])
def review_reject(request, review_id):
    review = get_object_or_404(
        Review.objects.select_related('participant', 'study'),
        pk=review_id,
    )
    form = ReviewRejectForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            reject_review(review, request.user, form.cleaned_data['reason'])
        except ValidationError as error:
            form.add_error('reason', error.messages[0])
        else:
            messages.success(request, 'Review rejected.')
            return redirect('adminpanel:reviews')
    return render(request, 'adminpanel/review_reject.html', {
        'review': review,
        'form': form,
    })


@staff_required
def support(request):
    status = request.GET.get('status', SupportRequest.Status.OPEN)
    if status not in dict(SupportRequest.Status.choices):
        status = SupportRequest.Status.OPEN
    requests = SupportRequest.objects.filter(status=status).select_related(
        'application__participant__user',
        'application__study',
    ).order_by('-created_at', '-id')
    return render(request, 'adminpanel/support.html', {
        'support_requests': requests,
        'status': status,
    })


@staff_required
@require_http_methods(['GET', 'POST'])
def support_detail(request, support_id):
    support_request = get_object_or_404(
        SupportRequest.objects.select_related(
            'application__participant__user',
            'application__study',
        ),
        pk=support_id,
    )
    form = SupportReplyForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            reply_to_support(
                support_request,
                request.user,
                form.cleaned_data['reply'],
            )
        except ValidationError as error:
            form.add_error('reply', error.messages[0])
        else:
            messages.success(request, 'Reply sent.')
            return redirect('adminpanel:support_detail', support_id=support_request.pk)
    application = support_request.application
    return render(request, 'adminpanel/support_detail.html', {
        'support_request': support_request,
        'application': application,
        'events': application.status_events.order_by('-created_at', '-id')[:3],
        'visits_attended': application.appointments.filter(
            kind=Appointment.Kind.VISIT,
            status=Appointment.Status.ATTENDED,
        ).count(),
        'payouts': application.payouts.order_by('-created_at', '-id'),
        'form': form,
    })


@staff_required
def operations_dashboard(request):
    return render(request, 'adminpanel/dashboard.html', ops_dashboard())


@staff_required
def moderation(request):
    tabs = [
        ('pending_review', 'Pending review'),
        ('changes_requested', 'Changes requested'),
        ('live', 'Live'),
        ('paused', 'Paused'),
    ]
    selected = request.GET.get('status', 'pending_review')
    if selected == 'live':
        statuses = [Study.Status.PUBLISHED, Study.Status.FULL]
        studies = Study.objects.filter(status__in=statuses)
    elif selected in dict(tabs):
        studies = Study.objects.filter(status=selected)
    else:
        selected = 'pending_review'
        studies = Study.objects.filter(status=Study.Status.PENDING_REVIEW)
    return render(request, 'adminpanel/moderation.html', {
        'studies': studies.select_related('organisation').order_by('-submitted_at', '-id'),
        'tabs': [
            {
                'value': value,
                'label': label,
                'count': (
                    Study.objects.filter(
                        status__in=[Study.Status.PUBLISHED, Study.Status.FULL]
                    ).count() if value == 'live'
                    else Study.objects.filter(status=value).count()
                ),
                'active': selected == value,
            }
            for value, label in tabs
        ],
    })


@staff_required
@require_http_methods(['GET', 'POST'])
def moderation_detail(request, study_id):
    study = get_object_or_404(
        Study.objects.select_related('organisation', 'category'),
        pk=study_id,
    )
    checks = run_compliance_checks(study)
    if request.method == 'POST':
        action = request.POST.get('action')
        try:
            if action == 'approve':
                approve_study(study, request.user)
                messages.success(request, 'Study approved and published.')
            elif action == 'return':
                form = ModerationCommentsForm(request.POST)
                if not form.is_valid():
                    return render(request, 'adminpanel/moderation_detail.html', {
                        'study': study,
                        'checks': checks,
                        'all_pass': all(check.passed for check in checks),
                        'comments_form': form,
                        'preview': True,
                        'approved_reviews': [],
                        'is_shortlisted': False,
                        'application': None,
                        'apply_step': None,
                    })
                return_study(study, request.user, form.cleaned_data['comments'])
                messages.success(request, 'Study returned with comments.')
            else:
                return HttpResponseBadRequest('Unknown action.')
        except ValidationError as error:
            messages.error(request, error.messages[0])
        return redirect('adminpanel:moderation_detail', study_id=study.pk)
    return render(request, 'adminpanel/moderation_detail.html', {
        'study': study,
        'checks': checks,
        'all_pass': all(check.passed for check in checks),
        'comments_form': ModerationCommentsForm(),
        'preview': True,
        'approved_reviews': [],
        'is_shortlisted': False,
        'application': None,
        'apply_step': None,
    })


@staff_required
@require_http_methods(['GET', 'POST'])
def moderation_unpublish(request, study_id):
    study = get_object_or_404(
        Study,
        pk=study_id,
        status__in=[Study.Status.PUBLISHED, Study.Status.FULL],
    )
    form = ReasonForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            unpublish_study(study, request.user, form.cleaned_data['reason'])
        except ValidationError as error:
            form.add_error('reason', error.messages[0])
        else:
            messages.success(request, 'Study paused.')
            return redirect('adminpanel:moderation_detail', study_id=study.pk)
    return render(request, 'adminpanel/confirmation.html', {
        'heading': 'Unpublish study',
        'warning': '',
        'form': form,
        'cancel_url': f'/panel/moderation/{study.pk}/',
        'button_text': 'Unpublish',
    })


@staff_required
def organisations(request):
    form = OrganisationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            organisation = create_organisation(form, request.user)
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, 'Organisation created.')
            return redirect('adminpanel:organisation_detail', organisation_id=organisation.pk)
    organisation_list = Organisation.objects.annotate(
        site_count=Count('sites', distinct=True),
        study_count=Count('studies', distinct=True),
        coordinator_count=Count(
            'staff_profiles__user',
            filter=Q(staff_profiles__user__groups__name='Coordinator'),
            distinct=True,
        ),
    ).order_by('name')
    return render(request, 'adminpanel/organisations.html', {
        'organisations': organisation_list,
        'form': form,
    })


@staff_required
@require_http_methods(['GET', 'POST'])
def organisation_detail(request, organisation_id):
    organisation = get_object_or_404(Organisation, pk=organisation_id)
    form = OrganisationForm(request.POST or None, instance=organisation)
    if request.method == 'POST' and form.is_valid():
        update_organisation(form)
        messages.success(request, 'Organisation changes saved.')
        return redirect('adminpanel:organisation_detail', organisation_id=organisation.pk)
    return render(request, 'adminpanel/organisation_detail.html', {
        'organisation': organisation,
        'form': form,
    })


@staff_required
@require_http_methods(['GET', 'POST'])
def organisation_active_confirmation(request, organisation_id, action):
    organisation = get_object_or_404(Organisation, pk=organisation_id)
    if action not in ('deactivate', 'reactivate'):
        raise Http404
    active = action == 'reactivate'
    if request.method == 'POST':
        set_organisation_active(organisation, active, request.user)
        messages.success(
            request,
            'Organisation reactivated.' if active else 'Organisation deactivated.',
        )
        return redirect('adminpanel:organisation_detail', organisation_id=organisation.pk)
    return render(request, 'adminpanel/confirmation.html', {
        'heading': 'Reactivate organisation' if active else 'Deactivate organisation',
        'warning': (
            '' if active else 'Its live studies will be paused.'
        ),
        'form': None,
        'cancel_url': f'/panel/organisations/{organisation.pk}/',
        'button_text': 'Reactivate' if active else 'Deactivate',
    })


@staff_required
@require_http_methods(['GET', 'POST'])
def organisation_sites(request, organisation_id):
    organisation = get_object_or_404(Organisation, pk=organisation_id)
    form = SiteForm(request.POST or None, organisation=organisation)
    if request.method == 'POST' and form.is_valid():
        site = save_site(form)
        messages.success(request, 'Site added.')
        return redirect('adminpanel:organisation_sites', organisation_id=organisation.pk)
    return render(request, 'adminpanel/organisation_sites.html', {
        'organisation': organisation,
        'sites': organisation.sites.select_related('region').order_by('name'),
        'form': form,
    })


@staff_required
@require_http_methods(['GET', 'POST'])
def site_edit(request, organisation_id, site_id):
    organisation = get_object_or_404(Organisation, pk=organisation_id)
    site = get_object_or_404(Site, pk=site_id, organisation=organisation)
    form = SiteForm(request.POST or None, instance=site, organisation=organisation)
    if request.method == 'POST' and form.is_valid():
        save_site(form)
        messages.success(request, 'Site changes saved.')
        return redirect('adminpanel:organisation_sites', organisation_id=organisation.pk)
    return render(request, 'adminpanel/site_edit.html', {
        'organisation': organisation,
        'site': site,
        'form': form,
    })


@staff_required
@require_http_methods(['GET', 'POST'])
def site_active_confirmation(request, organisation_id, site_id, action):
    organisation = get_object_or_404(Organisation, pk=organisation_id)
    site = get_object_or_404(Site, pk=site_id, organisation=organisation)
    if action not in ('deactivate', 'reactivate'):
        raise Http404
    active = action == 'reactivate'
    if request.method == 'POST':
        try:
            set_record_active(site, active)
        except ValidationError as error:
            messages.error(request, error.messages[0])
            return redirect('adminpanel:organisation_sites', organisation_id=organisation.pk)
        messages.success(request, 'Site reactivated.' if active else 'Site deactivated.')
        return redirect('adminpanel:organisation_sites', organisation_id=organisation.pk)
    return render(request, 'adminpanel/confirmation.html', {
        'heading': 'Reactivate site' if active else 'Deactivate site',
        'warning': '',
        'form': None,
        'cancel_url': f'/panel/organisations/{organisation.pk}/sites/',
        'button_text': 'Reactivate' if active else 'Deactivate',
    })


@staff_required
@require_http_methods(['GET', 'POST'])
def site_delete_confirmation(request, organisation_id, site_id):
    organisation = get_object_or_404(Organisation, pk=organisation_id)
    site = get_object_or_404(Site, pk=site_id, organisation=organisation)
    if request.method == 'POST':
        try:
            delete_unused_record(site)
        except ValidationError as error:
            messages.error(request, error.messages[0])
        else:
            messages.success(request, 'Site deleted.')
        return redirect('adminpanel:organisation_sites', organisation_id=organisation.pk)
    return render(request, 'adminpanel/confirmation.html', {
        'heading': 'Delete site',
        'warning': f'Delete {site.name}?',
        'form': None,
        'cancel_url': f'/panel/organisations/{organisation.pk}/sites/',
        'button_text': 'Delete site',
    })


@staff_required
@require_http_methods(['GET', 'POST'])
def organisation_users(request, organisation_id):
    organisation = get_object_or_404(Organisation, pk=organisation_id)
    coordinators = organisation.staff_profiles.filter(
        user__groups__name='Coordinator'
    ).select_related('user').order_by('user__last_name', 'user__first_name')
    for profile in coordinators:
        profile.account_status = (
            'Active' if profile.user.is_active
            else 'Switched off' if profile.user.last_login
            else 'Waiting for approval'
        )
    form = CoordinatorForm(request.POST or None)
    if request.method == 'POST':
        action = request.POST.get('action', '')
        if action == 'add' and form.is_valid():
            try:
                user = add_coordinator(organisation, form)
            except ValidationError as error:
                form.add_error('temporary_password', error)
            else:
                messages.success(request, 'Coordinator added.')
                return redirect('adminpanel:organisation_users', organisation_id=organisation.pk)
        elif action in ('approve', 'switch_off', 'switch_on'):
            user = get_object_or_404(
                coordinators,
                user_id=request.POST.get('user_id'),
            ).user
            try:
                if action == 'approve':
                    message = approve_researcher(user, request.user)
                    messages.success(request, message)
                else:
                    set_coordinator_active(user, action == 'switch_on')
                    messages.success(
                        request,
                        'Coordinator switched on.' if action == 'switch_on'
                        else 'Coordinator switched off.',
                    )
            except ValidationError as error:
                messages.error(request, error.messages[0])
            return redirect('adminpanel:organisation_users', organisation_id=organisation.pk)
        else:
            return HttpResponseBadRequest('Unknown action.')
    return render(request, 'adminpanel/organisation_users.html', {
        'organisation': organisation,
        'coordinators': coordinators,
        'form': form,
    })


@staff_required
def participants(request):
    query = request.GET.get('q', '')
    paginator = Paginator(search_participants(query), 25)
    page = paginator.get_page(request.GET.get('page'))
    return render(request, 'adminpanel/participants.html', {
        'page_obj': page,
        'query': query,
    })


@staff_required
def participant_detail(request, participant_id):
    participant = get_object_or_404(
        ParticipantProfile.objects.select_related('user', 'region').prefetch_related(
            'conditions',
            'applications__study',
            'applications__payouts',
        ),
        pk=participant_id,
    )
    return render(request, 'adminpanel/participant_detail.html', {
        'participant': participant,
        'applications': participant.applications.select_related(
            'study'
        ).prefetch_related('payouts').order_by('-created_at', '-id'),
        'payouts': Payout.objects.filter(
            application__participant=participant
        ).select_related('application__study').order_by('-created_at', '-id'),
    })


@staff_required
def taxonomy(request):
    return render(request, 'adminpanel/taxonomy.html', {
        'categories': StudyCategory.objects.order_by('display_order', 'name'),
        'conditions': Condition.objects.order_by('name'),
        'category_form': CategoryForm(),
        'condition_form': ConditionForm(),
    })


@staff_required
@require_http_methods(['GET', 'POST'])
def taxonomy_category_save(request, category_id=None):
    category = get_object_or_404(StudyCategory, pk=category_id) if category_id else None
    form = CategoryForm(request.POST or None, instance=category)
    if request.method == 'POST' and form.is_valid():
        save_taxonomy_form(form)
        messages.success(request, 'Category saved.')
        return redirect('adminpanel:taxonomy')
    return render(request, 'adminpanel/taxonomy_edit.html', {
        'heading': 'Edit category' if category else 'Add category',
        'form': form,
        'cancel_url': '/panel/taxonomy/',
    })


@staff_required
@require_http_methods(['GET', 'POST'])
def taxonomy_condition_save(request, condition_id=None):
    condition = get_object_or_404(Condition, pk=condition_id) if condition_id else None
    form = ConditionForm(request.POST or None, instance=condition)
    if request.method == 'POST' and form.is_valid():
        save_taxonomy_form(form)
        messages.success(request, 'Condition saved.')
        return redirect('adminpanel:taxonomy')
    return render(request, 'adminpanel/taxonomy_edit.html', {
        'heading': 'Edit condition' if condition else 'Add condition',
        'form': form,
        'cancel_url': '/panel/taxonomy/',
    })


@staff_required
@require_http_methods(['GET', 'POST'])
def taxonomy_active(request, kind, record_id, action):
    model = {'category': StudyCategory, 'condition': Condition}.get(kind)
    if model is None or action not in ('hide', 'show'):
        raise Http404
    record = get_object_or_404(model, pk=record_id)
    if request.method == 'POST':
        set_record_active(record, action == 'show')
        messages.success(
            request,
            f'{kind.title()} {"shown" if action == "show" else "hidden"}.',
        )
        return redirect('adminpanel:taxonomy')
    return render(request, 'adminpanel/confirmation.html', {
        'heading': f'{"Show" if action == "show" else "Hide"} {kind}',
        'warning': f'{record} will be {"shown" if action == "show" else "hidden"}.',
        'form': None,
        'cancel_url': '/panel/taxonomy/',
        'button_text': 'Show' if action == 'show' else 'Hide',
    })


@staff_required
@require_http_methods(['GET', 'POST'])
def taxonomy_delete(request, kind, record_id):
    model = {'category': StudyCategory, 'condition': Condition}.get(kind)
    if model is None:
        raise Http404
    record = get_object_or_404(model, pk=record_id)
    if request.method == 'POST':
        try:
            delete_unused_record(record)
        except ValidationError as error:
            messages.error(request, error.messages[0])
        else:
            messages.success(request, f'{kind.title()} deleted.')
        return redirect('adminpanel:taxonomy')
    return render(request, 'adminpanel/confirmation.html', {
        'heading': f'Delete {kind}',
        'warning': f'Delete {record}?',
        'form': None,
        'cancel_url': '/panel/taxonomy/',
        'button_text': f'Delete {kind}',
    })


def _model_monitor_card(name, title):
    card = model_card(name)
    card['title'] = title
    card['stats'] = prediction_stats(card.get('model_name', name))
    return card


@staff_required
def ml_monitor(request):
    ml1 = _model_monitor_card('ml1_interest', 'ML-1 Interest')
    ml2 = _model_monitor_card('ml2_screening', 'ML-2 Screening')
    first_picks = ml1_first_pick_counts()
    categories = {
        category.ml_label: category.name
        for category in StudyCategory.objects.all()
    }
    ml1_picks = [
        {'name': categories.get(label, label), 'count': count}
        for label, count in sorted(
            first_picks.items(), key=lambda item: (-item[1], item[0])
        )
    ]
    max_pick = max((item['count'] for item in ml1_picks), default=0)
    for item in ml1_picks:
        item['width'] = item['count'] / max_pick * 100 if max_pick else 0

    band_counts = {
        band: Application.objects.filter(ml2_band=band).count()
        for band in ('high', 'medium', 'low', 'unscored')
    }
    max_band = max(band_counts.values(), default=0)
    bands = [
        {
            'name': Application.Band(band).label,
            'value': band,
            'count': count,
            'width': count / max_band * 100 if max_band else 0,
        }
        for band, count in band_counts.items()
    ]
    overridden, scored, override_percentage = override_rate()
    settings = get_settings()
    recent_predictions = PredictionLog.objects.select_related(
        'participant', 'application'
    ).order_by('-created_at', '-id')[:20]
    return render(request, 'adminpanel/ml_monitor.html', {
        'ml1': ml1,
        'ml2': ml2,
        'model_cards': [ml1, ml2],
        'ml1_picks': ml1_picks,
        'bands': bands,
        'override_count': overridden,
        'scored_count': scored,
        'override_percentage': override_percentage,
        'pass_rates': band_pass_rates(Application.objects.all()),
        'settings': settings,
        'recent_predictions': recent_predictions,
    })


@admin_required
@require_http_methods(['GET', 'POST'])
def ml_settings(request):
    settings = get_settings()
    form = ThresholdForm(
        request.POST or None,
        initial={
            'high': settings.ml2_high_threshold,
            'medium': settings.ml2_medium_threshold,
        },
    )
    if request.method == 'POST' and form.is_valid():
        try:
            update_thresholds(
                form.cleaned_data['high'],
                form.cleaned_data['medium'],
                request.user,
            )
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, 'Thresholds saved.')
            return redirect('adminpanel:ml_monitor')
    return render(request, 'adminpanel/ml_settings.html', {
        'form': form,
        'settings': settings,
    })


@admin_required
@require_http_methods(['GET', 'POST'])
def staff_accounts(request):
    users = User.objects.filter(
        groups__name__in=['Staff', 'Admin'],
    ).distinct().select_related('staff_profile').order_by(
        'first_name', 'last_name', 'username'
    )
    form = StaffAccountForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            add_staff_account(form, request.user)
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, 'Staff account created.')
            return redirect('adminpanel:staff_accounts')
    return render(request, 'adminpanel/staff_accounts.html', {
        'staff_users': users,
        'form': form,
    })


@admin_required
@require_http_methods(['POST'])
def staff_account_action(request, user_id, action):
    target = get_object_or_404(
        User.objects.filter(groups__name__in=['Staff', 'Admin']).distinct(),
        pk=user_id,
    )
    try:
        if action in ('admin', 'staff'):
            set_staff_role(target, action, request.user)
            message = 'Account is now an admin.' if action == 'admin' else 'Account is now staff.'
        elif action in ('on', 'off'):
            set_staff_active(target, action == 'on', request.user)
            message = 'Account switched on.' if action == 'on' else 'Account switched off.'
        else:
            raise Http404
    except ValidationError as error:
        messages.error(request, error.messages[0])
    else:
        messages.success(request, message)
    return redirect('adminpanel:staff_accounts')


@admin_required
@require_http_methods(['GET', 'POST'])
def demo_data(request):
    output = request.session.pop('demo_seed_output', '')
    if request.method == 'POST':
        buffer = StringIO()
        call_command('seed_demo', stdout=buffer)
        login(
            request,
            User.objects.get(pk=request.user.pk),
            backend='django.contrib.auth.backends.ModelBackend',
        )
        request.session['demo_seed_output'] = buffer.getvalue()
        messages.success(request, 'Demo data loaded.')
        return redirect('adminpanel:demo_data')
    return render(request, 'adminpanel/demo_data.html', {'output': output})
