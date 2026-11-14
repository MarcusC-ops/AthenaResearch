from datetime import date, timedelta

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.utils import timezone

from core.models import (
    Organisation, ParticipantProfile, PredictionLog, Region, Site, Study, StudyCategory,
)


class ForYouViewsTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.region_w = Region.objects.create(code='W', name='West', display_order=1)
        cls.region_c = Region.objects.create(code='C', name='Central', display_order=2)
        labels = [
            'cognitive', 'healthy_phase1', 'heart', 'lifestyle', 'mental_health',
            'metabolic', 'respiratory', 'sleep', 'womens_health',
        ]
        names = {
            'sleep': 'Sleep',
            'mental_health': 'Mental Health',
            'heart': 'Heart and Blood Pressure',
        }
        cls.categories = {}
        for order, label in enumerate(labels, 1):
            cls.categories[label] = StudyCategory.objects.create(
                name=names.get(label, label.replace('_', ' ').title()),
                slug=label, ml_label=label, description=f'{label} research.',
                display_order=order,
            )
        cls.organisation = Organisation.objects.create(
            name='Test Organisation', org_type='university',
            contact_person='Test Contact', contact_email='test@example.com',
        )
        cls.site_w = Site.objects.create(
            organisation=cls.organisation, name='W1', address='1 West Road',
            postal_code='123456', region=cls.region_w,
        )
        cls.site_c = Site.objects.create(
            organisation=cls.organisation, name='C1', address='1 Central Road',
            postal_code='123457', region=cls.region_c,
        )
        cls.aisyah = User.objects.create_user(
            username='aisyah@example.com', email='aisyah@example.com',
            first_name='Aisyah', last_name='Rahman', password='Kopi-Teh-2026!',
        )
        cls.aisyah.groups.add(Group.objects.get(name='Participant'))
        cls.profile = ParticipantProfile.objects.create(
            user=cls.aisyah, mobile='+6591234567', terms_accepted_at=timezone.now(),
            date_of_birth=date.today().replace(year=date.today().year - 24),
            sex='female', region=cls.region_w, employment='student',
            education='degree', height_cm='160.0', weight_kg='52.0',
            activity_level='high', motivation='help_research',
            availability='weekday_evenings', max_travel_minutes='30',
            consent_matching=True, onboarding_completed_at=timezone.now(),
            ml1_categories=['mental_health', 'sleep', 'heart'],
        )
        common = {
            'organisation': cls.organisation, 'description': 'A study.',
            'study_type': 'observational', 'accepts_healthy_volunteers': True,
            'min_age': 21, 'max_age': 65, 'target_enrolment': 10,
            'total_visits': 1, 'duration_weeks': 1, 'visit_times': 'flexible',
            'compensation_amount': '10.00', 'show_compensation': True,
            'start_date': date.today(), 'status': 'published',
            'published_at': timezone.now(),
        }
        cls.studies = {}
        for title, category, site, days in (
            ('Sleep Habits Study', 'sleep', cls.site_w, 40),
            ('Calm Minds Trial', 'mental_health', cls.site_c, 30),
            ('Night Owls Study', 'sleep', cls.site_c, 10),
        ):
            study = Study.objects.create(
                **common, category=cls.categories[category], title=title,
                recruitment_deadline=date.today() + timedelta(days=days),
            )
            study.sites.add(site)
            cls.studies[title] = study
        cls.midlife = Study.objects.create(
            **{**common, 'min_age': 40},
            category=cls.categories['heart'], title='Midlife Heart Study',
            recruitment_deadline=date.today() + timedelta(days=20),
        )
        cls.midlife.sites.add(cls.site_w)
        cls.new_user = User.objects.create_user(
            username='new@example.com', email='new@example.com',
            password='Kopi-Teh-2026!',
        )
        cls.new_user.groups.add(Group.objects.get(name='Participant'))
        cls.new_profile = ParticipantProfile.objects.create(
            user=cls.new_user, mobile='+6581234567', terms_accepted_at=timezone.now(),
        )

    def valid_onboarding_form(self):
        return {
            'date_of_birth': (date.today() - timedelta(days=365 * 24)).isoformat(),
            'sex': 'female', 'region': str(self.region_w.pk), 'ethnicity': 'prefer_not',
            'employment': 'student', 'education': 'degree', 'height_cm': '160.0',
            'weight_kg': '52.0', 'activity_level': 'high', 'smoker': '',
            'conditions': [], 'motivation': 'help_research',
            'availability': 'weekday_evenings', 'max_travel_minutes': '30',
            'consent_matching': 'on', 'consent_insights': '', 'consent_contact': '',
        }

    def test_01_for_you_orders_eligible_studies(self):
        from core.services import for_you_feed
        self.profile.refresh_from_db()
        feed = for_you_feed(self.profile)
        self.assertEqual(
            [item['study'].title for item in feed['items']],
            ['Calm Minds Trial', 'Sleep Habits Study', 'Night Owls Study'],
        )
        self.client.force_login(self.aisyah)
        self.assertNotContains(self.client.get('/for-you/'), 'Midlife Heart Study')

    def test_02_for_you_shows_reasons_without_probabilities(self):
        self.client.force_login(self.aisyah)
        response = self.client.get('/for-you/')
        self.assertContains(response, 'Matches your interest in Mental Health')
        self.assertContains(response, 'Related to your interest in Sleep')
        self.assertContains(response, 'Site in the West region')
        self.assertNotContains(response, '%')
        self.assertNotContains(response, 'probability')

    def test_03_for_you_marks_studies_closing_soon(self):
        self.client.force_login(self.aisyah)
        self.assertContains(self.client.get('/for-you/'), 'Closing soon')

    def test_04_for_you_does_not_create_prediction_log(self):
        self.client.force_login(self.aisyah)
        self.client.get('/for-you/')
        self.assertEqual(PredictionLog.objects.count(), 0)

    def test_05_for_you_consent_off_shows_recommendation_notice(self):
        self.profile.consent_matching = False
        self.profile.save(update_fields=['consent_matching'])
        self.client.force_login(self.aisyah)
        response = self.client.get('/for-you/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Turn on recommendations')

    def test_06_for_you_without_prediction_shows_fallback_notice(self):
        self.profile.ml1_categories = []
        self.profile.save(update_fields=['ml1_categories'])
        self.client.force_login(self.aisyah)
        self.assertContains(
            self.client.get('/for-you/'),
            'We could not pick studies for you just now',
        )

    def test_07_home_shows_personal_row_only_when_signed_in(self):
        self.client.force_login(self.aisyah)
        self.assertContains(self.client.get('/'), 'Studies for you')
        self.client.logout()
        self.assertNotContains(self.client.get('/'), 'Studies for you')

    def test_08_unonboarded_participant_is_sent_to_onboarding(self):
        self.client.force_login(self.new_user)
        self.assertRedirects(self.client.get('/for-you/'), '/onboarding/')

    def test_09_onboarding_prediction_redirects_and_logs(self):
        self.client.force_login(self.new_user)
        response = self.client.post('/onboarding/', self.valid_onboarding_form())
        self.assertRedirects(response, '/for-you/')
        self.assertEqual(
            PredictionLog.objects.filter(participant=self.new_profile).count(), 1
        )
