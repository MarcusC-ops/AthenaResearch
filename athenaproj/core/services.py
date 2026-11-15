"""All Athena business logic lives here. Views call these functions."""

from dataclasses import dataclass
from datetime import timedelta
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
import re
from django.contrib.auth.models import Group, User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Avg, Case, Count, Q, Sum, Value, When
from django.db.models.deletion import ProtectedError, RestrictedError
from django.utils import timezone

from .models import (
    AppSetting,
    Appointment,
    Application,
    ApplicationAnswer,
    ApplicationStatusEvent,
    Condition,
    Notification,
    Organisation,
    ParticipantProfile,
    Payout,
    PreScreenQuestion,
    PredictionLog,
    Region,
    Review,
    Shortlist,
    StaffProfile,
    Study,
    StudyCategory,
    SupportRequest,
)
from .validators import normalise_sg_mobile


ALLOWED_MOVES = {
    Application.Status.SUBMITTED: {
        Application.Status.AUTO_DECLINED,
        Application.Status.UNDER_REVIEW,
        Application.Status.WAITLISTED,
        Application.Status.SHORTLISTED,
        Application.Status.WITHDRAWN,
    },
    Application.Status.UNDER_REVIEW: {
        Application.Status.SHORTLISTED,
        Application.Status.NOT_SELECTED,
        Application.Status.WITHDRAWN,
    },
    Application.Status.WAITLISTED: {
        Application.Status.UNDER_REVIEW,
        Application.Status.NOT_SELECTED,
        Application.Status.WITHDRAWN,
    },
    Application.Status.SHORTLISTED: {
        Application.Status.SCREENING_SCHEDULED,
        Application.Status.NOT_SELECTED,
        Application.Status.WITHDRAWN,
    },
    Application.Status.SCREENING_SCHEDULED: {
        Application.Status.SCREENING_PASSED,
        Application.Status.SCREENING_FAILED,
        Application.Status.WITHDRAWN,
    },
    Application.Status.SCREENING_PASSED: {
        Application.Status.ENROLLED,
        Application.Status.WAITLISTED,
        Application.Status.NOT_SELECTED,
        Application.Status.WITHDRAWN,
    },
    Application.Status.ENROLLED: {
        Application.Status.COMPLETED,
        Application.Status.WITHDRAWN,
    },
    Application.Status.AUTO_DECLINED: set(),
    Application.Status.NOT_SELECTED: set(),
    Application.Status.SCREENING_FAILED: set(),
    Application.Status.COMPLETED: set(),
    Application.Status.WITHDRAWN: set(),
}
FINAL_STATUSES = {
    status for status, moves in ALLOWED_MOVES.items() if not moves
}
OPEN_STATUSES = set(ALLOWED_MOVES) - FINAL_STATUSES


class InvalidStatusMove(Exception):
    pass


class NotEligible(Exception):
    pass


class StudyFull(InvalidStatusMove):
    pass


def list_regions():
    return Region.objects.order_by('display_order')


def list_active_categories():
    return StudyCategory.objects.filter(is_active=True).order_by('display_order')


def list_active_conditions():
    return Condition.objects.filter(is_active=True).order_by('name')


def _with_review_ratings(studies):
    return studies.annotate(
        review_average=Avg(
            'reviews__rating',
            filter=Q(reviews__status=Review.Status.APPROVED),
        ),
        review_count=Count(
            'reviews',
            filter=Q(reviews__status=Review.Status.APPROVED),
            distinct=True,
        ),
    )


def public_studies():
    return _with_review_ratings(
        Study.objects.filter(
            status__in=[Study.Status.PUBLISHED, Study.Status.FULL]
        )
    ).order_by('-published_at', '-id')


def get_public_study(slug):
    return public_studies().get(slug=slug)


def get_study(study_id):
    return Study.objects.get(pk=study_id)


def _panel_study_queryset(user):
    role = user_role(user)
    if role == 'coordinator':
        organisation_id = getattr(
            getattr(user, 'staff_profile', None), 'organisation_id', None
        )
        return Study.objects.filter(organisation_id=organisation_id)
    if role in ('staff', 'admin'):
        return Study.objects.all()
    return Study.objects.none()


def panel_studies(user, status=''):
    studies = _panel_study_queryset(user).select_related(
        'organisation', 'category'
    ).annotate(
        panel_application_count=Count('applications', distinct=True),
        panel_enrolled_count=Count(
            'applications',
            filter=Q(applications__status__in=[
                Application.Status.ENROLLED,
                Application.Status.COMPLETED,
            ]),
            distinct=True,
        ),
    ).order_by('-updated_at', '-id')
    if status:
        studies = studies.filter(status=status)
    return studies


