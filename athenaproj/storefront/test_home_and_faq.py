from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from core.models import Organisation, Region, Site, Study, StudyCategory
from core.services import category_tiles, popular_studies


class HomeAndFaqTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        region = Region.objects.create(code='W', name='West', display_order=1)
        sleep = StudyCategory.objects.create(
            name='Sleep',
            slug='sleep',
            ml_label='sleep',
            description='Explore sleep research.',
            display_order=8,
        )
        cognitive = StudyCategory.objects.create(
            name='Cognitive',
            slug='cognitive',
            ml_label='cognitive',
            description='Explore cognitive research.',
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
            name='Site A',
            address='1 West Road',
            postal_code='119077',
            region=region,
        )
        common = {
            'organisation': organisation,
            'description': 'A plain-language study description.',
            'study_type': Study.StudyType.OBSERVATIONAL,
            'min_age': 21,
            'max_age': 65,
            'target_enrolment': 30,
            'total_visits': 2,
            'duration_weeks': 2,
            'visit_times': Study.VisitTimes.FLEXIBLE,
            'compensation_amount': '80.00',
            'show_compensation': True,
            'accepts_healthy_volunteers': False,
            'start_date': timezone.localdate(),
            'recruitment_deadline': timezone.localdate() + timedelta(days=30),
            'status': Study.Status.PUBLISHED,
        }
        for index in range(1, 9):
            study = Study.objects.create(
                title=f'Sleep Study {index}',
                category=sleep,
                published_at=timezone.now() - timedelta(days=index - 1),
                **common,
            )
            study.sites.add(site)
        draft = Study.objects.create(
            title='Cognitive Draft Study',
            category=cognitive,
            status=Study.Status.DRAFT,
            published_at=None,
            **{
                key: value
                for key, value in common.items()
                if key not in {'status'}
            },
        )
        draft.sites.add(site)

    def test_01_homepage_shows_heading_and_category_section(self):
        response = self.client.get('/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Be part of the next Health Discovery')
        self.assertContains(response, 'Explore by category')

    def test_02_category_tiles_count_public_studies_only(self):
        response = self.client.get('/')

        self.assertContains(response, '8 studies')
        self.assertContains(response, '0 studies')

    def test_03_category_tiles_are_in_display_order(self):
        self.assertEqual(
            list(category_tiles().values_list('name', flat=True)),
            ['Cognitive', 'Sleep'],
        )

    def test_04_popular_studies_returns_six_newest_first(self):
        studies = list(popular_studies())

        self.assertEqual(len(studies), 6)
        self.assertEqual(studies[0].title, 'Sleep Study 1')
        self.assertEqual(studies[-1].title, 'Sleep Study 6')

    def test_05_faq_page_shows_heading_and_withdrawal_question(self):
        response = self.client.get('/support/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Questions and answers')
        self.assertContains(response, 'Can I withdraw?')

    def test_06_admin_route_is_not_found(self):
        self.assertEqual(self.client.get('/admin/').status_code, 404)
