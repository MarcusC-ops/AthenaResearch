"""All Athena business logic lives here. Views call these functions."""

from django.db.models import Case, Count, Q, Value, When

from .models import Condition, Region, Study, StudyCategory


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
