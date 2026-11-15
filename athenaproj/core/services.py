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
from django.db.models import Avg, Case, Count, Exists, F, IntegerField, OuterRef, Q, Sum, Value, When
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


def get_panel_application(user, application_id):
    role = user_role(user)
    applications = Application.objects.all()
    if role == 'coordinator':
        organisation_id = getattr(
            getattr(user, 'staff_profile', None), 'organisation_id', None
        )
        applications = applications.filter(
            study__organisation_id=organisation_id
        )
    elif role not in ('staff', 'admin'):
        applications = applications.none()
    return applications.select_related(
        'participant__user',
        'participant__region',
        'preferred_site',
        'study__organisation',
        'study__category',
        'overridden_by',
    ).prefetch_related(
        'answers__question',
        'status_events__actor',
        'appointments__site',
    ).get(pk=application_id)


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


def applicant_queue(study, tab='needs_action', band='', site='', availability=''):
    screening_appointments = Appointment.objects.filter(
        application_id=OuterRef('pk'),
        kind=Appointment.Kind.SCREENING,
    )
    applications = Application.objects.filter(study=study).exclude(
        status=Application.Status.AUTO_DECLINED
    ).annotate(
        has_screening=Exists(screening_appointments),
        band_rank=Case(
            When(ml2_band=Application.Band.HIGH, then=Value(0)),
            When(ml2_band=Application.Band.MEDIUM, then=Value(1)),
            When(ml2_band=Application.Band.LOW, then=Value(2)),
            default=Value(3),
            output_field=IntegerField(),
        ),
    )
    if tab == 'needs_action':
        applications = applications.filter(
            Q(status=Application.Status.UNDER_REVIEW)
            | Q(status=Application.Status.SHORTLISTED, has_screening=False)
            | Q(status=Application.Status.SCREENING_PASSED)
        )
    else:
        tab_statuses = {
            'under_review': Application.Status.UNDER_REVIEW,
            'shortlisted': Application.Status.SHORTLISTED,
            'screening_scheduled': Application.Status.SCREENING_SCHEDULED,
            'screening_passed': Application.Status.SCREENING_PASSED,
            'waitlisted': Application.Status.WAITLISTED,
        }
        status = tab_statuses.get(tab)
        if status is None:
            applications = applications.none()
        else:
            applications = applications.filter(status=status)
    if band:
        applications = applications.filter(ml2_band=band)
    if site:
        applications = applications.filter(preferred_site_id=site)
    if availability:
        applications = applications.filter(availability=availability)
    return applications.select_related(
        'participant__user',
        'participant__region',
        'preferred_site',
    ).order_by(
        'band_rank',
        F('ml2_probability').desc(nulls_last=True),
        'submitted_at',
        'pk',
    )


def age_band(age):
    if age < 30:
        return '21 to 29'
    if age < 40:
        return '30 to 39'
    if age < 50:
        return '40 to 49'
    if age < 60:
        return '50 to 59'
    return '60 and over'


def identity_unlocked(application):
    return application.status_events.filter(
        to_status=Application.Status.SHORTLISTED
    ).exists()


def shortlist_applicant(application, user):
    return change_status(
        application,
        Application.Status.SHORTLISTED,
        actor=user,
        actor_role=ApplicationStatusEvent.ActorRole.COORDINATOR,
        note='Good fit with the study criteria',
    )


@transaction.atomic
def schedule_screening(application, when, site, user):
    if timezone.is_naive(when):
        when = timezone.make_aware(when, timezone.get_current_timezone())
    if when <= timezone.now():
        raise ValidationError('Choose a date and time in the future.')
    if site is None or not application.study.sites.filter(pk=site.pk).exists():
        raise ValidationError('Choose a site for this study.')
    appointment = Appointment.objects.create(
        application=application,
        site=site,
        kind=Appointment.Kind.SCREENING,
        scheduled_for=when,
        status=Appointment.Status.PROPOSED,
    )
    note = (
        f'Screening on {timezone.localtime(when).strftime("%d %b %Y, %I:%M %p")} '
        f'at {site.name}'
    )
    change_status(
        application,
        Application.Status.SCREENING_SCHEDULED,
        actor=user,
        actor_role=ApplicationStatusEvent.ActorRole.COORDINATOR,
        note=note,
    )
    return appointment


