from django.contrib.auth import authenticate, get_user_model, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib import messages
from django.shortcuts import render, redirect

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
 
from leaves.models import LeaveBalance
from leaves.permissions import manager_required


User = get_user_model()


def _post_login_redirect_name(user):
    return 'manager_dashboard' if user.role in ('manager', 'hr') else 'dashboard'


def login_view(request):
    if request.user.is_authenticated:
        return redirect(_post_login_redirect_name(request.user))

    error = None
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            next_url = request.GET.get("next")
            return redirect(next_url or _post_login_redirect_name(user))
        else:
            # Check if the account exists but is just inactive
            try:
                candidate = User.objects.get(username=username)
                if not candidate.is_active:
                    error = "This account has been deactivated. Please contact your manager or HR."
                else:
                    error = "Invalid username or password."
            except User.DoesNotExist:
                error = "Invalid username or password."

    return render(request, "accounts/login.html", {"error": error})


def logout_view(request):
    logout(request)
    return redirect("login")


@login_required
def change_password_view(request):
    if request.method == 'POST':
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)
            messages.success(request, 'Your password was successfully updated!')
            return redirect(_post_login_redirect_name(request.user))
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = PasswordChangeForm(request.user)
    return render(request, 'accounts/change_password.html', {'form': form})
 
 
def _user_form_data(post):
    """Extract and lightly validate staff form fields. Returns (data, errors)."""
    data = {
        "first_name": post.get("first_name", "").strip(),
        "last_name": post.get("last_name", "").strip(),
        "username": post.get("username", "").strip(),
        "email": post.get("email", "").strip(),
        "department": post.get("department", "").strip(),
        "position": post.get("position", "").strip(),
        "role": post.get("role", "employee").strip(),
    }
    errors = []
 
    if not data["first_name"]:
        errors.append("First name is required.")
    if not data["last_name"]:
        errors.append("Last name is required.")
    if not data["username"]:
        errors.append("Username is required.")
    if data["role"] not in ("employee", "manager", "hr"):
        errors.append("Invalid role selected.")
 
    return data, errors
 
 
@manager_required
def staff_list(request):
    """List all staff with search/filter. Also handles account creation (POST)."""
 
    if request.method == "POST":
        data, errors = _user_form_data(request.POST)
        password = request.POST.get("password", "").strip()
        leave_total = request.POST.get("leave_total", "").strip()
 
        if not password:
            errors.append("A temporary password is required.")
        elif len(password) < 6:
            errors.append("Password must be at least 6 characters.")
 
        if not errors and User.objects.filter(username=data["username"]).exists():
            errors.append(f"Username '{data['username']}' is already taken.")
 
        if not errors and data["email"] and User.objects.filter(email=data["email"]).exists():
            errors.append(f"Email '{data['email']}' is already in use.")
 
        leave_total_int = 12
        if leave_total:
            try:
                leave_total_int = int(leave_total)
                if leave_total_int < 0:
                    errors.append("Leave allocation cannot be negative.")
            except ValueError:
                errors.append("Leave allocation must be a whole number.")
 
        if errors:
            for e in errors:
                messages.error(request, e)
        else:
            user = User.objects.create(
                username=data["username"],
                first_name=data["first_name"],
                last_name=data["last_name"],
                email=data["email"],
                department=data["department"],
                position=data["position"],
                role=data["role"],
                password=make_password(password),
                is_active=True,
            )
            LeaveBalance.objects.get_or_create(employee=user, defaults={"total": leave_total_int})
            messages.success(request, f"Account created for {user.get_full_name() or user.username}.")
            return redirect("staff_list")
 
    # --- list / search ---
    qs = User.objects.exclude(id=request.user.id).order_by("first_name", "last_name")
 
    q = request.GET.get("q", "").strip()
    filter_role = request.GET.get("role", "")
    filter_status = request.GET.get("status", "")
 
    if q:
        from django.db.models import Q
        qs = qs.filter(
            Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
            | Q(username__icontains=q)
            | Q(email__icontains=q)
            | Q(department__icontains=q)
            | Q(position__icontains=q)
        )
    if filter_role:
        qs = qs.filter(role=filter_role)
    if filter_status == "active":
        qs = qs.filter(is_active=True)
    elif filter_status == "inactive":
        qs = qs.filter(is_active=False)
 
    staff = []
    for u in qs:
        balance = LeaveBalance.objects.filter(employee=u).first()
        staff.append({
            "id": u.id,
            "name": u.get_full_name() or u.username,
            "username": u.username,
            "email": u.email or "—",
            "department": u.department or "—",
            "position": u.position or "—",
            "role": u.get_role_display(),
            "role_key": u.role,
            "is_active": u.is_active,
            "initials": u.initials,
            "leave_used": balance.used if balance else 0,
            "leave_total": balance.total if balance else 12,
            "leave_remaining": balance.remaining if balance else 12,
        })
 
    context = {
        "staff": staff,
        "active_count": sum(1 for s in staff if s["is_active"]),
        "inactive_count": sum(1 for s in staff if not s["is_active"]),
        "total_count": len(staff),
        "q": q,
        "filter_role": filter_role,
        "filter_status": filter_status,
    }
    return render(request, "accounts/staff_list.html", context)
 
 
