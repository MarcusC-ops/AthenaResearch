"""All Athena business logic lives here. Views call these functions."""

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
    ).order_by('-published_at')


def get_public_study(slug):
    return public_studies().get(slug=slug)


def get_study(study_id):
    return Study.objects.get(pk=study_id)