def get_panel_study(user, study_id):
    try:
        return _panel_study_queryset(user).select_related(
            'organisation', 'category'
        ).prefetch_related(
            'sites__region', 'regions', 'required_conditions',
            'excluded_conditions', 'pre_screen_questions',
        ).annotate(
            panel_enrolled_count=Count(
                'applications',
                filter=Q(applications__status__in=[
                    Application.Status.ENROLLED,
                    Application.Status.COMPLETED,
                ]),
                distinct=True,
            ),
        ).get(pk=study_id)
    except Study.DoesNotExist:
        raise Study.DoesNotExist


def _coordinator_organisation(user):
    if user_role(user) != 'coordinator':
        raise Study.DoesNotExist
    try:
        organisation = user.staff_profile.organisation
    except StaffProfile.DoesNotExist:
        raise Study.DoesNotExist
    if organisation is None:
        raise Study.DoesNotExist
    return organisation


def _editable_study(study):
    if study.status not in (
        Study.Status.DRAFT,
        Study.Status.CHANGES_REQUESTED,
    ):
        raise ValidationError('Only draft or returned listings can be edited.')


@transaction.atomic
def create_study(form, user):
    organisation = _coordinator_organisation(user)
    study = form.save(commit=False)
    study.organisation = organisation
    study.status = Study.Status.DRAFT
    study.created_by = user
    study.last_edited_by = user
    study.save()
    form.save_m2m()
    return study


@transaction.atomic
def update_study(form, user):
    visible_study = get_panel_study(user, form.instance.pk)
    if user_role(user) != 'coordinator':
        raise Study.DoesNotExist
    _editable_study(visible_study)
    study = form.save(commit=False)
    study.last_edited_by = user
    study.save()
    form.save_m2m()
    return study


@dataclass(frozen=True)
class CheckResult:
    code: str
    label: str
    passed: bool
    detail: str = ''


PAYMENT_LED_WORDING = re.compile(
    r'\b(?:earn|free|fast\s+cash|easy\s+money|guaranteed)\b',
    re.IGNORECASE,
)


def run_compliance_checks(study):
    wording = ' '.join((study.title or '', study.description or '', study.visit_plan or ''))
    matches = []
    for match in PAYMENT_LED_WORDING.finditer(wording):
        phrase = ' '.join(match.group(0).lower().split())
        matches.append(phrase)

    eligibility_failures = []
    if study.min_age is None or study.max_age is None or study.min_age > study.max_age:
        eligibility_failures.append('Age limits are not in order.')
    if (
        study.min_bmi is not None
        and study.max_bmi is not None
        and study.min_bmi > study.max_bmi
    ):
        eligibility_failures.append('BMI limits are not in order.')
    if not study.sites.exists():
        eligibility_failures.append('Choose at least one site.')
    if (
        study.start_date is None
        or study.recruitment_deadline is None
        or study.recruitment_deadline <= study.start_date
    ):
        eligibility_failures.append(
            'The recruitment deadline must be after the start date.'
        )
    if (
        study.recruitment_deadline is not None
        and study.recruitment_deadline < timezone.localdate()
    ):
        eligibility_failures.append('The recruitment deadline must not be in the past.')

    return [
        CheckResult(
            'irb_reference',
            'IRB name and reference present',
            bool(study.irb_name.strip() and study.irb_reference.strip()),
            '' if study.irb_name.strip() and study.irb_reference.strip()
            else 'Enter the IRB name and reference.',
        ),
        CheckResult(
            'irb_expiry',
            'IRB approval valid past the recruitment deadline',
            bool(
                study.irb_expiry
                and study.recruitment_deadline
                and study.irb_expiry > study.recruitment_deadline
            ),
            '' if (
                study.irb_expiry
                and study.recruitment_deadline
                and study.irb_expiry > study.recruitment_deadline
            ) else 'IRB approval must expire after the recruitment deadline.',
        ),
        CheckResult(
            'irb_text',
            'Listing text approved by the IRB',
            study.irb_approved_text,
            '' if study.irb_approved_text else 'Confirm the listing text is IRB-approved.',
        ),
        CheckResult(
            'wording',
            'No payment-led wording',
            not matches,
            '' if not matches else f"Found: {', '.join(matches)}.",
        ),
        CheckResult(
            'compensation',
            'Compensation display consistent with IRB approval',
            (
                not study.show_compensation
                or (
                    study.compensation_amount is not None
                    and study.compensation_amount > 0
                    and study.irb_approved_text
                )
            ),
            '' if (
                not study.show_compensation
                or (
                    study.compensation_amount is not None
                    and study.compensation_amount > 0
                    and study.irb_approved_text
                )
            ) else 'Showing compensation requires a positive amount and IRB-approved text.',
        ),
        CheckResult(
            'eligibility',
            'Eligibility ranges make sense and at least one site',
            not eligibility_failures,
            '; '.join(eligibility_failures),
        ),
        CheckResult(
            'questions',
            'Pre-screen questions added',
            study.pre_screen_questions.exists(),
            '' if study.pre_screen_questions.exists()
            else 'Add at least one pre-screen question.',
        ),
    ]


