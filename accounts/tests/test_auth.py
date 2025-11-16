from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

User = get_user_model()


class AuthFlowTests(TestCase):
    def setUp(self):
        self.register_url = reverse("accounts:register")
        self.login_url = reverse("accounts:login")
        self.logout_url = reverse("accounts:logout")
        self.dashboard_url = reverse("trading:dashboard")

    def test_register_page_renders_without_username_field(self):
        resp = self.client.get(self.register_url)
        assert resp.status_code == 200
        # Ensure the form does not render a username input
        assert 'name="username"' not in resp.content.decode()

    def test_register_success_creates_user_and_logs_in(self):
        data = {
            "email": "newuser@example.com",
            "first_name": "New",
            "last_name": "User",
            "password1": "StrongPass!234",
            "password2": "StrongPass!234",
        }
        resp = self.client.post(self.register_url, data, follow=True)
        # Should redirect to dashboard
        self.assertRedirects(resp, self.dashboard_url)
        # User exists
        assert User.objects.filter(email="newuser@example.com").exists()
        # Client is authenticated
        assert resp.context["user"].is_authenticated

    def test_register_invalid_missing_email_shows_error(self):
        data = {
            "email": "",
            "first_name": "A",
            "last_name": "B",
            "password1": "StrongPass!234",
            "password2": "StrongPass!234",
        }
        resp = self.client.post(self.register_url, data)
        assert resp.status_code == 200
        self.assertContains(resp, "Email is required")

    def test_login_success_with_email(self):
        user = User.objects.create_user(
            email="loginuser@example.com",
            username="loginuser@example.com",
            password="StrongPass!234",
        )
        resp = self.client.post(
            self.login_url, {"username": user.email, "password": "StrongPass!234"}
        )
        assert resp.status_code == 302
        assert resp.url == self.dashboard_url

    def test_login_invalid_credentials(self):
        User.objects.create_user(
            email="badlogin@example.com",
            username="badlogin@example.com",
            password="CorrectPass!234",
        )
        resp = self.client.post(
            self.login_url, {"username": "badlogin@example.com", "password": "wrong"}
        )
        # Should re-render with errors
        assert resp.status_code == 200
        self.assertContains(resp, "Please enter a correct")

    def test_logout_requires_post(self):
        user = User.objects.create_user(
            email="willlogout@example.com",
            username="willlogout@example.com",
            password="StrongPass!234",
        )
        self.client.login(username=user.email, password="StrongPass!234")
        # GET should not be allowed (405)
        resp_get = self.client.get(self.logout_url)
        assert resp_get.status_code == 405

    def test_logout_post_logs_out(self):
        user = User.objects.create_user(
            email="postlogout@example.com",
            username="postlogout@example.com",
            password="StrongPass!234",
        )
        self.client.login(username=user.email, password="StrongPass!234")
        resp = self.client.post(self.logout_url, follow=True)
        # Redirects to home
        assert resp.status_code == 200
        assert not resp.context["user"].is_authenticated
