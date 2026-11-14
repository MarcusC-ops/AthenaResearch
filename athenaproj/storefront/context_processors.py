from core.services import shortlist_count


def participant_shortlist(request):
    profile = (
        request.user.participant_profile
        if request.user.is_authenticated
        and hasattr(request.user, 'participant_profile')
        else None
    )
    return {
        'shortlist_count': (
            shortlist_count(profile)
            if request.user.is_authenticated and profile is not None
            else 0
        ),
    }