def _editable_question_study(study):
    _editable_study(study)


@transaction.atomic
def create_pre_screen_question(study, form):
    _editable_question_study(study)
    question = form.save(commit=False)
    question.study = study
    question.save()
    return question


@transaction.atomic
def update_pre_screen_question(study, question, form):
    _editable_question_study(study)
    if question.study_id != study.pk:
        raise PreScreenQuestion.DoesNotExist
    updated = form.save(commit=False)
    updated.study = study
    updated.save()
    return updated


@transaction.atomic
def delete_pre_screen_question(study, question_id):
    _editable_question_study(study)
    question = study.pre_screen_questions.get(pk=question_id)
    try:
        question.delete()
    except (ProtectedError, RestrictedError) as error:
        raise ValidationError(
            'This question has answers, so it cannot be deleted.'
        ) from error


@transaction.atomic
def submit_study_for_review(study, user):
    organisation = _coordinator_organisation(user)
    study = get_panel_study(user, study.pk)
    if study.organisation_id != organisation.pk:
        raise Study.DoesNotExist
    _editable_study(study)
    if not all(check.passed for check in run_compliance_checks(study)):
        raise ValidationError('Fix the failed checks before you submit.')
    study.status = Study.Status.PENDING_REVIEW
    study.submitted_at = timezone.now()
    study.save(update_fields=['status', 'submitted_at', 'updated_at'])
    notify_staff(
        f'{study.organisation.name} submitted {study.title} for review.',
        f'/panel/moderation/{study.pk}/',
    )
    return study


@transaction.atomic
def set_auto_shortlist(study, on, user):
    visible_study = get_panel_study(user, study.pk)
    if visible_study.status not in (
        Study.Status.PUBLISHED,
        Study.Status.FULL,
        Study.Status.PAUSED,
    ):
        raise ValidationError(
            'Auto-shortlist can only be changed on published, full or paused listings.'
        )
    visible_study.auto_shortlist_high = bool(on)
    visible_study.save(update_fields=['auto_shortlist_high', 'updated_at'])
    return visible_study


def add_to_shortlist(profile, study_id):
    study = public_studies().get(pk=study_id)
    shortlist, created = Shortlist.objects.get_or_create(
        participant=profile,
        study=study,
    )
    return shortlist, created


def remove_from_shortlist(profile, study_id):
    deleted, _ = Shortlist.objects.filter(
        participant=profile,
        study_id=study_id,
    ).delete()
    return deleted > 0


def shortlist_for(profile):
    shortlists = (
        Shortlist.objects.filter(
            participant=profile,
            study__status__in=[Study.Status.PUBLISHED, Study.Status.FULL],
        )
        .annotate(
            study_review_average=Avg(
                'study__reviews__rating',
                filter=Q(study__reviews__status=Review.Status.APPROVED),
            ),
            study_review_count=Count(
                'study__reviews',
                filter=Q(study__reviews__status=Review.Status.APPROVED),
                distinct=True,
            ),
        )
        .select_related('study', 'study__category', 'study__organisation')
        .prefetch_related(
            'study__sites__region',
            'study__required_conditions',
            'study__excluded_conditions',
            'study__regions',
        )
        .order_by('-created_at', '-id')
    )
    studies = []
    for shortlist in shortlists:
        study = shortlist.study
        study.review_average = shortlist.study_review_average
        study.review_count = shortlist.study_review_count
        study.is_eligible = is_eligible(profile, study)
        studies.append(study)
    return studies


def shortlist_count(profile):
    return Shortlist.objects.filter(
        participant=profile,
        study__status__in=[Study.Status.PUBLISHED, Study.Status.FULL],
    ).count()


def compare_studies(profile, ids):
    study_ids = [str(study_id) for study_id in ids]
    if len(study_ids) not in (2, 3) or len(set(study_ids)) != len(study_ids):
        raise ValueError('Choose two or three studies from your shortlist to compare')
    shortlisted_ids = set(
        Shortlist.objects.filter(
            participant=profile,
            study__status__in=[Study.Status.PUBLISHED, Study.Status.FULL],
            study_id__in=study_ids,
        ).values_list('study_id', flat=True)
    )
    if shortlisted_ids != {int(study_id) for study_id in study_ids}:
        raise ValueError('Choose two or three studies from your shortlist to compare')
    studies_by_id = Study.objects.filter(
        pk__in=study_ids,
        status__in=[Study.Status.PUBLISHED, Study.Status.FULL],
    ).select_related('category', 'organisation').prefetch_related(
        'sites__region',
        'required_conditions',
        'excluded_conditions',
        'regions',
    )
    studies_by_id = _with_review_ratings(studies_by_id)
    studies = {str(study.pk): study for study in studies_by_id}
    return [studies[study_id] for study_id in study_ids]