@manager_required
def staff_edit(request, user_id):
    """Edit an existing staff member's profile, role, leave allocation, or password."""
    employee = get_object_or_404(User, id=user_id)
    balance = LeaveBalance.objects.filter(employee=employee).first()
 
    if request.method == "POST":
        action = request.POST.get("action", "edit")
 
        # --- password reset ---
        if action == "reset_password":
            new_pw = request.POST.get("new_password", "").strip()
            if not new_pw or len(new_pw) < 6:
                messages.error(request, "New password must be at least 6 characters.")
            else:
                employee.set_password(new_pw)
                employee.save(update_fields=["password"])
                messages.success(request, "Password updated.")
            return redirect("staff_edit", user_id=user_id)
 
        # --- profile edit ---
        data, errors = _user_form_data(request.POST)
        leave_total = request.POST.get("leave_total", "").strip()
 
        # username uniqueness — exclude current user
        if (
            not errors
            and data["username"] != employee.username
            and User.objects.filter(username=data["username"]).exists()
        ):
            errors.append(f"Username '{data['username']}' is already taken.")
 
        if (
            not errors
            and data["email"]
            and data["email"] != employee.email
            and User.objects.filter(email=data["email"]).exists()
        ):
            errors.append(f"Email '{data['email']}' is already in use.")
 
        leave_total_int = balance.total if balance else 12
        if leave_total:
            try:
                leave_total_int = int(leave_total)
                if leave_total_int < 0:
                    errors.append("Leave allocation cannot be negative.")
            except ValueError:
                errors.append("Leave allocation must be a whole number.")
 
        if errors:
            for e in errors:
                messages.error(request, e)
        else:
            employee.first_name = data["first_name"]
            employee.last_name = data["last_name"]
            employee.username = data["username"]
            employee.email = data["email"]
            employee.department = data["department"]
            employee.position = data["position"]
            employee.role = data["role"]
            employee.save(update_fields=[
                "first_name", "last_name", "username", "email",
                "department", "position", "role",
            ])
 
            if balance:
                balance.total = leave_total_int
                balance.save(update_fields=["total"])
            else:
                LeaveBalance.objects.create(employee=employee, total=leave_total_int)
 
            messages.success(request, "Profile updated.")
            return redirect("staff_edit", user_id=user_id)
 
    context = {
        "employee": employee,
        "balance": balance,
    }
    return render(request, "accounts/staff_edit.html", context)
 
 
@manager_required
@require_POST
def staff_toggle_active(request, user_id):
    """Activate or deactivate a staff account."""
    employee = get_object_or_404(User, id=user_id)
 
    if employee == request.user:
        messages.error(request, "You cannot deactivate your own account.")
        return redirect("staff_list")
 
    employee.is_active = not employee.is_active
    employee.save(update_fields=["is_active"])
 
    action = "reactivated" if employee.is_active else "deactivated"
    messages.success(request, f"Account {action} for {employee.get_full_name() or employee.username}.")
 
    # Return to edit page if that's where the request came from, else list
    next_url = request.POST.get("next", "staff_list")
    if next_url == "staff_edit":
        return redirect("staff_edit", user_id=user_id)
    return redirect("staff_list")