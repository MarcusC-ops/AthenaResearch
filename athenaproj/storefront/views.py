from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.http import Http404
from django.contrib import messages
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.models import Appointment, Application, Review, Study
from core.redirects import safe_next_url
from core.services import (
    OPEN_STATUSES,
    PARTICIPANT_STATUS_LABELS,
    InvalidStatusMove,
    NotEligible,
    alternatives_for,
    approved_reviews,
    category_tiles,
    check_eligibility,
    confirm_appointment as confirm_application_appointment,
    create_support_request,
    get_public_study,
    get_my_application,
    is_eligible,
    my_applications,
    popular_studies,
    payouts_summary,
    search_studies,
    for_you_feed,
    personal_row,
    profile_ready,
    refresh_interest_predictions,
    save_review,
    save_profile,
    timeline,
    what_happens_next,
    withdraw_application,
    add_to_shortlist,
    compare_studies,
    remove_from_shortlist,
    shortlist_for,
    submit_application,
)

from .forms import (
    ApplyQuestionsForm,
    ProfileForm,
    ReviewForm,
    StudyFilterForm,
    SupportRequestForm,
    WithdrawalForm,
)
from .decorators import participant_required


def home(request):
    personal_items = []
    if (
        request.user.is_authenticated
        and hasattr(request.user, 'participant_profile')
        and profile_ready(request.user.participant_profile)
    ):
        personal_items = personal_row(request.user.participant_profile)
    return render(
        request,
        'storefront/home.html',
        {
            'category_tiles': category_tiles(),
            'popular_studies': popular_studies(),
            'personal_items': personal_items,
        },
    )


def studies(request):
    form = StudyFilterForm(request.GET)
    form.is_valid()
    cleaned = form.cleaned_data
    queryset = search_studies(
        q=cleaned.get('q', ''),
        category=cleaned.get('category', ''),
        types=cleaned.get('type'),
        region=cleaned.get('region', ''),
        duration=cleaned.get('duration', ''),
        hv=cleaned.get('hv', False),
        comp=cleaned.get('comp', ''),
        sort=cleaned.get('sort') or 'newest',
    )
    page_obj = Paginator(queryset, 12).get_page(request.GET.get('page'))
    return render(
        request,
        'storefront/studies.html',
        {'form': form, 'page_obj': page_obj, 'result_count': queryset.count()},
    )


def study_detail(request, slug):
    try:
        study = get_public_study(slug)
    except Study.DoesNotExist:
        raise Http404
    is_shortlisted = (
        request.user.is_authenticated
        and hasattr(request.user, 'participant_profile')
        and study.shortlists.filter(
            participant=request.user.participant_profile
        ).exists()
    )
    application = None
    apply_step = None
    if request.user.is_authenticated and hasattr(request.user, 'participant_profile'):
        application = Application.objects.filter(
            participant=request.user.participant_profile,
            study=study,
        ).first()
        if application:
            apply_step = 'application'
        else:
            session_data = request.session.get(_apply_session_key(study.pk), {})
            if session_data.get('passed_step1'):
                apply_step = 'step3' if session_data.get('answers') else 'step2'
            else:
                apply_step = 'step1'
    return render(
        request,
        'storefront/study_detail.html',
        {
            'study': study,
            'is_shortlisted': is_shortlisted,
            'application': application,
            'apply_step': apply_step,
            'approved_reviews': approved_reviews(study),
        },
    )


def _safe_next(request, fallback):
    return safe_next_url(request, request.POST.get('next', ''), fallback)


def _public_study_or_404(slug):
    try:
        return get_public_study(slug)
    except Study.DoesNotExist:
        raise Http404


def _apply_session_key(study_id):
    return f'apply_{study_id}'


def _redirect_if_application_exists(request, study):
    if not request.user.is_authenticated:
        return None
    application = Application.objects.filter(
        participant=request.user.participant_profile,
        study=study,
    ).first()
    if application:
        return redirect(f'/applications/{application.pk}/')
    return None


def _availability_label(value):
    try:
        return Application.Availability(value).label
    except ValueError:
        return ''


def _require_profile_ready(request):
    profile = request.user.participant_profile
    if not profile_ready(profile):
        messages.info(request, 'Complete your profile first.')
        return redirect('/onboarding/')
    return None