@transaction.atomic
def record_screening_outcome(application, passed, user, note=''):
    target_status = (
        Application.Status.SCREENING_PASSED
        if passed else Application.Status.SCREENING_FAILED
    )
    appointment = application.appointments.filter(
        kind=Appointment.Kind.SCREENING
    ).order_by('-created_at', '-pk').first()
    if appointment is None:
        change_status(
            application,
            target_status,
            actor=user,
            actor_role=ApplicationStatusEvent.ActorRole.COORDINATOR,
        )
        raise ValidationError('This application has no screening appointment.')
    outcome = (
        Application.ScreeningOutcome.PASSED
        if passed else Application.ScreeningOutcome.FAILED
    )
    application.screening_outcome = outcome
    application.outcome_recorded_at = timezone.now()
    application.save(update_fields=[
        'screening_outcome', 'outcome_recorded_at', 'updated_at',
    ])
    appointment.status = Appointment.Status.ATTENDED
    appointment.save(update_fields=['status', 'updated_at'])
    event_note = (
        'You passed screening'
        if passed else (note.strip() or 'Thank you for attending screening')
    )
    return change_status(
        application,
        target_status,
        actor=user,
        actor_role=ApplicationStatusEvent.ActorRole.COORDINATOR,
        note=event_note,
    )


@transaction.atomic
def enrol_applicant(application, user):
    change_status(
        application,
        Application.Status.ENROLLED,
        actor=user,
        actor_role=ApplicationStatusEvent.ActorRole.COORDINATOR,
        note='Welcome to the study',
    )
    Appointment.objects.bulk_create([
        Appointment(
            application=application,
            site=application.preferred_site,
            kind=Appointment.Kind.VISIT,
            visit_number=visit_number,
            status=Appointment.Status.PROPOSED,
        )
        for visit_number in range(1, application.study.total_visits + 1)
    ])
    return application


def waitlist_applicant(application, user):
    return change_status(
        application,
        Application.Status.WAITLISTED,
        actor=user,
        actor_role=ApplicationStatusEvent.ActorRole.COORDINATOR,
        note='You are on the waitlist',
    )


def move_to_review(application, user):
    return change_status(
        application,
        Application.Status.UNDER_REVIEW,
        actor=user,
        actor_role=ApplicationStatusEvent.ActorRole.COORDINATOR,
        note='Moved back to review',
    )


@transaction.atomic
def mark_not_selected(application, user, reason):
    change_status(
        application,
        Application.Status.NOT_SELECTED,
        actor=user,
        actor_role=ApplicationStatusEvent.ActorRole.COORDINATOR,
        note='Not selected this time',
    )
    application.not_selected_reason = reason
    application.save(update_fields=['not_selected_reason', 'updated_at'])
    return application


@transaction.atomic
def override_band(application, new_band, reason, user):
    reason = reason.strip()
    if len(reason) < 10:
        raise ValidationError('Give a reason of at least 10 characters.')
    if new_band not in (
        Application.Band.HIGH,
        Application.Band.MEDIUM,
        Application.Band.LOW,
    ):
        raise ValidationError('Choose High, Medium or Low.')
    if new_band == application.ml2_band:
        raise ValidationError('Choose a band different from the current band.')
    if not application.band_overridden:
        application.original_band = application.ml2_band
    application.band_overridden = True
    application.ml2_band = new_band
    application.override_reason = reason
    application.overridden_by = user
    application.overridden_at = timezone.now()
    application.save(update_fields=[
        'original_band',
        'band_overridden',
        'ml2_band',
        'override_reason',
        'overridden_by',
        'overridden_at',
        'updated_at',
    ])
    return application


def model_inputs(application):
    prediction = application.prediction_logs.filter(
        model_name=PredictionLog.ModelName.ML2,
        succeeded=True,
    ).order_by('-created_at', '-pk').first()
    if prediction is None:
        return []
    features = prediction.features
    preferred_total = application.study.pre_screen_questions.filter(
        preferred_answer__gt=''
    ).count()
    preferred_share = float(features.get('preferred_answer_share', 0))
    preferred_count = round(preferred_share * preferred_total)
    return [
        {
            'label': 'Region match',
            'value': 'Yes' if features.get('region_match') else 'No',
        },
        {
            'label': 'Availability match',
            'value': 'Yes' if features.get('availability_match') else 'No',
        },
        {
            'label': 'Preferred answers',
            'value': f'{preferred_count} of {preferred_total}',
        },
        {
            'label': 'Prior completed studies',
            'value': features.get('prior_completed', 0),
        },
        {
            'label': 'Prior no-shows',
            'value': features.get('prior_no_shows', 0),
        },
        {
            'label': 'BMI near a limit',
            'value': 'Yes' if features.get('bmi_near_limit') else 'No',
        },
    ]


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


@transaction.atomic
def save_visit_date(appointment, when, user):
    """Set a visit date and reset status to proposed so participant confirms."""
    if appointment.kind != Appointment.Kind.VISIT:
        raise ValidationError('Only visit appointments can have dates scheduled.')
    if appointment.application.status != Application.Status.ENROLLED:
        raise ValidationError('This visit cannot be marked yet.')
    if appointment.status not in [Appointment.Status.PROPOSED, Appointment.Status.CONFIRMED]:
        raise ValidationError('This visit cannot be marked yet.')
    appointment.scheduled_for = when
    appointment.status = Appointment.Status.PROPOSED
    appointment.save(update_fields=['scheduled_for', 'status', 'updated_at'])
    return appointment