def search_studies(
    q='',
    category='',
    types=None,
    region='',
    duration='',
    hv=False,
    comp='',
    sort='newest',
):
    """Return public studies matching the supplied catalogue filters."""
    studies = public_studies().select_related(
        'category', 'organisation'
    ).prefetch_related('sites__region', 'required_conditions', 'excluded_conditions')
    if q:
        studies = studies.filter(
            Q(title__icontains=q)
            | Q(description__icontains=q)
            | Q(category__name__icontains=q)
            | Q(required_conditions__name__icontains=q)
        ).distinct()
    if category:
        studies = studies.filter(category__slug=category)
    if types:
        studies = studies.filter(study_type__in=types)
    if region:
        studies = studies.filter(sites__region__code=region)
    if duration == 'short':
        studies = studies.filter(duration_weeks__lte=4)
    elif duration == 'medium':
        studies = studies.filter(duration_weeks__gte=5, duration_weeks__lte=13)
    elif duration == 'long':
        studies = studies.filter(duration_weeks__gte=14)
    if hv:
        studies = studies.filter(accepts_healthy_volunteers=True)
    if comp == 'shown':
        studies = studies.filter(show_compensation=True)
    elif comp == '100':
        studies = studies.filter(show_compensation=True, compensation_amount__gte=100)
    elif comp == '300':
        studies = studies.filter(show_compensation=True, compensation_amount__gte=300)

    if sort == 'deadline':
        studies = studies.order_by('recruitment_deadline', '-id')
    elif sort == 'compensation':
        studies = studies.annotate(
            hidden_compensation=Case(
                When(show_compensation=False, then=Value(1)),
                default=Value(0),
            )
        ).order_by('hidden_compensation', '-compensation_amount', '-id')
    elif sort == 'title':
        studies = studies.order_by('title', '-id')
    return studies


def category_tiles():
    public_statuses = [Study.Status.PUBLISHED, Study.Status.FULL]
    return (
        StudyCategory.objects.filter(is_active=True)
        .annotate(
            public_count=Count(
                'studies',
                filter=Q(studies__status__in=public_statuses),
                distinct=True,
            )
        )
        .order_by('display_order')
    )


def alternatives_for(profile, exclude_study, limit=3):
    """Return up to limit eligible public studies that fit the participant."""
    if exclude_study is None:
        return []
    category_positions = {
        category: index for index, category in enumerate(profile.ml1_categories or [])
    }
    studies = (
        _with_review_ratings(Study.objects.filter(
            status__in=[Study.Status.PUBLISHED, Study.Status.FULL],
        )
        )
        .exclude(pk=exclude_study.pk)
        .exclude(applications__participant=profile)
        .select_related('category', 'organisation')
        .prefetch_related('sites__region', 'required_conditions', 'excluded_conditions')
        .distinct()
    )
    eligible = [study for study in studies if is_eligible(profile, study)]
    eligible.sort(key=lambda study: (
        0 if study.category_id == exclude_study.category_id else 1,
        category_positions.get(study.category.ml_label, len(category_positions)),
        study.recruitment_deadline,
        study.pk,
    ))
    return eligible[:limit]


def popular_studies(limit=6):
    """Return public studies ordered by recent applications, then newest published."""
    cutoff = timezone.now() - timedelta(days=30)
    return (
        public_studies()
        .annotate(
            recent_applications=Count(
                'applications',
                filter=Q(applications__submitted_at__gte=cutoff),
                distinct=True,
            )
        )
        .order_by('-recent_applications', '-published_at', '-id')[:limit]
    )


@transaction.atomic
def register_participant(first_name, last_name, email, mobile, password):
    email = email.lower()
    if User.objects.filter(username=email).exists():
        raise ValidationError('An account with this email already exists.')
    validate_password(password)
    user = User.objects.create_user(
        username=email, email=email, first_name=first_name,
        last_name=last_name, password=password,
    )
    user.groups.add(Group.objects.get(name='Participant'))
    ParticipantProfile.objects.create(
        user=user, mobile=normalise_sg_mobile(mobile),
        terms_accepted_at=timezone.now(),
    )
    return user


@transaction.atomic
def register_researcher(
    first_name, last_name, email, organisation_id, job_title, mobile, password
):
    email = email.lower()
    if User.objects.filter(username=email).exists():
        raise ValidationError('An account with this email already exists.')
    validate_password(password)
    organisation = Organisation.objects.get(pk=organisation_id, is_active=True)
    user = User.objects.create_user(
        username=email, email=email, first_name=first_name,
        last_name=last_name, password=password, is_active=False,
    )
    user.groups.add(Group.objects.get(name='Coordinator'))
    StaffProfile.objects.create(
        user=user, organisation=organisation, job_title=job_title,
        mobile=normalise_sg_mobile(mobile),
    )
    notify_staff(
        f'New research team sign-up: {user.get_full_name()} ({organisation}) is waiting for approval.',
        f'/panel/organisations/{organisation.id}/users/',
    )
    return user


