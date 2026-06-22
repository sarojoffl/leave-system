def get_view_mode(request):
    if not request.user.has_management_access:
        return 'employee'
    return request.session.get('view_mode', 'manager')