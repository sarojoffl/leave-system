from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

User = get_user_model()


class ProfileAndAuthTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser",
            password="oldpassword123",
            first_name="Test",
            last_name="User",
            email="testuser@example.com",
            role="employee",
            gender="male",
        )
        self.other_user = User.objects.create_user(
            username="otheruser",
            password="password123",
            first_name="Other",
            last_name="Person",
            email="other@example.com",
            role="employee",
        )

    def test_unauthenticated_profile_redirects_to_login(self):
        response = self.client.get(reverse("profile"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_user_can_view_profile(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("profile"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/profile.html")
        self.assertContains(response, "Test User")
        self.assertContains(response, "testuser@example.com")

    def test_user_can_update_profile(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("profile"), {
            "first_name": "UpdatedName",
            "last_name": "NewSurname",
            "email": "updated.email@example.com",
            "gender": "female",
        })
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("profile"))

        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "UpdatedName")
        self.assertEqual(self.user.last_name, "NewSurname")
        self.assertEqual(self.user.email, "updated.email@example.com")
        self.assertEqual(self.user.gender, "female")

    def test_profile_update_duplicate_email_fails(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("profile"), {
            "first_name": "Test",
            "last_name": "User",
            "email": "other@example.com",  # Already belongs to other_user
            "gender": "male",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already in use")
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "testuser@example.com")

    def test_password_reset_by_email_sends_email(self):
        mail.outbox.clear()
        response = self.client.post(reverse("password_reset"), {
            "email": "testuser@example.com",
        })
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("password_reset_done"))

        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertEqual(email.to, ["testuser@example.com"])
        self.assertIn("Reset", email.subject)
        self.assertIn("password-reset-confirm", email.body)

    def test_password_reset_by_username_sends_email(self):
        mail.outbox.clear()
        response = self.client.post(reverse("password_reset"), {
            "email": "testuser",  # Username lookup
        })
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("password_reset_done"))

        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertEqual(email.to, ["testuser@example.com"])

    def test_password_reset_confirm_and_complete(self):
        uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        token = default_token_generator.make_token(self.user)

        confirm_url = reverse("password_reset_confirm", kwargs={"uidb64": uid, "token": token})

        # GET confirm page (follows Django session token redirect to .../set-password/)
        response = self.client.get(confirm_url, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/password_reset_confirm.html")

        # POST new password to the active session form URL
        post_url = response.redirect_chain[0][0]
        response = self.client.post(post_url, {
            "new_password1": "brandnewpassword456",
            "new_password2": "brandnewpassword456",
        })
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("password_reset_complete"))

        # Verify password updated
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("brandnewpassword456"))