def notify_staff(message, link=''):
    staff_group = Group.objects.get(name='Staff')
    admin_group = Group.objects.get(name='Admin')
    users = User.objects.filter(
        is_active=True, groups__in=[staff_group, admin_group]
    ).distinct()
    return notify_users(users, message, link)


def notify_users(users, message, link=''):
    return Notification.objects.bulk_create(
        [Notification(user=user, message=message, link=link) for user in users]
    )


def list_notifications(user):
    return Notification.objects.filter(user=user).order_by('-created_at', '-id')


def unread_count(user):
    return Notification.objects.filter(user=user, is_read=False).count()


def mark_all_read(user):
    return Notification.objects.filter(user=user, is_read=False).update(is_read=True)


def user_role(user):
    permissions = user.get_all_permissions()
    if 'core.admin_access' in permissions:
        return 'admin'
    if 'core.staff_access' in permissions:
        return 'staff'
    if 'core.panel_access' in permissions:
        return 'coordinator'
    if 'core.participant_access' in permissions:
        return 'participant'
    return None


def sign_in_check(email, password):
    try:
        user = User.objects.get(username=email.lower())
    except User.DoesNotExist:
        return None, 'Email or password is incorrect.'
    if not user.check_password(password):
        return None, 'Email or password is incorrect.'
    if not user.is_active:
        if user.groups.filter(name='Coordinator').exists():
            return None, 'Your research team account is waiting for approval.'
        return None, 'This account is switched off. Contact Athena.'
    return user, None


@dataclass(frozen=True)
class RuleResult:
    code: str
    label: str
    detail: str
    met: bool


def save_profile(profile, form):
    was_complete = profile_ready(profile)
    profile = form.save()
    if not was_complete:
        profile.onboarding_completed_at = timezone.now()
        profile.save(update_fields=['onboarding_completed_at', 'updated_at'])
    return profile


def check_eligibility(profile, study):
    results = [
        RuleResult(
            'age', 'Age',
            f'Ages {study.min_age} to {study.max_age} (you are {profile.age}).',
            profile.age is not None and study.min_age <= profile.age <= study.max_age,
        ),
        RuleResult(
            'sex', 'Sex', study.SexEligibility(study.sex_eligibility).label,
            study.sex_eligibility == study.SexEligibility.ALL
            or study.sex_eligibility == profile.sex,
        ),
        RuleResult(
            'health', 'Health',
            'Healthy volunteers are welcome'
            if study.accepts_healthy_volunteers
            else 'For people living with a health condition.',
            study.accepts_healthy_volunteers or profile.conditions.exists(),
        ),
    ]
    required = list(study.required_conditions.all())
    excluded = list(study.excluded_conditions.all())
    if required:
        results.append(RuleResult(
            'required_conditions', 'Must have',
            ', '.join(condition.name for condition in required),
            profile.conditions.filter(pk__in=[condition.pk for condition in required]).exists(),
        ))
    if excluded:
        results.append(RuleResult(
            'excluded_conditions', 'Not suitable if you have',
            ', '.join(condition.name for condition in excluded),
            not profile.conditions.filter(pk__in=[condition.pk for condition in excluded]).exists(),
        ))
    results.append(RuleResult(
        'smoking', 'Smoking', study.SmokerRule(study.smoker_rule).label,
        study.smoker_rule == study.SmokerRule.ANY
        or (study.smoker_rule == study.SmokerRule.SMOKERS and profile.smoker)
        or (study.smoker_rule == study.SmokerRule.NON_SMOKERS and not profile.smoker),
    ))
    if study.min_bmi is not None or study.max_bmi is not None:
        minimum = study.min_bmi if study.min_bmi is not None else 'no minimum'
        maximum = study.max_bmi if study.max_bmi is not None else 'no maximum'
        profile_bmi = float(profile.bmi) if profile.bmi is not None else None
        results.append(RuleResult(
            'bmi', 'BMI', f'BMI {minimum} to {maximum} (yours is {profile.bmi}).',
            profile_bmi is not None
            and (study.min_bmi is None or profile_bmi >= float(study.min_bmi))
            and (study.max_bmi is None or profile_bmi <= float(study.max_bmi)),
        ))
    regions = list(study.regions.all())
    if regions:
        results.append(RuleResult(
            'region', 'Where you live', ', '.join(region.name for region in regions),
            profile.region_id in {region.pk for region in regions},
        ))
    return results


def is_eligible(profile, study):
    return all(result.met for result in check_eligibility(profile, study))


def eligible_studies(profile):
    return [study for study in public_studies() if is_eligible(profile, study)]


def profile_ready(profile):
    return profile.onboarding_completed_at is not None