@participant_required
def apply_step1(request, slug):
    study = _public_study_or_404(slug)
    existing = _redirect_if_application_exists(request, study)
    if existing:
        return existing
    profile_ready_redirect = _require_profile_ready(request)
    if profile_ready_redirect:
        return profile_ready_redirect

    key = _apply_session_key(study.pk)
    session_data = request.session.get(key, {})
    eligible = is_eligible(request.user.participant_profile, study)
    next_data = {
        'passed_step1': eligible,
        'answers': session_data.get('answers', {}) if eligible else {},
        'preferred_site': session_data.get('preferred_site'),
        'availability': session_data.get('availability'),
    }
    request.session[key] = next_data
    rules = check_eligibility(request.user.participant_profile, study)
    return render(
        request,
        'storefront/apply_step1.html',
        {
            'study': study,
            'eligible': eligible,
            'rules': rules,
            'alternatives': alternatives_for(request.user.participant_profile, study, limit=3)
            if not eligible else [],
            'session_data': next_data,
        },
    )


@participant_required
def apply_step2(request, slug):
    study = _public_study_or_404(slug)
    existing = _redirect_if_application_exists(request, study)
    if existing:
        return existing
    profile_ready_redirect = _require_profile_ready(request)
    if profile_ready_redirect:
        return profile_ready_redirect

    key = _apply_session_key(study.pk)
    session_data = request.session.get(key, {})
    if not session_data.get('passed_step1'):
        return redirect('storefront:apply_step1', slug=study.slug)

    form = ApplyQuestionsForm(
        study,
        request.POST or None,
        initial={
            **{
                f'question_{question.pk}': session_data.get('answers', {}).get(str(question.pk))
                for question in study.pre_screen_questions.all()
            },
            'preferred_site': session_data.get('preferred_site'),
            'availability': session_data.get('availability'),
        },
    )
    if request.method == 'POST' and form.is_valid():
        answers = {
            int(field_name.split('_', 1)[1]): value
            for field_name, value in form.cleaned_data.items()
            if field_name.startswith('question_')
        }
        next_data = {
            'passed_step1': True,
            'answers': answers,
            'preferred_site': form.cleaned_data['preferred_site'].pk,
            'availability': form.cleaned_data['availability'],
        }
        request.session[key] = next_data
        return redirect('storefront:apply_step3', slug=study.slug)
    return render(request, 'storefront/apply_step2.html', {'study': study, 'form': form})


@participant_required
def apply_step3(request, slug):
    study = _public_study_or_404(slug)
    existing = _redirect_if_application_exists(request, study)
    if existing:
        return existing
    profile_ready_redirect = _require_profile_ready(request)
    if profile_ready_redirect:
        return profile_ready_redirect

    key = _apply_session_key(study.pk)
    session_data = request.session.get(key, {})
    if not session_data.get('passed_step1'):
        return redirect('storefront:apply_step1', slug=study.slug)
    if not session_data.get('answers'):
        return redirect('storefront:apply_step2', slug=study.slug)

    preferred_site = study.sites.filter(pk=session_data.get('preferred_site')).first()
    answers = session_data.get('answers', {})
    question_answers = [
        {
            'question': question,
            'answer': answers.get(question.pk, answers.get(str(question.pk), '')),
        }
        for question in study.pre_screen_questions.all()
    ]
    if request.method == 'POST':
        consent = request.POST.get('consent') == 'on'
        try:
            application, _ = submit_application(
                request.user.participant_profile,
                study,
                answers,
                session_data.get('preferred_site'),
                session_data.get('availability'),
                consent,
            )
        except ValidationError as exc:
            return render(
                request,
                'storefront/apply_step3.html',
                {
                    'study': study,
                    'answers': question_answers,
                    'preferred_site': preferred_site,
                    'availability': _availability_label(session_data.get('availability')),
                    'error_message': ' '.join(exc.messages),
                },
            )
        except NotEligible:
            session_data['passed_step1'] = False
            request.session[key] = session_data
            return redirect('storefront:apply_step1', slug=study.slug)

        request.session.pop(key, None)
        return redirect('storefront:application_submitted', application_id=application.pk)

    return render(
        request,
        'storefront/apply_step3.html',
        {
            'study': study,
            'answers': question_answers,
            'preferred_site': preferred_site,
            'availability': _availability_label(session_data.get('availability')),
        },
    )


