from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import PasswordResetForm
from django.core.exceptions import ValidationError

User = get_user_model()


class UserProfileForm(forms.ModelForm):
    first_name = forms.CharField(
        max_length=150,
        required=True,
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "Enter your first name",
            "id": "first_name",
        })
    )
    last_name = forms.CharField(
        max_length=150,
        required=True,
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "Enter your last name",
            "id": "last_name",
        })
    )
    email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(attrs={
            "class": "form-control",
            "placeholder": "name@example.com",
            "id": "email",
        })
    )
    gender = forms.ChoiceField(
        choices=[("", "Select Gender")] + list(User.GENDER_CHOICES),
        required=False,
        widget=forms.Select(attrs={
            "class": "form-control",
            "id": "gender",
        })
    )

    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "gender"]

    def clean_email(self):
        email = self.cleaned_data.get("email", "").strip()
        if email:
            qs = User.objects.filter(email__iexact=email)
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise ValidationError("This email address is already in use by another account.")
        return email


from django.db.models import Q


class CustomPasswordResetForm(PasswordResetForm):
    email = forms.CharField(
        label="Email or Username",
        max_length=254,
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "Enter your registered email or username",
            "id": "id_email",
            "autocomplete": "email",
            "autofocus": True,
        })
    )

    def clean_email(self):
        val = self.cleaned_data["email"].strip()
        return val

    def get_users(self, email):
        """Allow lookup by either email or username."""
        email_clean = email.strip()
        # Look up by email (case-insensitive) or username (case-insensitive)
        users = User._default_manager.filter(
            Q(email__iexact=email_clean) | Q(username__iexact=email_clean),
            is_active=True,
        )
        return [u for u in users if u.has_usable_password() and u.email]