def refresh_interest_predictions(profile):
    if not profile.consent_matching:
        profile.ml1_categories = []
        profile.ml1_model_version = ''
        profile.ml1_predicted_at = None
        profile.save(update_fields=[
            'ml1_categories', 'ml1_model_version', 'ml1_predicted_at', 'updated_at',
        ])
        return None

    from ml.services import predict_interest

    result = predict_interest(profile)
    if result is None:
        profile.ml1_categories = []
        profile.ml1_model_version = ''
        profile.ml1_predicted_at = None
        profile.save(update_fields=[
            'ml1_categories', 'ml1_model_version', 'ml1_predicted_at', 'updated_at',
        ])
        return None

    profile.ml1_categories = [item['category'] for item in result['top_three']]
    profile.ml1_model_version = result['model_version']
    profile.ml1_predicted_at = timezone.now()
    profile.save(update_fields=[
        'ml1_categories', 'ml1_model_version', 'ml1_predicted_at', 'updated_at',
    ])
    return result


def enrolled_count(study):
    return study.applications.filter(
        status__in=[Application.Status.ENROLLED, Application.Status.COMPLETED]
    ).count()


def is_full(study):
    return enrolled_count(study) >= study.target_enrolment


@transaction.atomic
def refresh_capacity(study):
    full = is_full(study)
    if study.status == Study.Status.PUBLISHED and full:
        study.status = Study.Status.FULL
        study.save(update_fields=['status', 'updated_at'])
    elif study.status == Study.Status.FULL and not full:
        study.status = Study.Status.PUBLISHED
        study.save(update_fields=['status', 'updated_at'])
    return study


@transaction.atomic
def change_status(application, to_status, actor=None, actor_role='system', note=''):
    current = application.status
    if to_status not in ALLOWED_MOVES.get(current, set()):
        current_label = application.Status(current).label
        target_label = application.Status(to_status).label
        raise InvalidStatusMove(
            f'An application cannot move from {current_label} to {target_label}.'
        )
    if to_status == Application.Status.ENROLLED and is_full(application.study):
        raise StudyFull('This study is full. Waitlist the applicant instead.')
    application.status = to_status
    application.save(update_fields=['status', 'updated_at'])
    ApplicationStatusEvent.objects.create(
        application=application,
        from_status=current,
        to_status=to_status,
        actor=actor,
        actor_role=actor_role,
        note=note,
    )
    if to_status == Application.Status.ENROLLED or current == Application.Status.ENROLLED:
        refresh_capacity(application.study)
    return application


PARTICIPANT_STATUS_LABELS = {
    Application.Status.SUBMITTED: 'Received',
    Application.Status.AUTO_DECLINED: 'Not eligible this time',
    Application.Status.UNDER_REVIEW: 'Being reviewed',
    Application.Status.WAITLISTED: 'Waitlisted',
    Application.Status.SHORTLISTED: 'Shortlisted',
    Application.Status.SCREENING_SCHEDULED: 'Screening booked',
    Application.Status.SCREENING_PASSED: 'Screening passed',
    Application.Status.SCREENING_FAILED: 'Did not pass screening',
    Application.Status.ENROLLED: 'Enrolled',
    Application.Status.COMPLETED: 'Completed',
    Application.Status.NOT_SELECTED: 'Not selected',
    Application.Status.WITHDRAWN: 'Withdrawn',
}

WHAT_HAPPENS_NEXT = {
    Application.Status.SUBMITTED:
        'The research team is reviewing applications. You will see the next step here.',
    Application.Status.UNDER_REVIEW:
        'The research team is reviewing applications. You will see the next step here.',
    Application.Status.WAITLISTED:
        'The study is full right now. If a place opens, the research team can move you forward.',
    Application.Status.SHORTLISTED:
        'The research team will propose a screening appointment. You can confirm it here.',
    Application.Status.SCREENING_SCHEDULED:
        'Confirm your screening appointment below and attend at the time shown.',
    Application.Status.SCREENING_PASSED:
        'You passed screening. The research team will confirm whether you are enrolled.',
    Application.Status.ENROLLED:
        'You are taking part. Attend your study visits; compensation is paid as visits are completed.',
    Application.Status.COMPLETED:
        'Thank you for taking part. You can rate and review this study.',
    Application.Status.AUTO_DECLINED:
        'This study is not the right fit this time.',
    Application.Status.NOT_SELECTED:
        'The research team did not select you this time.',
    Application.Status.SCREENING_FAILED:
        'You did not pass screening this time.',
    Application.Status.WITHDRAWN:
        'You withdrew from this study.',
}


def my_applications(profile):
    applications = (
        Application.objects.filter(participant=profile)
        .select_related('study', 'study__organisation', 'study__category')
        .order_by('-updated_at', '-id')
    )
    open_applications = []
    finished_applications = []
    for application in applications:
        application.participant_status_label = PARTICIPANT_STATUS_LABELS[
            application.status
        ]
        if application.status in OPEN_STATUSES:
            open_applications.append(application)
        else:
            finished_applications.append(application)
    return open_applications, finished_applications


