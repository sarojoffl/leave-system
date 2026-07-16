from leave_system import settings


def get_view_mode(request):
    if not request.user.has_management_access:
        return 'employee'
    return request.session.get('view_mode', 'manager')

def exclude_staff_movement_ineligible(queryset):
    """Filter out users who shouldn't appear in Staff Movement pickers."""
    excluded = getattr(settings, "STAFF_MOVEMENT_EXCLUDED_USERNAMES", [])
    if excluded:
        queryset = queryset.exclude(username__in=excluded)
    return queryset