@transaction.atomic
def mark_visit(appointment, attended, user):
    """Mark a visit as attended or missed."""
    if appointment.kind != Appointment.Kind.VISIT:
        raise ValidationError('Only visit appointments can be marked.')
    if appointment.application.status != Application.Status.ENROLLED:
        raise ValidationError('This visit cannot be marked yet.')
    if appointment.status not in [Appointment.Status.PROPOSED, Appointment.Status.CONFIRMED]:
        raise ValidationError('This visit cannot be marked yet.')
    if appointment.scheduled_for is None or appointment.scheduled_for > timezone.now():
        raise ValidationError('This visit cannot be marked yet.')

    appointment.status = Appointment.Status.ATTENDED if attended else Appointment.Status.MISSED
    appointment.save(update_fields=['status', 'updated_at'])
    return appointment


def earned_amount(application):
    """Calculate compensation earned: compensation × attended_visits / total_visits."""
    attended_count = application.appointments.filter(
        kind=Appointment.Kind.VISIT,
        status=Appointment.Status.ATTENDED,
    ).count()
    total_visits = application.study.total_visits
    if total_visits == 0:
        return Decimal('0.00')
    earned = application.study.compensation_amount * Decimal(attended_count) / Decimal(total_visits)
    return earned.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def amount_due(application):
    """Calculate amount due: earned_amount - (requested + paid), minimum 0."""
    earned = earned_amount(application)
    already_requested_or_paid = application.payouts.filter(
        status__in=[Payout.Status.REQUESTED, Payout.Status.PAID]
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    due = earned - already_requested_or_paid
    return max(due, Decimal('0.00')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


@transaction.atomic
def request_payout(application, user):
    """Create a payout request if amount is due."""
    due = amount_due(application)
    if due <= 0:
        raise ValidationError('Nothing is due right now.')

    attended_count = application.appointments.filter(
        kind=Appointment.Kind.VISIT,
        status=Appointment.Status.ATTENDED,
    ).count()

    payout = Payout.objects.create(
        application=application,
        amount=due,
        visits_counted=attended_count,
        status=Payout.Status.REQUESTED,
        requested_by=user,
    )
    notify_staff(
        f'Payout requested for {application.reference}: S${due:.2f}.',
        '/panel/payouts/',
    )
    return payout


@transaction.atomic
def complete_participation(application, user):
    """Mark application as completed if all visits are recorded."""
    open_visits = application.appointments.filter(
        kind=Appointment.Kind.VISIT,
        status__in=[Appointment.Status.PROPOSED, Appointment.Status.CONFIRMED],
    )
    if open_visits.exists():
        raise ValidationError('Record every visit as attended or missed first.')

    change_status(
        application,
        Application.Status.COMPLETED,
        actor=user,
        actor_role=ApplicationStatusEvent.ActorRole.COORDINATOR,
        note='Thank you for taking part',
    )
    return application


@transaction.atomic
def coordinator_withdraw(application, user, reason=''):
    """Withdraw participant by coordinator, cancels open appointments."""
    note = reason if reason else 'Withdrawn by the research team'
    change_status(
        application,
        Application.Status.WITHDRAWN,
        actor=user,
        actor_role=ApplicationStatusEvent.ActorRole.COORDINATOR,
        note=note,
    )
    application.appointments.filter(
        status__in=[Appointment.Status.PROPOSED, Appointment.Status.CONFIRMED]
    ).update(status=Appointment.Status.CANCELLED, updated_at=timezone.now())
    refresh_capacity(application.study)
    return application


def study_funnel(applications_queryset):
    """Return counts for each funnel stage."""
    qs = applications_queryset
    applied = qs.count()

    passed_pre_screen = qs.exclude(
        status=Application.Status.AUTO_DECLINED
    ).count()

    shortlisted = qs.filter(
        status_events__to_status=Application.Status.SHORTLISTED
    ).distinct().count()

    screened = qs.exclude(screening_outcome='').count()
    passed_screening = qs.filter(screening_outcome=Application.ScreeningOutcome.PASSED).count()

    enrolled = qs.filter(
        status_events__to_status=Application.Status.ENROLLED
    ).distinct().count()

    completed = qs.filter(
        status=Application.Status.COMPLETED
    ).count()

    return {
        'applied': applied,
        'passed_pre_screen': passed_pre_screen,
        'shortlisted': shortlisted,
        'screened': screened,
        'passed_screening': passed_screening,
        'enrolled': enrolled,
        'completed': completed,
    }


def band_pass_rates(qs):
    """Return screening pass rates by ML-2 band."""
    bands = ['high', 'medium', 'low', 'unscored']
    result = {}
    for band in bands:
        band_qs = qs.filter(ml2_band=band)
        outcomes = band_qs.exclude(screening_outcome='')
        if outcomes.exists():
            passed = outcomes.filter(
                screening_outcome=Application.ScreeningOutcome.PASSED
            ).count()
            total = outcomes.count()
            rate = (passed / total * 100) if total > 0 else 0
            result[band] = {
                'passed': passed,
                'total': total,
                'rate': f'{rate:.0f}%',
            }
        else:
            result[band] = {
                'passed': 0,
                'total': 0,
                'rate': 'No outcomes yet',
            }
    return result


def band_distribution(qs):
    """Return application counts by ML-2 band."""
    return list(
        qs.values('ml2_band').annotate(count=Count('id')).order_by('ml2_band')
    )


def applicant_mix(qs):
    """Return age/sex/region counts for applied vs enrolled with insights consent."""
    result = {
        'age_bands': {},
        'sex': {},
        'regions': {},
    }

    for label in ['applied', 'enrolled']:
        if label == 'applied':
            filtered_qs = qs
        else:
            filtered_qs = qs.filter(status=Application.Status.ENROLLED)

        filtered_qs = filtered_qs.filter(
            participant__consent_insights=True
        )

        age_bands_raw = filtered_qs.values_list(
            'participant__user__first_name',
            'participant__date_of_birth',
        )
        age_band_counts = defaultdict(int)
        for _, dob in age_bands_raw:
            if dob:
                age = age_band(
                    (timezone.now().date() - dob).days // 365
                )
                age_band_counts[age] += 1

        if label not in result['age_bands']:
            result['age_bands'][label] = {}
        result['age_bands'][label] = dict(age_band_counts)

        sex_counts = filtered_qs.values('participant__sex').annotate(
            count=Count('id')
        ).order_by('participant__sex')
        if label not in result['sex']:
            result['sex'][label] = {}
        result['sex'][label] = {
            item['participant__sex']: item['count'] for item in sex_counts
        }

        region_counts = filtered_qs.values(
            'participant__region__name'
        ).annotate(count=Count('id')).order_by('participant__region__name')
        if label not in result['regions']:
            result['regions'][label] = {}
        result['regions'][label] = {
            item['participant__region__name']: item['count']
            for item in region_counts if item['participant__region__name']
        }

    return result


def coordinator_dashboard(user):
    """Return dashboard data for coordinator's organisation."""
    if not user.has_perm('core.panel_access'):
        raise ValidationError('Access denied.')

    org = getattr(user.staff_profile, 'organisation', None)
    if not org:
        return None

    studies = Study.objects.filter(
        organisation=org,
        status__in=[Study.Status.PUBLISHED, Study.Status.PAUSED, Study.Status.FULL],
    )

    applications_qs = Application.objects.filter(study__in=studies)

    high_priority = applications_qs.filter(
        status=Application.Status.UNDER_REVIEW,
        ml2_band=Application.Band.HIGH,
    ).count()

    awaiting_review = applications_qs.filter(
        status=Application.Status.UNDER_REVIEW,
    ).count()

    screening_appointments = Appointment.objects.filter(
        application__study__in=studies,
        kind=Appointment.Kind.SCREENING,
        status__in=[Appointment.Status.PROPOSED, Appointment.Status.CONFIRMED],
        scheduled_for__gt=timezone.now(),
        scheduled_for__lte=timezone.now() + timedelta(days=7),
    ).count()

    payouts_awaiting = Payout.objects.filter(
        application__study__in=studies,
        status=Payout.Status.REQUESTED,
    ).count()

    under_review_apps = applications_qs.filter(
        status=Application.Status.UNDER_REVIEW,
    ).order_by('-ml2_band', '-created_at', '-id')[:5]

    screening_list = Appointment.objects.filter(
        application__study__in=studies,
        kind=Appointment.Kind.SCREENING,
        status__in=[Appointment.Status.PROPOSED, Appointment.Status.CONFIRMED],
        scheduled_for__gt=timezone.now(),
        scheduled_for__lte=timezone.now() + timedelta(days=7),
    ).order_by('scheduled_for').select_related(
        'application__participant__user',
        'application__study',
        'site',
    )[:7]

    return {
        'organisation': org,
        'active_studies': studies.count(),
        'high_priority': high_priority,
        'awaiting_review': awaiting_review,
        'screening_this_week': screening_appointments,
        'payouts_awaiting': payouts_awaiting,
        'under_review_apps': under_review_apps,
        'screening_list': screening_list,
    }
