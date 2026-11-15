from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.utils import timezone

from core.models import (
    Organisation,
    ParticipantProfile,
    PreScreenQuestion,
    Region,
    Site,
    StaffProfile,
    Study,
    StudyCategory,
)


class StudyListingViewTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.region = Region.objects.create(
            code='W',
            name='West',
            display_order=5,
        )
        cls.category = StudyCategory.objects.create(
            name='Sleep',
            slug='sleep',
            ml_label='sleep',
            description='Explore sleep research.',
            display_order=8,
        )
        cls.kent_ridge = Organisation.objects.create(
            name='Kent Ridge Clinical Research Centre',
            org_type=Organisation.OrganisationType.UNIVERSITY,
            contact_person='Daniel Lim',
            contact_email='drlim@kentridge-crc.sg',
        )
        cls.harbourfront = Organisation.objects.create(
            name='Harbourfront General Hospital',
            org_type=Organisation.OrganisationType.HOSPITAL,
            contact_person='Nurul Huda',
            contact_email='nurul@harbourfront.sg',
        )
        cls.k1 = Site.objects.create(
            organisation=cls.kent_ridge,
            name='K1',
            address='21 Lower Kent Ridge Road',
            postal_code='119077',
            region=cls.region,
        )
        cls.k2 = Site.objects.create(
            organisation=cls.kent_ridge,
            name='K2',
            address='1 Fusionopolis Way',
            postal_code='138632',
            region=cls.region,
        )
        cls.h1 = Site.objects.create(
            organisation=cls.harbourfront,
            name='H1',
            address='1 Maritime Square',
            postal_code='099253',
            region=cls.region,
        )

        coordinator_group = Group.objects.get(name='Coordinator')
        cls.drlim = User.objects.create_user(
            username='drlim@kentridge-crc.sg',
            email='drlim@kentridge-crc.sg',
            first_name='Daniel',
            last_name='Lim',
            password='Kopi-Teh-2026!',
        )
        cls.drlim.groups.add(coordinator_group)
        StaffProfile.objects.create(
            user=cls.drlim,
            organisation=cls.kent_ridge,
            job_title='Clinical research coordinator',
            mobile='+6591234567',
        )

        cls.nurul = User.objects.create_user(
            username='nurul@harbourfront.sg',
            email='nurul@harbourfront.sg',
            first_name='Nurul',
            last_name='Huda',
            password='Kopi-Teh-2026!',
            is_active=True,
        )
        cls.nurul.groups.add(coordinator_group)
        StaffProfile.objects.create(
            user=cls.nurul,
            organisation=cls.harbourfront,
            job_title='Research coordinator',
            mobile='+6591234568',
        )

        cls.priya = User.objects.create_user(
            username='priya@athena.sg',
            email='priya@athena.sg',
            first_name='Priya',
            last_name='Nair',
            password='Kopi-Teh-2026!',
        )
        cls.priya.groups.add(Group.objects.get(name='Staff'))
        StaffProfile.objects.create(
            user=cls.priya,
            organisation=None,
            job_title='Operations executive',
            mobile='+6591234569',
        )

        cls.aisyah = User.objects.create_user(
            username='aisyah@example.com',
            email='aisyah@example.com',
            first_name='Aisyah',
            last_name='Rahman',
            password='Kopi-Teh-2026!',
        )
        cls.aisyah.groups.add(Group.objects.get(name='Participant'))
        ParticipantProfile.objects.create(
            user=cls.aisyah,
            mobile='+6591234570',
            terms_accepted_at=cls.aisyah.date_joined,
        )

        today = timezone.localdate()
        common = {
            'category': cls.category,
            'description': 'A study about sleep habits in Singapore.',
            'visit_plan': 'Visit 1: sleep questionnaire.',
            'study_type': Study.StudyType.OBSERVATIONAL,
            'accepts_healthy_volunteers': True,
            'min_age': 21,
            'max_age': 65,
            'target_enrolment': 40,
            'total_visits': 1,
            'duration_weeks': 4,
            'visit_times': Study.VisitTimes.FLEXIBLE,
            'compensation_amount': Decimal('120.00'),
            'show_compensation': True,
            'start_date': today,
            'recruitment_deadline': today + timedelta(days=30),
            'irb_name': 'NUS-IRB',
            'irb_reference': 'NUS-IRB-2026-0412',
            'irb_expiry': today + timedelta(days=120),
            'irb_approved_text': True,
        }
        cls.kent_ridge_draft = Study.objects.create(
            organisation=cls.kent_ridge,
            title='Kent Ridge Draft',
            status=Study.Status.DRAFT,
            created_by=cls.drlim,
            last_edited_by=cls.drlim,
            **common,
        )
        cls.kent_ridge_draft.sites.add(cls.k1)
        cls.harbourfront_live = Study.objects.create(
            organisation=cls.harbourfront,
            title='Harbourfront Live',
            status=Study.Status.PUBLISHED,
            created_by=cls.nurul,
            last_edited_by=cls.nurul,
            **common,
        )
        cls.harbourfront_live.sites.add(cls.h1)

    def setUp(self):
        self.kent_ridge_draft.refresh_from_db()
        self.harbourfront_live.refresh_from_db()
        self.drlim.refresh_from_db()
        self.nurul.refresh_from_db()
        self.priya.refresh_from_db()
        self.aisyah.refresh_from_db()
        self.client.force_login(self.drlim)

    def study_form_data(self, site_id):
        today = timezone.localdate()
        return {
            'title': 'New Sleep Study',
            'category': self.category.pk,
            'study_type': Study.StudyType.OBSERVATIONAL,
            'phase': Study.Phase.NOT_APPLICABLE,
            'description': 'A plain language study about sleep.',
            'visit_plan': 'Visit 1: sleep questions.',
            'accepts_healthy_volunteers': 'on',
            'sex_eligibility': Study.SexEligibility.ALL,
            'min_age': '21',
            'max_age': '65',
            'min_bmi': '',
            'max_bmi': '',
            'smoker_rule': Study.SmokerRule.ANY,
            'regions': [],
            'sites': [str(site_id)],
            'target_enrolment': '40',
            'total_visits': '1',
            'duration_weeks': '4',
            'visit_times': Study.VisitTimes.FLEXIBLE,
            'compensation_amount': '120.00',
            'show_compensation': 'on',
            'start_date': today.isoformat(),
            'recruitment_deadline': (today + timedelta(days=30)).isoformat(),
            'irb_name': 'NUS-IRB',
            'irb_reference': 'NUS-IRB-2026-0412',
            'irb_expiry': (today + timedelta(days=120)).isoformat(),
            'irb_approved_text': 'on',
            'auto_shortlist_high': '',
        }

    def test_01_coordinator_list_is_limited_to_own_organisation(self):
        response = self.client.get('/panel/studies/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Kent Ridge Draft')
        self.assertNotContains(response, 'Harbourfront Live')

    def test_02_coordinator_gets_404_for_another_organisations_study(self):
        response = self.client.get(
            f'/panel/studies/{self.harbourfront_live.pk}/'
        )
        self.assertEqual(response.status_code, 404)

    def test_03_staff_sees_all_studies_and_organisation_column(self):
        self.client.force_login(self.priya)
        response = self.client.get('/panel/studies/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Kent Ridge Draft')
        self.assertContains(response, 'Harbourfront Live')
        self.assertContains(response, '<th>Organisation</th>', html=True)

    def test_04_valid_new_study_is_created_for_coordinators_organisation(self):
        response = self.client.post(
            '/panel/studies/new/',
            self.study_form_data(self.k1.pk),
        )
        self.assertEqual(response.status_code, 302)
        study = Study.objects.get(title='New Sleep Study')
        self.assertEqual(study.organisation, self.kent_ridge)
        self.assertEqual(study.status, Study.Status.DRAFT)
        self.assertEqual(study.created_by, self.drlim)

    def test_05_foreign_site_submission_is_rejected(self):
        response = self.client.post(
            '/panel/studies/new/',
            self.study_form_data(self.h1.pk),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Select a valid choice')
        self.assertFalse(Study.objects.filter(title='New Sleep Study').exists())

    def test_06_non_interventional_phase_is_rejected(self):
        data = self.study_form_data(self.k1.pk)
        data['phase'] = Study.Phase.PHASE_2
        response = self.client.post('/panel/studies/new/', data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Only interventional studies have a phase.')

    def test_07_maximum_age_below_minimum_is_rejected(self):
        data = self.study_form_data(self.k1.pk)
        data['min_age'] = '50'
        data['max_age'] = '30'
        response = self.client.post('/panel/studies/new/', data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            'Maximum age must be at least the minimum age.',
        )

    def test_08_invalid_disqualifying_answer_is_rejected(self):
        response = self.client.post(
            f'/panel/studies/{self.kent_ridge_draft.pk}/questions/',
            {
                'text': 'Do you work night shifts?',
                'options': 'Yes\nNo',
                'preferred_answer': '',
                'disqualifying_answer': 'Maybe',
                'order': '1',
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Disqualifying answer must be one of the options.')
        self.assertFalse(
            PreScreenQuestion.objects.filter(
                study=self.kent_ridge_draft,
                text='Do you work night shifts?',
            ).exists()
        )

    def test_09_published_listing_edit_redirects_with_message(self):
        self.client.force_login(self.nurul)
        response = self.client.get(
            f'/panel/studies/{self.harbourfront_live.pk}/edit/',
            follow=True,
        )
        self.assertContains(
            response,
            'Only draft or returned listings can be edited.',
        )
        self.assertEqual(
            response.redirect_chain,
            [(f'/panel/studies/{self.harbourfront_live.pk}/', 302)],
        )

    def test_10_participant_gets_403_for_study_list(self):
        self.client.force_login(self.aisyah)
        response = self.client.get('/panel/studies/')
        self.assertEqual(response.status_code, 403)
