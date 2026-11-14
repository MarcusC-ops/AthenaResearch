from datetime import date, timedelta

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Condition, Organisation, ParticipantProfile, Region


class OnboardingViewsTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.region_w = Region.objects.create(code='W', name='West', display_order=1)
        cls.asthma = Condition.objects.create(name='Asthma', ml_flag='respiratory')
        cls.insomnia = Condition.objects.create(name='Insomnia', ml_flag='sleep')
        cls.organisation = Organisation.objects.create(
            name='Kent Ridge Test Organisation', org_type='university',
            contact_person='Daniel Lim', contact_email='drlim@example.com',
        )
        cls.aisyah = User.objects.create_user(
            username='aisyah@example.com', email='aisyah@example.com',
            first_name='Aisyah', last_name='Rahman', password='Kopi-Teh-2026!',
        )
        cls.aisyah.groups.add(Group.objects.get(name='Participant'))
        cls.profile = ParticipantProfile.objects.create(
            user=cls.aisyah, mobile='+6591234567', terms_accepted_at=timezone.now(),
        )
        cls.coordinator = User.objects.create_user(
            username='drlim@kentridge-crc.sg', email='drlim@kentridge-crc.sg',
            password='Kopi-Teh-2026!',
        )
        cls.coordinator.groups.add(Group.objects.get(name='Coordinator'))

    def valid_form(self):
        return {
            'date_of_birth': (date.today() - timedelta(days=365 * 24)).isoformat(),
            'sex': 'female', 'region': str(self.region_w.pk), 'ethnicity': 'prefer_not',
            'employment': 'student', 'education': 'degree',
            'height_cm': '160.0', 'weight_kg': '52.0',
            'activity_level': 'low', 'smoker': '',
            'motivation': 'help_research', 'availability': 'weekday_evenings',
            'max_travel_minutes': '30', 'consent_matching': 'on',
            'consent_insights': '', 'consent_contact': '',
            'conditions': [],
        }

    def test_01_signed_out_onboarding_redirects_to_sign_in(self):
        response = self.client.get('/onboarding/')
        self.assertRedirects(response, '/accounts/login/?next=/onboarding/')

    def test_02_onboarding_shows_form_sections(self):
        self.client.force_login(self.aisyah)
        response = self.client.get('/onboarding/')
        self.assertContains(response, 'Tell us about yourself')
        self.assertContains(response, 'About you')
        self.assertContains(response, 'Health basics')
        self.assertContains(response, 'Preferences and consents')

    def test_03_valid_onboarding_saves_profile(self):
        self.client.force_login(self.aisyah)
        response = self.client.post('/onboarding/', self.valid_form())
        self.assertRedirects(response, '/account/')
        self.profile.refresh_from_db()
        self.assertIsNotNone(self.profile.onboarding_completed_at)
        self.assertEqual(str(self.profile.bmi), '20.3')

    def test_04_too_young_dob_is_rejected(self):
        self.client.force_login(self.aisyah)
        data = self.valid_form()
        data['date_of_birth'] = (date.today() - timedelta(days=365 * 20)).isoformat()
        response = self.client.post('/onboarding/', data)
        self.assertContains(response, 'You must be at least 21 to join Athena.')
        self.profile.refresh_from_db()
        self.assertIsNone(self.profile.onboarding_completed_at)

    def test_05_invalid_height_is_rejected(self):
        self.client.force_login(self.aisyah)
        data = self.valid_form()
        data['height_cm'] = '300'
        response = self.client.post('/onboarding/', data)
        self.assertContains(response, 'Enter a height between 120 and 220 cm.')

    def test_06_saved_profile_is_shown_on_both_pages(self):
        self.client.force_login(self.aisyah)
        self.client.post('/onboarding/', self.valid_form())
        self.assertContains(self.client.get('/account/'), 'BMI 20.3')
        self.assertContains(self.client.get('/account/'), 'Edit profile')
        self.assertContains(self.client.get('/onboarding/'), 'Edit your profile')

    def test_07_coordinator_is_forbidden(self):
        self.client.force_login(self.coordinator)
        self.assertEqual(self.client.get('/onboarding/').status_code, 403)