def get_my_application(profile, application_id):
    return (
        Application.objects.select_related(
            'study', 'study__organisation', 'study__category', 'preferred_site'
        )
        .prefetch_related(
            'status_events',
            'appointments__site',
            'payouts',
            'support_requests',
        )
        .get(pk=application_id, participant=profile)
    )


def timeline(application):
    events = list(application.status_events.select_related('actor').order_by('created_at', 'id'))
    for event in events:
        event.participant_label = PARTICIPANT_STATUS_LABELS[event.to_status]
        event.actor_label = ApplicationStatusEvent.ActorRole(event.actor_role).label
    return events


def what_happens_next(application):
    text = WHAT_HAPPENS_NEXT[application.status]
    if application.status == Application.Status.NOT_SELECTED and application.not_selected_reason:
        return f'{text} {application.not_selected_reason}'
    return text


def confirm_appointment(profile, appointment_id):
    appointment = Appointment.objects.filter(
        pk=appointment_id,
        application__participant=profile,
        application__status__in=OPEN_STATUSES,
        status=Appointment.Status.PROPOSED,
        scheduled_for__gt=timezone.now(),
    ).first()
    if appointment is None:
        raise ValidationError('This appointment cannot be confirmed.')
    appointment.status = Appointment.Status.CONFIRMED
    appointment.confirmed_at = timezone.now()
    appointment.save(update_fields=['status', 'confirmed_at', 'updated_at'])
    return appointment


def notify_coordinators(organisation, message, link=''):
    coordinators = User.objects.filter(
        is_active=True,
        groups__name='Coordinator',
        staff_profile__organisation=organisation,
    ).distinct()
    return notify_users(coordinators, message, link)


@transaction.atomic
def withdraw_application(profile, application, reason=''):
    if application.participant_id != profile.pk:
        raise Application.DoesNotExist
    change_status(
        application,
        Application.Status.WITHDRAWN,
        actor=profile.user,
        actor_role=ApplicationStatusEvent.ActorRole.PARTICIPANT,
        note='You withdrew',
    )
    application.withdrawal_reason = reason
    application.save(update_fields=['withdrawal_reason', 'updated_at'])
    application.appointments.filter(
        status__in=[Appointment.Status.PROPOSED, Appointment.Status.CONFIRMED]
    ).update(status=Appointment.Status.CANCELLED, updated_at=timezone.now())
    notify_coordinators(
        application.study.organisation,
        f'{application.reference} withdrew from {application.study.title}.',
        f'/panel/applications/{application.pk}/',
    )
    return application


def payouts_summary(application):
    payouts = application.payouts.order_by('-created_at', '-id')
    total_paid = payouts.filter(status=Payout.Status.PAID).aggregate(
        total=Sum('amount')
    )['total'] or 0
    return payouts, total_paid


@transaction.atomic
def save_review(profile, study, rating, comment=''):
    if not Application.objects.filter(
        participant=profile,
        study=study,
        status=Application.Status.COMPLETED,
    ).exists():
        raise ValidationError('You can review a study after you complete it.')
    review, created = Review.objects.get_or_create(
        participant=profile,
        study=study,
        defaults={'rating': rating, 'comment': comment, 'status': Review.Status.PENDING},
    )
    if not created:
        if review.status != Review.Status.PENDING:
            raise ValidationError(
                'This review has already been checked and cannot be changed.'
            )
        review.rating = rating
        review.comment = comment
        review.save(update_fields=['rating', 'comment', 'updated_at'])
    return review


def study_rating(study):
    result = study.reviews.filter(status=Review.Status.APPROVED).aggregate(
        average=Avg('rating'),
        count=Count('id'),
    )
    average = result['average']
    rounded = (
        float(Decimal(str(average)).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP))
        if average is not None else None
    )
    return rounded, result['count']


def approved_reviews(study):
    return (
        study.reviews.filter(status=Review.Status.APPROVED)
        .order_by('-created_at', '-id')
    )


@transaction.atomic
def create_support_request(application, topic, question):
    request = SupportRequest.objects.create(
        application=application,
        topic=topic,
        question=question,
    )
    notify_staff(
        f'New question about {application.reference}: '
        f'{SupportRequest.Topic(topic).label}.',
        f'/panel/support/{request.pk}/',
    )
    return request


def get_settings():
    settings, _ = AppSetting.objects.get_or_create(
        pk=1,
        defaults={
            'ml2_high_threshold': 0.70,
            'ml2_medium_threshold': 0.40,
        },
    )
    return settings


def band_for(probability, settings):
    if probability is None:
        return Application.Band.UNSCORED
    if probability >= float(settings.ml2_high_threshold):
        return Application.Band.HIGH
    if probability >= float(settings.ml2_medium_threshold):
        return Application.Band.MEDIUM
    return Application.Band.LOW


