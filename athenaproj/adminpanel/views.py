from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.views import LogoutView
from django.core.exceptions import ValidationError
from django.http import Http404, HttpResponseBadRequest, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from core.models import Application, Appointment, Payout, Study
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
    create_pre_screen_question,
    create_study,
    delete_pre_screen_question,
    enrol_applicant,
    enrolled_count,
    earned_amount,
    get_panel_application,
    get_panel_study,
    get_settings,
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
    run_compliance_checks,
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

from .decorators import coordinator_required
from .forms import (
    ApplicantFilterForm,
    CoordinatorWithdrawForm,
    NotSelectedForm,
    OverrideBandForm,
    ParticipationFilterForm,
    PreScreenQuestionForm,
    ScreeningOutcomeForm,
    ScreeningScheduleForm,
    StudyForm,
    VisitDateForm,
)


def dashboard(request):
    role = user_role(request.user)
    if role == 'coordinator':
        dashboard_data = coordinator_dashboard(request.user)
        if dashboard_data:
            return render(request, 'adminpanel/dashboard_coordinator.html', dashboard_data)
        else:
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


@coordinator_required
def participation(request):
    org = request.user.staff_profile.organisation
    applications_qs = Application.objects.filter(
        study__organisation=org,
        status__in=[Application.Status.ENROLLED, Application.Status.COMPLETED],
    ).select_related('participant__user', 'study').order_by('-created_at')

    form = ParticipationFilterForm(request.GET or None, organisation=org)
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


@coordinator_required
def participation_detail(request, application_id):
    application = get_object_or_404(
        Application.objects.select_related('participant__user', 'study__organisation'),
        pk=application_id,
        study__organisation=request.user.staff_profile.organisation,
    )

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


@coordinator_required
def participation_withdraw(request, application_id):
    application = get_object_or_404(
        Application.objects.select_related('study__organisation'),
        pk=application_id,
        study__organisation=request.user.staff_profile.organisation,
    )

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


@coordinator_required
def insights(request):
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
