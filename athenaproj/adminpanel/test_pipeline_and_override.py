from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from core.models import (
    Appointment,
    Application,
    Organisation,
    ParticipantProfile,
    Region,
    Site,
    StaffProfile,
    Study,
    StudyCategory,
)
from core.services import (
    InvalidStatusMove,
    StudyFull,
    change_status,
    enrol_applicant,
    mark_not_selected,
    override_band,
    record_screening_outcome,
    schedule_screening,
    shortlist_applicant,
)


class PipelineAndOverrideTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.region = Region.objects.create(code='W', name='West', display_order=5)
        cls.category = StudyCategory.objects.create(
            name='Healthy Volunteer Phase I',
            slug='healthy-volunteer-phase-1',
            ml_label='healthy_phase1',
            description='Explore healthy volunteer studies.',
            display_order=2,
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
        cls.drlim = User.objects.create_user(
            username='drlim@kentridge-crc.sg',
            email='drlim@kentridge-crc.sg',
            first_name='Daniel',
            last_name='Lim',
            password='Kopi-Teh-2026!',
        )
        cls.drlim.groups.add(Group.objects.get(name='Coordinator'))
        StaffProfile.objects.create(
            user=cls.drlim,
            organisation=cls.kent_ridge,
            mobile='+6591234567',
        )
        today = timezone.localdate()
        cls.study = Study.objects.create(
            organisation=cls.kent_ridge,
            category=cls.category,
            title='Flu Vaccine Exercise Study',
            description='A study about exercise and flu vaccines.',
            study_type=Study.StudyType.INTERVENTIONAL,
            accepts_healthy_volunteers=True,
            min_age=21,
            max_age=65,
            target_enrolment=1,
            total_visits=5,
            duration_weeks=4,
            visit_times=Study.VisitTimes.FLEXIBLE,
            compensation_amount=Decimal('100.00'),
            show_compensation=True,
            start_date=today,
            recruitment_deadline=today + timedelta(days=30),
            status=Study.Status.PUBLISHED,
        )
        cls.study.sites.add(cls.k1, cls.k2)

        now = timezone.now()
        for number in (1, 2):
            user = User.objects.create_user(
                username=f'p{number}@example.com',
                email=f'p{number}@example.com',
                first_name=f'P{number}',
                password='Kopi-Teh-2026!',
            )
            user.groups.add(Group.objects.get(name='Participant'))
            profile = ParticipantProfile.objects.create(
                user=user,
                mobile='+6591234568',
                terms_accepted_at=now,
                date_of_birth=date(today.year - 30, 1, 1),
                sex=ParticipantProfile.Sex.FEMALE,
                region=cls.region,
            )
            application = Application.objects.create(
                participant=profile,
                study=cls.study,
                preferred_site=cls.k1,
                availability=Application.Availability.FLEXIBLE,
                consent_given_at=now,
                submitted_at=now,
                ml2_probability=0.55 if number == 1 else None,
                ml2_band=(
                    Application.Band.MEDIUM
                    if number == 1 else Application.Band.UNSCORED
                ),
            )
            change_status(application, Application.Status.UNDER_REVIEW)
            setattr(cls, f'p{number}', application)

    def setUp(self):
        self.study.refresh_from_db()
        self.drlim.refresh_from_db()
        self.k1.refresh_from_db()
        self.k2.refresh_from_db()
        self.h1.refresh_from_db()
        self.p1.refresh_from_db()
        self.p2.refresh_from_db()

    def schedule(self, application):
        shortlist_applicant(application, self.drlim)
        return schedule_screening(
            application,
            timezone.now() + timedelta(days=3),
            self.k1,
            self.drlim,
        )

    def pass_screening(self, application):
        self.schedule(application)
        record_screening_outcome(application, True, self.drlim)

    def test_01_shortlist_and_schedule_screening(self):
        self.schedule(self.p1)
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.status, Application.Status.SCREENING_SCHEDULED)
        appointments = self.p1.appointments.filter(kind=Appointment.Kind.SCREENING)
        self.assertEqual(appointments.count(), 1)
        appointment = appointments.get()
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, Appointment.Status.PROPOSED)
        self.assertEqual(appointment.site, self.k1)
        event = self.p1.status_events.get(to_status=Application.Status.SCREENING_SCHEDULED)
        self.assertTrue(event.note.startswith('Screening on'))

    def test_02_scheduling_under_review_is_invalid(self):
        with self.assertRaises(InvalidStatusMove):
            schedule_screening(
                self.p2,
                timezone.now() + timedelta(days=3),
                self.k1,
                self.drlim,
            )
        self.p2.refresh_from_db()
        self.assertEqual(self.p2.status, Application.Status.UNDER_REVIEW)
        self.assertFalse(self.p2.appointments.exists())

    def test_03_screening_rejects_wrong_site_and_past_time(self):
        shortlist_applicant(self.p1, self.drlim)
        with self.assertRaises(ValidationError):
            schedule_screening(
                self.p1,
                timezone.now() + timedelta(days=3),
                self.h1,
                self.drlim,
            )
        with self.assertRaises(ValidationError):
            schedule_screening(
                self.p1,
                timezone.now() - timedelta(hours=1),
                self.k1,
                self.drlim,
            )
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.status, Application.Status.SHORTLISTED)
        self.assertFalse(self.p1.appointments.exists())

    def test_04_record_passed_screening(self):
        appointment = self.schedule(self.p1)
        record_screening_outcome(self.p1, True, self.drlim)
        self.p1.refresh_from_db()
        appointment.refresh_from_db()
        self.assertEqual(self.p1.screening_outcome, 'passed')
        self.assertIsNotNone(self.p1.outcome_recorded_at)
        self.assertEqual(appointment.status, Appointment.Status.ATTENDED)
        self.assertEqual(self.p1.status, Application.Status.SCREENING_PASSED)

    def test_05_enrol_creates_visits_and_fills_study(self):
        self.pass_screening(self.p1)
        enrol_applicant(self.p1, self.drlim)
        self.p1.refresh_from_db()
        self.study.refresh_from_db()
        self.assertEqual(self.p1.status, Application.Status.ENROLLED)
        visits = self.p1.appointments.filter(kind=Appointment.Kind.VISIT).order_by(
            'visit_number'
        )
        self.assertEqual(visits.count(), 5)
        self.assertEqual(list(visits.values_list('visit_number', flat=True)), [1, 2, 3, 4, 5])
        self.assertTrue(all(visit.status == Appointment.Status.PROPOSED for visit in visits))
        self.assertEqual(self.study.status, Study.Status.FULL)

    def test_06_full_study_rejects_enrolment_without_creating_visits(self):
        self.pass_screening(self.p1)
        enrol_applicant(self.p1, self.drlim)
        self.pass_screening(self.p2)
        with self.assertRaises(StudyFull):
            enrol_applicant(self.p2, self.drlim)
        self.p2.refresh_from_db()
        self.assertEqual(self.p2.status, Application.Status.SCREENING_PASSED)
        self.assertFalse(self.p2.appointments.filter(kind=Appointment.Kind.VISIT).exists())

    def test_07_mark_not_selected_saves_reason(self):
        mark_not_selected(self.p2, self.drlim, 'We reached our target')
        self.p2.refresh_from_db()
        self.assertEqual(self.p2.status, Application.Status.NOT_SELECTED)
        self.assertEqual(self.p2.not_selected_reason, 'We reached our target')

    def test_08_override_preserves_original_band_and_status(self):
        original_status = self.p1.status
        override_band(self.p1, 'high', 'Strong fit after the phone call', self.drlim)
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.ml2_band, Application.Band.HIGH)
        self.assertEqual(self.p1.original_band, Application.Band.MEDIUM)
        self.assertTrue(self.p1.band_overridden)
        self.assertEqual(self.p1.overridden_by, self.drlim)
        self.assertEqual(self.p1.status, original_status)

    def test_09_short_override_reason_is_rejected(self):
        with self.assertRaises(ValidationError):
            override_band(self.p1, 'low', 'short', self.drlim)
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.ml2_band, Application.Band.MEDIUM)

    def test_10_subsequent_override_keeps_first_original_band(self):
        override_band(self.p1, 'high', 'Strong fit after the phone call', self.drlim)
        override_band(
            self.p1,
            'low',
            'Could not attend the screening window',
            self.drlim,
        )
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.ml2_band, Application.Band.LOW)
        self.assertEqual(self.p1.original_band, Application.Band.MEDIUM)
