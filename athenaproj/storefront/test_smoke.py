from django.conf import settings
from django.test import TestCase
from django.urls import reverse


class ProjectSkeletonSmokeTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

    def test_01_homepage_renders_heading(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Be part of the next Health Discovery")

    def test_02_panel_dashboard_route(self):
        self.assertEqual(reverse("adminpanel:dashboard"), "/panel/")
        self.assertNotEqual(self.client.get("/panel/").status_code, 404)

    def test_03_admin_route_is_not_found(self):
        self.assertEqual(self.client.get("/admin/").status_code, 404)

    def test_04_project_locale_and_timezone_settings(self):
        self.assertEqual(settings.TIME_ZONE, "Asia/Singapore")
        self.assertEqual(settings.LANGUAGE_CODE, "en-gb")
        self.assertTrue(settings.USE_TZ)

    def test_05_django_admin_is_not_installed(self):
        self.assertNotIn("django.contrib.admin", settings.INSTALLED_APPS)

    def test_06_project_apps_are_installed(self):
        for app in ("core", "accounts", "storefront", "adminpanel", "ml"):
            with self.subTest(app=app):
                self.assertIn(app, settings.INSTALLED_APPS)

    def test_07_homepage_includes_bootstrap_and_custom_stylesheet(self):
        response = self.client.get("/")

        self.assertContains(response, "bootstrap@5.3")
        self.assertContains(response, "css/athena.css")
