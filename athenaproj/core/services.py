"""All Athena business logic lives here. Views call these functions."""

from dataclasses import dataclass
from datetime import timedelta
from django.contrib.auth.models import Group, User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Case, Count, Q, Value, When
from django.utils import timezone

from .models import (
    Condition,
    Notification,
    Organisation,
    ParticipantProfile,
    PredictionLog,
    Region,
    StaffProfile,
    Study,
    StudyCategory,
)
from .validators import normalise_sg_mobile


def list_regions():
    return Region.objects.order_by('display_order')


def list_active_categories():
    return StudyCategory.objects.filter(is_active=True).order_by('display_order')


def list_active_conditions():
    return Condition.objects.filter(is_active=True).order_by('name')


def public_studies():
    return Study.objects.filter(
        status__in=[Study.Status.PUBLISHED, Study.Status.FULL]
    ).order_by('-published_at', '-id')


def get_public_study(slug):
    return public_studies().get(slug=slug)


def get_study(study_id):
    return Study.objects.get(pk=study_id)


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


def popular_studies(limit=6):
    """Return newest public studies for now; increment 8 changes it."""
    return search_studies(sort='newest')[:limit]


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
        results.append(RuleResult(
            'bmi', 'BMI', f'BMI {minimum} to {maximum} (yours is {profile.bmi}).',
            profile.bmi is not None
            and (study.min_bmi is None or profile.bmi >= study.min_bmi)
            and (study.max_bmi is None or profile.bmi <= study.max_bmi),
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
