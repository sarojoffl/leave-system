def get_view_mode(request):
    if request.user.role not in ('manager', 'hr'):
        return 'employee'
    return request.session.get('view_mode', 'manager')