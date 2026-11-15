from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from core.models import (
    Condition,
    Organisation,
    ParticipantProfile,
    Region,
    Site,
    StaffProfile,
    Study,
    StudyCategory,
)
from core.services import (
    add_coordinator,
    approve_researcher,
    search_participants,
    set_organisation_active,
    set_site_active,
)
from adminpanel.forms import CoordinatorForm


class RecordsAndTaxonomyTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.region = Region.objects.create(
            code='W',
            name='West',
            display_order=5,
        )
        cls.sleep = StudyCategory.objects.create(
            name='Sleep',
            slug='sleep',
            ml_label='sleep',
            description='Explore sleep research.',
            display_order=1,
        )
        cls.lifestyle = StudyCategory.objects.create(
            name='Lifestyle',
            slug='lifestyle',
            ml_label='lifestyle',
            description='Explore lifestyle research.',
            display_order=2,
        )
        cls.asthma = Condition.objects.create(
            name='Asthma',
            ml_flag=Condition.MLFlag.RESPIRATORY,
        )
        cls.migraine = Condition.objects.create(
            name='Migraine',
        )
        cls.organisation = Organisation.objects.create(
            name='Harbourfront General Hospital',
            org_type=Organisation.OrganisationType.HOSPITAL,
            contact_person='Nurul Huda',
            contact_email='nurul@harbourfront.sg',
        )
        cls.site = Site.objects.create(
            organisation=cls.organisation,
            name='H1',
            address='1 Maritime Square',
            postal_code='099253',
            region=cls.region,
        )

        coordinator_group = Group.objects.get(name='Coordinator')
        cls.coordinator = User.objects.create_user(
            username='drlim@kentridge-crc.sg',
            email='drlim@kentridge-crc.sg',
            first_name='Daniel',
            last_name='Lim',
            password='Kopi-Teh-2026!',
        )
        cls.coordinator.groups.add(coordinator_group)
        StaffProfile.objects.create(
            user=cls.coordinator,
            organisation=cls.organisation,
            job_title='Clinical research coordinator',
            mobile='+6591234567',
        )

        cls.researcher = User.objects.create_user(
            username='nurul@harbourfront.sg',
            email='nurul@harbourfront.sg',
            first_name='Nurul',
            last_name='Huda',
            password='Kopi-Teh-2026!',
            is_active=False,
        )
        cls.researcher.groups.add(coordinator_group)
        StaffProfile.objects.create(
            user=cls.researcher,
            organisation=cls.organisation,
            job_title='Research coordinator',
            mobile='+6591234568',
        )

        cls.staff = User.objects.create_user(
            username='priya@athena.sg',
            email='priya@athena.sg',
            first_name='Priya',
            last_name='Nair',
            password='Kopi-Teh-2026!',
        )
        cls.staff.groups.add(Group.objects.get(name='Staff'))
        StaffProfile.objects.create(
            user=cls.staff,
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
        cls.aisyah_profile = ParticipantProfile.objects.create(
            user=cls.aisyah,
            mobile='+6591234567',
            terms_accepted_at=cls.aisyah.date_joined,
        )
        cls.aisyah.groups.add(Group.objects.get(name='Participant'))
        cls.aisyah_profile.conditions.add(cls.asthma)

        cls.tan = User.objects.create_user(
            username='mrtan@example.com',
            email='mrtan@example.com',
            first_name='Tan Ah',
            last_name='Kow',
            password='Kopi-Teh-2026!',
        )
        cls.tan_profile = ParticipantProfile.objects.create(
            user=cls.tan,
            mobile='+6581234567',
            terms_accepted_at=cls.tan.date_joined,
        )
        cls.tan.groups.add(Group.objects.get(name='Participant'))

        today = timezone.localdate()
        cls.live_study = Study.objects.create(
            organisation=cls.organisation,
            category=cls.sleep,
            title='Harbourfront Live',
            description='A study about sleep habits in Singapore.',
            visit_plan='Visit 1: sleep questionnaire.',
            study_type=Study.StudyType.OBSERVATIONAL,
            accepts_healthy_volunteers=True,
            min_age=21,
            max_age=65,
            target_enrolment=40,
            total_visits=1,
            duration_weeks=4,
            visit_times=Study.VisitTimes.FLEXIBLE,
            compensation_amount=Decimal('120.00'),
            show_compensation=True,
            start_date=today,
            recruitment_deadline=today + timedelta(days=30),
            irb_name='NUS-IRB',
            irb_reference='NUS-IRB-2026-0412',
            irb_expiry=today + timedelta(days=120),
            irb_approved_text=True,
            status=Study.Status.PUBLISHED,
            created_by=cls.coordinator,
            last_edited_by=cls.coordinator,
            published_at=timezone.now(),
        )
        cls.live_study.sites.add(cls.site)

    def setUp(self):
        self.organisation = Organisation.objects.get(
            pk=type(self).organisation.pk
        )
        self.site = Site.objects.get(pk=type(self).site.pk)
        self.live_study = Study.objects.get(pk=type(self).live_study.pk)
        self.live_study.refresh_from_db()
        self.researcher = User.objects.get(pk=type(self).researcher.pk)
        self.researcher.refresh_from_db()
        self.coordinator = User.objects.get(pk=type(self).coordinator.pk)
        self.coordinator.refresh_from_db()
        self.staff = User.objects.get(pk=type(self).staff.pk)
        self.staff.refresh_from_db()
        self.aisyah_profile = ParticipantProfile.objects.get(
            pk=type(self).aisyah_profile.pk
        )
        self.tan_profile = ParticipantProfile.objects.get(
            pk=type(self).tan_profile.pk
        )

    def test_01_approve_researcher_enables_account_sign_in(self):
        approve_researcher(self.researcher, self.staff)
        self.researcher.refresh_from_db()
        self.assertTrue(self.researcher.is_active)
        response = self.client.post(
            '/accounts/login/',
            {
                'email': 'nurul@harbourfront.sg',
                'password': 'Kopi-Teh-2026!',
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            self.client.session['_auth_user_id'],
            str(self.researcher.pk),
        )

    def test_02_deactivating_organisation_pauses_study_and_coordinator(self):
        approve_researcher(self.researcher, self.staff)
        set_organisation_active(self.organisation, False, self.staff)
        self.live_study.refresh_from_db()
        self.researcher.refresh_from_db()
        self.assertEqual(self.live_study.status, Study.Status.PAUSED)
        self.assertEqual(
            self.live_study.paused_reason,
            'Organisation deactivated',
        )
        self.assertFalse(self.researcher.is_active)

    def test_03_site_used_by_live_study_cannot_be_deactivated(self):
        with self.assertRaisesMessage(
            ValidationError,
            'This site is used by a live study.',
        ):
            set_site_active(self.site, False)
        self.site.refresh_from_db()
        self.assertTrue(self.site.is_active)

    def test_04_delete_views_keep_used_category_and_remove_unused_category(self):
        self.client.force_login(self.staff)
        used_response = self.client.post(
            f'/panel/taxonomy/category/{self.sleep.pk}/delete/',
            follow=True,
        )
        self.assertContains(
            used_response,
            'This is in use, so it has been kept. Hide it instead.',
        )
        self.assertTrue(StudyCategory.objects.filter(pk=self.sleep.pk).exists())

        unused_response = self.client.post(
            f'/panel/taxonomy/category/{self.lifestyle.pk}/delete/',
            follow=True,
        )
        self.assertEqual(unused_response.status_code, 200)
        self.assertFalse(
            StudyCategory.objects.filter(pk=self.lifestyle.pk).exists()
        )

    def test_05_hiding_condition_keeps_it_and_removes_it_from_onboarding(self):
        self.client.force_login(self.staff)
        response = self.client.post(
            f'/panel/taxonomy/condition/{self.asthma.pk}/hide/'
        )
        self.assertEqual(response.status_code, 302)
        self.asthma.refresh_from_db()
        self.assertFalse(self.asthma.is_active)
        self.assertTrue(Condition.objects.filter(pk=self.asthma.pk).exists())

        self.client.force_login(self.aisyah)
        onboarding_response = self.client.get('/onboarding/')
        self.assertEqual(onboarding_response.status_code, 200)
        self.assertNotContains(onboarding_response, 'Asthma')

    def test_06_participant_search_matches_name_mobile_and_p_code(self):
        name_results = list(search_participants('aisyah'))
        self.assertEqual([item.user.email for item in name_results], [
            'aisyah@example.com',
        ])
        mobile_results = list(search_participants('9123'))
        self.assertEqual([item.user.email for item in mobile_results], [
            'aisyah@example.com',
        ])
        code_results = list(search_participants(self.tan_profile.code))
        self.assertEqual([item.user.email for item in code_results], [
            'mrtan@example.com',
        ])

    def test_07_duplicate_organisation_name_is_rejected(self):
        self.client.force_login(self.staff)
        response = self.client.post(
            '/panel/organisations/',
            {
                'name': 'Harbourfront General Hospital',
                'org_type': Organisation.OrganisationType.HOSPITAL,
                'contact_person': 'Another Contact',
                'contact_email': 'another@harbourfront.sg',
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Organisation with this Name already exists.')
        self.assertEqual(Organisation.objects.filter(
            name='Harbourfront General Hospital'
        ).count(), 1)

    def test_08_coordinator_cannot_open_participant_records(self):
        self.client.force_login(self.coordinator)
        response = self.client.get('/panel/participants/')
        self.assertEqual(response.status_code, 403)

    def test_09_invalid_mobile_is_rejected_when_adding_coordinator(self):
        form = CoordinatorForm(data={
            'first_name': 'New',
            'last_name': 'Coordinator',
            'email': 'new@harbourfront.sg',
            'job_title': 'Research coordinator',
            'mobile': '6123 4567',
            'temporary_password': 'Kopi-Teh-2026!',
        })
        self.assertFalse(form.is_valid())
        self.assertIn(
            'Enter a Singapore mobile number, for example 9123 4567.',
            form.errors['mobile'],
        )
        service_form = SimpleNamespace(cleaned_data={
            'email': 'new@harbourfront.sg',
            'first_name': 'New',
            'last_name': 'Coordinator',
            'job_title': 'Research coordinator',
            'mobile': '6123 4567',
            'temporary_password': 'Kopi-Teh-2026!',
        })
        with self.assertRaisesMessage(
            ValidationError,
            'Enter a Singapore mobile number, for example 9123 4567.',
        ):
            add_coordinator(self.organisation, service_form)
        self.assertFalse(User.objects.filter(username='new@harbourfront.sg').exists())
