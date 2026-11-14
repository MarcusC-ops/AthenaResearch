from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from core.models import Organisation, Region, Site, Study, StudyCategory


class CatalogueViewsTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        region_w = Region.objects.create(code='W', name='West', display_order=1)
        region_c = Region.objects.create(code='C', name='Central', display_order=2)
        sleep = StudyCategory.objects.create(
            name='Sleep',
            slug='sleep',
            ml_label='sleep',
            description='Explore sleep research.',
            display_order=1,
        )
        mental_health = StudyCategory.objects.create(
            name='Mental Health',
            slug='mental-health',
            ml_label='mental_health',
            description='Explore mental health research.',
            display_order=2,
        )
        organisation = Organisation.objects.create(
            name='Kent Ridge Clinical Research Centre',
            org_type=Organisation.OrganisationType.UNIVERSITY,
            contact_person='Daniel Lim',
            contact_email='drlim@example.sg',
        )
        site_a = Site.objects.create(
            organisation=organisation,
            name='Site A',
            address='1 West Road',
            postal_code='119077',
            region=region_w,
        )
        site_b = Site.objects.create(
            organisation=organisation,
            name='Site B',
            address='1 Central Road',
            postal_code='179077',
            region=region_c,
        )
        common = {
            'organisation': organisation,
            'description': 'A plain-language study description.',
            'min_age': 21,
            'max_age': 65,
            'target_enrolment': 30,
            'visit_times': Study.VisitTimes.FLEXIBLE,
            'start_date': timezone.localdate(),
            'recruitment_deadline': timezone.localdate() + timedelta(days=30),
        }

        cls.sleep_study = Study.objects.create(
            title='Sleep Habits Study',
            category=sleep,
            study_type=Study.StudyType.OBSERVATIONAL,
            duration_weeks=8,
            total_visits=4,
            compensation_amount='120.00',
            show_compensation=True,
            accepts_healthy_volunteers=True,
            status=Study.Status.PUBLISHED,
            published_at=timezone.now(),
            **common,
        )
        cls.sleep_study.sites.add(site_a)
        cls.calm_study = Study.objects.create(
            title='Calm Minds Trial',
            category=mental_health,
            study_type=Study.StudyType.INTERVENTIONAL,
            phase=Study.Phase.PHASE_2,
            duration_weeks=12,
            total_visits=2,
            compensation_amount='300.00',
            show_compensation=True,
            accepts_healthy_volunteers=False,
            status=Study.Status.PUBLISHED,
            published_at=timezone.now() - timedelta(days=1),
            **common,
        )
        cls.calm_study.sites.add(site_b)
        cls.night_study = Study.objects.create(
            title='Night Shift Sleep Study',
            category=sleep,
            study_type=Study.StudyType.BEHAVIOURAL,
            duration_weeks=4,
            total_visits=2,
            compensation_amount='50.00',
            show_compensation=False,
            accepts_healthy_volunteers=False,
            status=Study.Status.FULL,
            published_at=timezone.now() - timedelta(days=2),
            **common,
        )
        cls.night_study.sites.add(site_a)
        draft = Study.objects.create(
            title='Draft Diet Study',
            category=sleep,
            study_type=Study.StudyType.OBSERVATIONAL,
            duration_weeks=8,
            total_visits=2,
            compensation_amount='80.00',
            show_compensation=True,
            accepts_healthy_volunteers=False,
            status=Study.Status.DRAFT,
            published_at=None,
            **common,
        )
        draft.sites.add(site_a)
        for index in range(1, 11):
            filler = Study.objects.create(
                title=f'Filler Study {index}',
                category=sleep,
                study_type=Study.StudyType.OBSERVATIONAL,
                duration_weeks=2,
                total_visits=2,
                compensation_amount='0.00',
                show_compensation=True,
                accepts_healthy_volunteers=False,
                status=Study.Status.PUBLISHED,
                published_at=timezone.now() - timedelta(days=index + 2),
                **common,
            )
            filler.sites.add(site_a)

    def test_01_catalogue_lists_public_studies_only(self):
        response = self.client.get('/studies/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Sleep Habits Study')
        self.assertNotContains(response, 'Draft Diet Study')

    def test_02_keyword_filter_lists_calm_trial_only(self):
        response = self.client.get('/studies/?q=calm')

        self.assertContains(response, 'Calm Minds Trial')
        self.assertNotContains(response, 'Sleep Habits Study')

    def test_03_type_filter_lists_calm_trial_only(self):
        response = self.client.get('/studies/?type=interventional')

        self.assertContains(response, 'Calm Minds Trial')
        self.assertNotContains(response, 'Sleep Habits Study')

    def test_04_compensation_filter_lists_calm_trial_only(self):
        response = self.client.get('/studies/?comp=300')

        self.assertContains(response, 'Calm Minds Trial')
        self.assertNotContains(response, 'Night Shift Sleep Study')

    def test_05_region_filter_lists_calm_trial_only(self):
        response = self.client.get('/studies/?region=C')

        self.assertContains(response, 'Calm Minds Trial')
        self.assertNotContains(response, 'Sleep Habits Study')

    def test_06_long_duration_filter_is_empty(self):
        response = self.client.get('/studies/?duration=long')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No studies match these filters.')

    def test_07_title_sort_paginates_and_preserves_filters(self):
        response = self.client.get('/studies/?sort=title')

        self.assertEqual(len(response.context['page_obj'].object_list), 12)
        self.assertContains(response, 'href="?sort=title&page=2"')

    def test_08_invalid_region_and_page_are_tolerated(self):
        response = self.client.get('/studies/?region=ZZ&page=abc')

        self.assertEqual(response.status_code, 200)

    def test_09_sleep_study_detail_shows_key_facts(self):
        response = self.client.get('/studies/sleep-habits-study/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Key facts')
        self.assertContains(response, '$120')

    def test_10_full_study_hides_compensation_amount(self):
        response = self.client.get('/studies/night-shift-sleep-study/')

        self.assertContains(response, 'Compensation for time and travel is provided')
        self.assertContains(response, 'Full')

    def test_11_draft_study_returns_not_found(self):
        response = self.client.get('/studies/draft-diet-study/')

        self.assertEqual(response.status_code, 404)
