from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.utils import timezone

from core.models import (
    Application,
    Appointment,
    Organisation,
    ParticipantProfile,
    Payout,
    Region,
    Site,
    StaffProfile,
    Study,
    StudyCategory,
    SupportRequest,
)


class AccessMatrixTests(TestCase):
    password = 'Kopi-Teh-2026!'

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for name in ('Participant', 'Coordinator', 'Staff', 'Admin'):
            Group.objects.get_or_create(name=name)
        cls.region = Region.objects.create(code='W', name='West', display_order=5)
        cls.category = StudyCategory.objects.create(
            name='Healthy Volunteer Phase I',
            slug='healthy-volunteer-phase-1',
            ml_label='healthy_phase1',
            description='Healthy volunteer studies.',
            display_order=1,
        )
        cls.kent_ridge = cls._organisation(
            'Kent Ridge Clinical Research Centre',
            'drlim@kentridge-crc.sg',
        )
        cls.harbourfront = cls._organisation(
            'Harbourfront General Hospital',
            'harbourfront@example.com',
        )
        cls.k1 = Site.objects.create(
            organisation=cls.kent_ridge,
            name='K1',
            address='21 Lower Kent Ridge Road',
            postal_code='119077',
            region=cls.region,
        )
        cls.h1 = Site.objects.create(
            organisation=cls.harbourfront,
            name='H1',
            address='1 Maritime Square',
            postal_code='099253',
            region=cls.region,
        )
        cls.coordinator = cls._panel_user(
            'drlim@kentridge-crc.sg',
            'Daniel',
            'Lim',
            'Coordinator',
            cls.kent_ridge,
        )
        cls.harbour_coordinator = cls._panel_user(
            'harbourfront@example.com',
            'Harbourfront',
            'Coordinator',
            'Coordinator',
            cls.harbourfront,
        )
        cls.staff = cls._panel_user('priya@athena.sg', 'Priya', 'Nair', 'Staff')
        cls.admin = cls._panel_user('admin@athena.sg', 'Wei', 'Ling', 'Admin')
        cls.aisyah = cls._participant('aisyah@example.com', 'Aisyah', 'Rahman')
        cls.tan = cls._participant('tan@example.com', 'Tan', 'Participant')
        cls.study = cls._study(
            'Kent Ridge Flu Study',
            cls.kent_ridge,
            cls.k1,
        )
        cls.harbour_study = cls._study(
            'Harbourfront Flu Study',
            cls.harbourfront,
            cls.h1,
        )
        now = timezone.now()
        cls.application = Application.objects.create(
            participant=cls.aisyah,
            study=cls.study,
            status=Application.Status.ENROLLED,
            preferred_site=cls.k1,
            availability=Application.Availability.FLEXIBLE,
            consent_given_at=now,
            submitted_at=now,
        )
        cls.appointment = Appointment.objects.create(
            application=cls.application,
            site=cls.k1,
            kind=Appointment.Kind.VISIT,
            visit_number=1,
            scheduled_for=now + timedelta(days=1),
        )
        cls.payout = Payout.objects.create(
            application=cls.application,
            amount=Decimal('50.00'),
            visits_counted=1,
            status=Payout.Status.REQUESTED,
        )
        cls.support = SupportRequest.objects.create(
            application=cls.application,
            topic=SupportRequest.Topic.OTHER,
            question='Can I update my availability?',
        )

    @classmethod
    def _organisation(cls, name, email):
        return Organisation.objects.create(
            name=name,
            org_type=Organisation.OrganisationType.UNIVERSITY,
            contact_person='Research contact',
            contact_email=email,
        )

    @classmethod
    def _panel_user(cls, email, first_name, last_name, group, organisation=None):
        user = User.objects.create_user(
            username=email,
            email=email,
            first_name=first_name,
            last_name=last_name,
            password=cls.password,
        )
        user.groups.add(Group.objects.get(name=group))
        StaffProfile.objects.create(
            user=user,
            organisation=organisation,
            mobile='+6591234567',
        )
        return user

    @classmethod
    def _participant(cls, email, first_name, last_name):
        user = User.objects.create_user(
            username=email,
            email=email,
            first_name=first_name,
            last_name=last_name,
            password=cls.password,
        )
        user.groups.add(Group.objects.get(name='Participant'))
        return ParticipantProfile.objects.create(
            user=user,
            mobile='+6591234567',
            terms_accepted_at=timezone.now(),
            onboarding_completed_at=timezone.now(),
            date_of_birth=date.today().replace(year=date.today().year - 30),
            sex=ParticipantProfile.Sex.FEMALE,
            region=cls.region,
            employment=ParticipantProfile.Employment.FULL_TIME,
            education=ParticipantProfile.Education.DEGREE,
            height_cm='165.0',
            weight_kg='60.0',
            activity_level=ParticipantProfile.ActivityLevel.MODERATE,
            availability=ParticipantProfile.Availability.FLEXIBLE,
            max_travel_minutes=ParticipantProfile.TravelMinutes.THIRTY,
        )

    @classmethod
    def _study(cls, title, organisation, site):
        study = Study.objects.create(
            organisation=organisation,
            category=cls.category,
            title=title,
            description='A plain-language research study.',
            study_type=Study.StudyType.OBSERVATIONAL,
            accepts_healthy_volunteers=True,
            min_age=21,
            max_age=65,
            target_enrolment=40,
            total_visits=2,
            duration_weeks=4,
            visit_times=Study.VisitTimes.FLEXIBLE,
            compensation_amount=Decimal('100.00'),
            show_compensation=True,
            start_date=timezone.localdate(),
            recruitment_deadline=timezone.localdate() + timedelta(days=30),
            status=Study.Status.PUBLISHED,
        )
        study.sites.add(site)
        return study

    def test_01_every_sitemap_url_matches_role_access(self):
        public = [
            '/',
            '/studies/',
            f'/studies/{self.study.slug}/',
            '/support/',
        ]
        participant = [
            '/account/',
            '/onboarding/',
            '/for-you/',
            '/shortlist/',
            '/applications/',
            f'/applications/{self.application.pk}/',
            f'/applications/{self.application.pk}/withdraw/',
            f'/applications/{self.application.pk}/review/',
            f'/applications/{self.application.pk}/contact/',
        ]
        panel = [
            '/panel/',
            '/panel/notifications/',
            '/panel/studies/',
            '/panel/participation/',
            '/panel/insights/',
        ]
        staff_pages = [
            '/panel/moderation/',
            '/panel/organisations/',
            '/panel/participants/',
            '/panel/taxonomy/',
            '/panel/payouts/',
            '/panel/reviews/',
            '/panel/support/',
            '/panel/ml/',
        ]
        admin_pages = [
            '/panel/ml/settings/',
            '/panel/staff/',
            '/panel/demo-data/',
        ]

        for path in public:
            for role, user in (
                ('anonymous', None),
                ('participant', self.aisyah.user),
                ('coordinator', self.coordinator),
                ('staff', self.staff),
                ('admin', self.admin),
            ):
                with self.subTest(path=path, role=role):
                    if user:
                        self.client.force_login(user)
                    else:
                        self.client.logout()
                    self.assertEqual(self.client.get(path).status_code, 200)
        for path in ('/accounts/login/', '/accounts/register/'):
            with self.subTest(path=path, role='anonymous'):
                self.client.logout()
                self.assertEqual(self.client.get(path).status_code, 200)
        for path in participant:
            with self.subTest(path=path, role='anonymous'):
                self.client.logout()
                self.assertRedirects(
                    self.client.get(path),
                    f'/accounts/login/?next={path}',
                    fetch_redirect_response=False,
                )
            for role, user in (
                ('coordinator', self.coordinator),
                ('staff', self.staff),
                ('admin', self.admin),
            ):
                with self.subTest(path=path, role=role):
                    self.client.force_login(user)
                    self.assertEqual(self.client.get(path).status_code, 403)
        self.client.force_login(self.tan.user)
        with self.subTest(path='aisyah application', role='tan'):
            self.assertEqual(
                self.client.get(f'/applications/{self.application.pk}/').status_code,
                404,
            )
        panel_paths = panel + staff_pages + admin_pages
        for path in panel_paths:
            with self.subTest(path=path, role='anonymous'):
                self.client.logout()
                self.assertRedirects(
                    self.client.get(path),
                    f'/panel/login/?next={path}',
                    fetch_redirect_response=False,
                )
            with self.subTest(path=path, role='participant'):
                self.client.force_login(self.aisyah.user)
                self.assertEqual(self.client.get(path).status_code, 403)
        for path in panel:
            for role, user in (
                ('coordinator', self.coordinator),
                ('staff', self.staff),
                ('admin', self.admin),
            ):
                with self.subTest(path=path, role=role):
                    self.client.force_login(user)
                    self.assertEqual(self.client.get(path).status_code, 200)
        for path in staff_pages:
            with self.subTest(path=path, role='coordinator'):
                self.client.force_login(self.coordinator)
                self.assertEqual(self.client.get(path).status_code, 403)
            for role, user in (('staff', self.staff), ('admin', self.admin)):
                with self.subTest(path=path, role=role):
                    self.client.force_login(user)
                    self.assertEqual(self.client.get(path).status_code, 200)
        for path in admin_pages:
            for role, user in (
                ('coordinator', self.coordinator),
                ('staff', self.staff),
            ):
                with self.subTest(path=path, role=role):
                    self.client.force_login(user)
                    self.assertEqual(self.client.get(path).status_code, 403)
            with self.subTest(path=path, role='admin'):
                self.client.force_login(self.admin)
                self.assertEqual(self.client.get(path).status_code, 200)
        for path in (
            f'/panel/studies/{self.harbour_study.pk}/',
            f'/panel/studies/{self.harbour_study.pk}/applicants/',
        ):
            with self.subTest(path=path, role='coordinator'):
                self.client.force_login(self.coordinator)
                self.assertEqual(self.client.get(path).status_code, 404)
        for role, user in (
            ('anonymous', None),
            ('participant', self.aisyah.user),
            ('coordinator', self.coordinator),
            ('staff', self.staff),
            ('admin', self.admin),
        ):
            with self.subTest(path='/admin/', role=role):
                if user:
                    self.client.force_login(user)
                else:
                    self.client.logout()
                self.assertEqual(self.client.get('/admin/').status_code, 404)