@transaction.atomic
def submit_application(profile, study, answers, preferred_site_id, availability, consent):
    if study.status not in (Study.Status.PUBLISHED, Study.Status.FULL):
        raise Study.DoesNotExist
    existing = Application.objects.filter(participant=profile, study=study).first()
    if existing:
        return existing, False
    if not is_eligible(profile, study):
        raise NotEligible
    if not consent:
        raise ValidationError('Tick the consent box to send your application.')

    questions = list(study.pre_screen_questions.all())
    normalised_answers = {int(key): value for key, value in answers.items()}
    if any(
        question.pk not in normalised_answers
        or normalised_answers[question.pk] not in question.option_list()
        for question in questions
    ):
        raise ValidationError('Answer every question.')
    if not study.sites.filter(pk=preferred_site_id).exists():
        raise ValidationError('Choose a site for this study.')
    if availability not in Application.Availability.values:
        raise ValidationError('Choose when you are available.')

    now = timezone.now()
    application = Application.objects.create(
        participant=profile,
        study=study,
        status=Application.Status.SUBMITTED,
        preferred_site_id=preferred_site_id,
        availability=availability,
        consent_given_at=now,
        submitted_at=now,
    )
    ApplicationAnswer.objects.bulk_create([
        ApplicationAnswer(
            application=application,
            question=question,
            answer=normalised_answers[question.pk],
        )
        for question in questions
    ])
    ApplicationStatusEvent.objects.create(
        application=application,
        from_status='',
        to_status=Application.Status.SUBMITTED,
        actor_role=ApplicationStatusEvent.ActorRole.SYSTEM,
        note='Application received',
    )
    if not profile.first_application_category_id:
        profile.first_application_category = study.category
        profile.save(update_fields=['first_application_category', 'updated_at'])

    if any(
        normalised_answers[question.pk] == question.disqualifying_answer
        for question in questions
        if question.disqualifying_answer
    ):
        change_status(
            application,
            Application.Status.AUTO_DECLINED,
            note='One of your answers means this study is not the right fit.',
        )
        return application, True

    from ml import services as ml_services
    prediction = ml_services.predict_screening(application)
    if prediction is None:
        band = Application.Band.UNSCORED
    else:
        application.ml2_probability = prediction.get('probability')
        application.ml2_model_version = prediction.get('version', '')
        band = band_for(application.ml2_probability, get_settings())
        application.ml2_band = band
        application.save(update_fields=[
            'ml2_probability', 'ml2_model_version', 'ml2_band', 'updated_at',
        ])

    if is_full(study):
        change_status(
            application,
            Application.Status.WAITLISTED,
            note='The study is full, so you are on the waitlist.',
        )
    elif band == Application.Band.HIGH and study.auto_shortlist_high:
        application.auto_shortlisted = True
        application.save(update_fields=['auto_shortlisted', 'updated_at'])
        change_status(
            application,
            Application.Status.SHORTLISTED,
            note='Shortlisted by System',
        )
    else:
        change_status(
            application,
            Application.Status.UNDER_REVIEW,
            note='Waiting for the research team to review',
        )
    return application, True


def _feed_reasons(profile, study, category_position):
    reasons = []
    if category_position == 0:
        reasons.append(f'Matches your interest in {study.category.name}')
    elif category_position in (1, 2):
        reasons.append(f'Related to your interest in {study.category.name}')
    if len(reasons) < 3:
        reasons.append('You meet the age and health criteria')
    if len(reasons) < 3 and study.sites.filter(region=profile.region).exists():
        reasons.append(f'Site in the {profile.region.name} region')
    if len(reasons) < 3 and study.recruitment_deadline <= timezone.localdate() + timedelta(days=14):
        reasons.append('Closing soon')
    return reasons[:3]


def for_you_feed(profile):
    if not profile.consent_matching or not profile.ml1_categories:
        return {
            'mode': 'popular',
            'notice': (
                'Turn on recommendations in your profile to see studies picked for you.'
                if not profile.consent_matching
                else 'We could not pick studies for you just now, so here are popular studies.'
            ),
            'items': [
                {'study': study, 'reasons': []}
                for study in popular_studies(12)
                if is_eligible(profile, study)
            ] or [
                {'study': study, 'reasons': []}
                for study in popular_studies(12)
            ],
        }

    category_positions = {
        label: position for position, label in enumerate(profile.ml1_categories)
    }
    eligible = eligible_studies(profile)
    eligible.sort(key=lambda study: (
        category_positions.get(study.category.ml_label, 3),
        0 if study.sites.filter(region=profile.region).exists() else 1,
        study.recruitment_deadline,
    ))
    return {
        'mode': 'personal',
        'notice': '',
        'items': [
            {
                'study': study,
                'reasons': _feed_reasons(
                    profile, study, category_positions.get(study.category.ml_label, 3)
                ),
            }
            for study in eligible[:24]
        ],
    }


def personal_row(profile):
    feed = for_you_feed(profile)
    return feed['items'][:3] if feed['mode'] == 'personal' else []
