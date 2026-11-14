"""All Athena business logic lives here. Views call these functions."""

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