@participant_required
def application_detail(request, application_id):
    profile = request.user.participant_profile
    try:
        application = get_my_application(profile, application_id)
    except Application.DoesNotExist:
        raise Http404
    appointments = application.appointments.select_related('site').order_by('scheduled_for', 'id')
    screening_appointment = appointments.filter(kind=Appointment.Kind.SCREENING).first()
    visits = list(appointments.filter(kind=Appointment.Kind.VISIT))
    attended_visits = sum(
        visit.status == Appointment.Status.ATTENDED for visit in visits
    )
    payouts, total_paid = payouts_summary(application)
    review = application.study.reviews.filter(participant=profile).first()
    support_requests = application.support_requests.select_related(
        'replied_by'
    ).order_by('-created_at', '-id')
    alternatives = []
    if application.status in (
        Application.Status.AUTO_DECLINED,
        Application.Status.NOT_SELECTED,
        Application.Status.SCREENING_FAILED,
    ):
        alternatives = alternatives_for(profile, application.study, limit=3)
    return render(
        request,
        'storefront/application_detail.html',
        {
            'application': application,
            'timeline': timeline(application),
            'screening_appointment': screening_appointment,
            'visits': visits,
            'attended_visits': attended_visits,
            'visit_percentage': (
                round(attended_visits * 100 / application.study.total_visits)
                if application.study.total_visits else 0
            ),
            'payouts': payouts,
            'total_paid': total_paid,
            'review': review,
            'support_requests': support_requests,
            'what_happens_next': what_happens_next(application),
            'alternatives': alternatives,
            'is_open': application.status in OPEN_STATUSES,
            'status_label': PARTICIPANT_STATUS_LABELS[application.status],
            'now': timezone.now(),
        },
    )


@participant_required
def applications(request):
    open_applications, finished_applications = my_applications(
        request.user.participant_profile
    )
    return render(
        request,
        'storefront/applications.html',
        {
            'open_applications': open_applications,
            'finished_applications': finished_applications,
        },
    )


@participant_required
def withdraw_application_view(request, application_id):
    try:
        application = get_my_application(
            request.user.participant_profile, application_id
        )
    except Application.DoesNotExist:
        raise Http404
    if application.status not in OPEN_STATUSES:
        return render(
            request,
            'storefront/withdraw_application.html',
            {'application': application, 'closed': True},
        )
    form = WithdrawalForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            withdraw_application(
                request.user.participant_profile,
                application,
                form.cleaned_data['reason'],
            )
        except InvalidStatusMove:
            messages.error(request, 'This application is already closed.')
            return redirect('storefront:application_detail', application_id=application.pk)
        messages.success(request, 'You have withdrawn from this study.')
        return redirect('storefront:application_detail', application_id=application.pk)
    return render(
        request,
        'storefront/withdraw_application.html',
        {'application': application, 'form': form},
    )


@participant_required
def review_application(request, application_id):
    try:
        application = get_my_application(
            request.user.participant_profile, application_id
        )
    except Application.DoesNotExist:
        raise Http404
    review = application.study.reviews.filter(
        participant=request.user.participant_profile
    ).first()
    if application.status != Application.Status.COMPLETED:
        messages.error(request, 'You can review a study after you complete it.')
        return redirect('storefront:application_detail', application_id=application.pk)
    if review and review.status != Review.Status.PENDING:
        messages.error(
            request,
            'This review has already been checked and cannot be changed.',
        )
        return redirect('storefront:application_detail', application_id=application.pk)
    form = ReviewForm(
        request.POST or None,
        initial={
            'rating': review.rating if review else None,
            'comment': review.comment if review else '',
        },
    )
    if request.method == 'POST' and form.is_valid():
        try:
            save_review(
                request.user.participant_profile,
                application.study,
                int(form.cleaned_data['rating']),
                form.cleaned_data['comment'],
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, 'Your review has been sent for approval.')
            return redirect('storefront:application_detail', application_id=application.pk)
    return render(
        request,
        'storefront/review_application.html',
        {'application': application, 'form': form},
    )


@participant_required
def contact_application(request, application_id):
    try:
        application = get_my_application(
            request.user.participant_profile, application_id
        )
    except Application.DoesNotExist:
        raise Http404
    form = SupportRequestForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        create_support_request(
            application,
            form.cleaned_data['topic'],
            form.cleaned_data['question'],
        )
        messages.success(request, 'Your question has been sent.')
        return redirect('storefront:application_detail', application_id=application.pk)
    return render(
        request,
        'storefront/contact_application.html',
        {'application': application, 'form': form},
    )


