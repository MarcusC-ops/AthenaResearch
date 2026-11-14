from core.services import unread_count
from core.services import user_role


def panel_notifications(request):
    return {
        'panel_unread_count': (
            unread_count(request.user) if request.user.is_authenticated else 0
        ),
        'user_role': user_role(request.user) if request.user.is_authenticated else None,
    }
