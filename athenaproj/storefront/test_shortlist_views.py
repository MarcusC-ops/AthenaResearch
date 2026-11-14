from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from core.models import (
    Organisation,
    ParticipantProfile,
    Region,
    Site,
    Study,
    StudyCategory,
)
from core.services import add_to_shortlist


class ShortlistViewTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        region = Region.objects.create(code='W', name='West', display_order=1)
        category = StudyCategory.objects.create(
            name='Sleep',
            slug='sleep',
            ml_label='sleep',
            description='Explore sleep research.',
            display_order=1,
        )
        organisation = Organisation.objects.create(
            name='Kent Ridge Clinical Research Centre',
            org_type=Organisation.OrganisationType.UNIVERSITY,
            contact_person='Daniel Lim',
            contact_email='drlim@example.sg',
        )
        site = Site.objects.create(
            organisation=organisation,
            name='Kent Ridge CRC',
            address='21 Lower Kent Ridge Road',
            postal_code='119077',
            region=region,
        )
        defaults = {
            'organisation': organisation,
            'category': category,
            'description': 'A plain-language study about health.',
            'study_type': Study.StudyType.OBSERVATIONAL,
            'accepts_healthy_volunteers': True,
            'min_age': 21,
            'max_age': 65,
            'target_enrolment': 30,
            'total_visits': 2,
            'duration_weeks': 8,
            'visit_times': Study.VisitTimes.FLEXIBLE,
            'compensation_amount': '100.00',
            'show_compensation': True,
            'start_date': timezone.localdate(),
            'recruitment_deadline': timezone.localdate() + timedelta(days=30),
            'status': Study.Status.PUBLISHED,
            'published_at': timezone.now(),
        }
        cls.studies = []
        for title in (
            'Sleep Habits Study',
            'Calm Minds Trial',
            'Midlife Heart Study',
            'Asthma Inhaler Trial',
        ):
            study = Study.objects.create(title=title, **defaults)
            study.sites.add(site)
            cls.studies.append(study)
        draft = Study.objects.create(
            title='Draft Diet Study',
            status=Study.Status.DRAFT,
            published_at=None,
            **{
                key: value
                for key, value in defaults.items()
                if key not in {'status', 'published_at'}
            },
        )
        draft.sites.add(site)

        cls.user = User.objects.create_user(
            username='aisyah@example.com',
            email='aisyah@example.com',
            first_name='Aisyah',
            password='Kopi-Teh-2026!',
        )
        cls.user.groups.add(cls.user.groups.model.objects.get(name='Participant'))
        cls.profile = ParticipantProfile.objects.create(
            user=cls.user,
            mobile='+6591234567',
            terms_accepted_at=timezone.now(),
            onboarding_completed_at=timezone.now(),
            date_of_birth=timezone.localdate().replace(
                year=timezone.localdate().year - 30
            ),
            sex=ParticipantProfile.Sex.FEMALE,
            region=region,
            height_cm='165.0',
            weight_kg='60.0',
        )

    def test_01_signed_out_add_redirects_to_sign_in(self):
        response = self.client.post('/shortlist/add/1/')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.url,
            '/accounts/login/?next=/shortlist/add/1/',
        )

    def test_02_participant_add_shows_header_count(self):
        self.client.login(username='aisyah@example.com', password='Kopi-Teh-2026!')
        response = self.client.post('/shortlist/add/1/')
        self.assertEqual(response.status_code, 302)
        response = self.client.get(response.url)
        self.assertContains(response, 'Shortlist (1)')

    def test_03_get_add_is_not_allowed(self):
        self.assertEqual(self.client.get('/shortlist/add/1/').status_code, 405)

    def test_04_compare_shows_two_studies(self):
        self.client.login(username='aisyah@example.com', password='Kopi-Teh-2026!')
        self.client.post('/shortlist/add/1/')
        self.client.post('/shortlist/add/2/')
        response = self.client.get('/shortlist/compare/?ids=1&ids=2')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Study type')
        self.assertContains(response, 'Sleep Habits Study')
        self.assertContains(response, 'Calm Minds Trial')

    def test_05_compare_one_redirects_with_message(self):
        self.client.login(username='aisyah@example.com', password='Kopi-Teh-2026!')
        response = self.client.get('/shortlist/compare/?ids=1', follow=True)
        self.assertEqual(response.redirect_chain, [('/shortlist/', 302)])
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Choose two or three studies')

    def test_06_empty_shortlist_shows_empty_state(self):
        self.client.login(username='aisyah@example.com', password='Kopi-Teh-2026!')
        response = self.client.get('/shortlist/')
        self.assertContains(response, 'Your shortlist is empty.')

    def test_07_added_study_page_shows_remove_action(self):
        self.client.login(username='aisyah@example.com', password='Kopi-Teh-2026!')
        self.client.post('/shortlist/add/1/')
        response = self.client.get('/studies/sleep-habits-study/')
        self.assertContains(response, 'Remove from shortlist')