@require_POST
@participant_required
def confirm_appointment(request, application_id, appointment_id):
    try:
        application = get_my_application(
            request.user.participant_profile, application_id
        )
    except Application.DoesNotExist:
        raise Http404
    if not application.appointments.filter(pk=appointment_id).exists():
        raise Http404
    try:
        confirm_application_appointment(
            request.user.participant_profile, appointment_id
        )
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
    else:
        messages.success(request, 'Appointment confirmed.')
    return redirect('storefront:application_detail', application_id=application.pk)


@participant_required
def application_submitted(request, application_id):
    profile = request.user.participant_profile
    try:
        application = get_my_application(profile, application_id)
    except Application.DoesNotExist:
        raise Http404
    alternatives = alternatives_for(profile, application.study, limit=3)
    return render(
        request,
        'storefront/application_submitted.html',
        {
            'application': application,
            'alternatives': alternatives,
        },
    )


@participant_required
def shortlist(request):
    profile = request.user.participant_profile
    return render(request, 'storefront/shortlist.html', {
        'studies': shortlist_for(profile),
    })


@require_POST
@participant_required
def shortlist_add(request, study_id):
    study = Study.objects.filter(pk=study_id).first()
    fallback = (
        reverse('storefront:study_detail', kwargs={'slug': study.slug})
        if study is not None else '/shortlist/'
    )
    try:
        _, created = add_to_shortlist(request.user.participant_profile, study_id)
    except Study.DoesNotExist:
        return redirect(_safe_next(request, fallback))
    messages.success(
        request,
        'Saved to your shortlist.' if created else 'Already on your shortlist.',
    )
    return redirect(_safe_next(request, fallback))


@require_POST
@participant_required
def shortlist_remove(request, study_id):
    remove_from_shortlist(request.user.participant_profile, study_id)
    messages.success(request, 'Removed from your shortlist.')
    study = Study.objects.filter(pk=study_id).first()
    fallback = (
        reverse('storefront:study_detail', kwargs={'slug': study.slug})
        if study is not None else '/shortlist/'
    )
    return redirect(_safe_next(request, fallback))


@participant_required
def shortlist_compare(request):
    try:
        studies = compare_studies(
            request.user.participant_profile,
            request.GET.getlist('ids'),
        )
    except ValueError:
        messages.error(
            request,
            'Choose two or three studies from your shortlist to compare',
        )
        return redirect('/shortlist/')
    return render(request, 'storefront/compare.html', {'studies': studies})


def support(request):
    faq_items = [
        (
            'Who can take part in a study?',
            'Each study has its own eligibility rules, such as age, health and visit requirements. Read the study page carefully before deciding whether it suits you.',
        ),
        (
            'Do I have to pay anything?',
            'No. You do not pay to take part in an Athena study. Any costs and support are explained on the study page.',
        ),
        (
            'How do I apply?',
            'Choose a study and select Check if I can apply. You will sign in or create an account, then answer the study questions.',
        ),
        (
            'What happens after I apply?',
            'The research team reviews your answers against the study requirements. They will contact you with the next steps if you may be eligible.',
        ),
        (
            'Can I withdraw?',
            'Yes. You can withdraw from a study at any time. Tell the research team as soon as possible so they can explain what happens next.',
        ),
        (
            'How does compensation work?',
            'Some studies provide compensation for your time and travel. Where the amount is approved for display, it is shown on the study page.',
        ),
        (
            'How is my health information used?',
            'Your information is used to check eligibility and run the study. The research team explains how it is protected and used in the study information.',
        ),
        (
            'Who runs the studies on Athena?',
            'Studies are run by partner hospitals, universities, research institutes, sponsors and clinical research organisations. The organisation is named on each study page.',
        ),
    ]
    return render(request, 'storefront/support.html', {'faq_items': faq_items})


@participant_required
def onboarding(request):
    profile = request.user.participant_profile
    form = ProfileForm(request.POST or None, instance=profile)
    if request.method == 'POST' and form.is_valid():
        was_ready = profile_ready(profile)
        save_profile(profile, form)
        refresh_interest_predictions(profile)
        messages.success(
            request, 'Your profile is updated.' if was_ready else 'Your profile is saved.'
        )
        return redirect('/for-you/' if not was_ready else '/account/')
    return render(request, 'storefront/onboarding.html', {
        'form': form, 'editing': profile.onboarding_completed_at is not None,
    })


@participant_required
def for_you(request):
    profile = request.user.participant_profile
    if not profile_ready(profile):
        messages.info(request, 'Complete your profile first.')
        return redirect('/onboarding/')
    return render(request, 'storefront/for_you.html', for_you_feed(profile))
