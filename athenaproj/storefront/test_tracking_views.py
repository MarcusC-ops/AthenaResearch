from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import (
    Appointment,
    Application,
    ApplicationStatusEvent,
    Notification,
    Organisation,
    ParticipantProfile,
    Payout,
    Region,
    Site,
    StaffProfile,
    Study,
    StudyCategory,
)
from core.services import change_status


class ApplicationTrackingViewTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.password = 'Kopi-Teh-2026!'
        cls.region = Region.objects.create(
            code='W',
            name='West',
            display_order=5,
        )
        cls.category = StudyCategory.objects.create(
            name='Healthy Volunteer Phase I',
            slug='healthy-volunteer-phase-1',
            ml_label='healthy_phase1',
            description='Healthy volunteer studies.',
            display_order=1,
        )
        cls.organisation = Organisation.objects.create(
            name='Kent Ridge Clinical Research Centre',
            org_type=Organisation.OrganisationType.UNIVERSITY,
            contact_person='Daniel Lim',
            contact_email='drlim@kentridge-crc.sg',
        )
        cls.site = Site.objects.create(
            organisation=cls.organisation,
            name='Kent Ridge CRC, Lower Kent Ridge Clinic',
            address='21 Lower Kent Ridge Road, Level 3',
            postal_code='119077',
            region=cls.region,
        )

        participant_group, _ = Group.objects.get_or_create(name='Participant')
        coordinator_group, _ = Group.objects.get_or_create(name='Coordinator')
        cls.coordinator = User.objects.create_user(
            username='drlim@kentridge-crc.sg',
            email='drlim@kentridge-crc.sg',
            first_name='Daniel',
            last_name='Lim',
            password=cls.password,
            is_active=True,
        )
        cls.coordinator.groups.add(coordinator_group)
        StaffProfile.objects.create(
            user=cls.coordinator,
            organisation=cls.organisation,
            job_title='Clinical research coordinator',
            mobile='+6591234567',
        )

        cls.aisyah_user = User.objects.create_user(
            username='aisyah@example.com',
            email='aisyah@example.com',
            first_name='Aisyah',
            last_name='Rahman',
            password=cls.password,
        )
        cls.aisyah_user.groups.add(participant_group)
        cls.aisyah = ParticipantProfile.objects.create(
            user=cls.aisyah_user,
            mobile='+6591234567',
            terms_accepted_at=timezone.now(),
            onboarding_completed_at=timezone.now(),
            date_of_birth=date.today().replace(year=date.today().year - 30),
            sex=ParticipantProfile.Sex.FEMALE,
            region=cls.region,
            employment=ParticipantProfile.Employment.STUDENT,
            education=ParticipantProfile.Education.DEGREE,
            height_cm='160.0',
            weight_kg='52.0',
            smoker=False,
            activity_level=ParticipantProfile.ActivityLevel.HIGH,
            availability=ParticipantProfile.Availability.WEEKDAY_EVENINGS,
            max_travel_minutes=ParticipantProfile.TravelMinutes.THIRTY,
            consent_matching=True,
            consent_insights=True,
            consent_contact=True,
        )

        cls.tan_user = User.objects.create_user(
            username='tan@example.com',
            email='tan@example.com',
            first_name='Tan',
            last_name='Participant',
            password=cls.password,
        )
        cls.tan_user.groups.add(participant_group)
        cls.tan = ParticipantProfile.objects.create(
            user=cls.tan_user,
            mobile='+6581234567',
            terms_accepted_at=timezone.now(),
            onboarding_completed_at=timezone.now(),
            date_of_birth=date.today().replace(year=date.today().year - 35),
            sex=ParticipantProfile.Sex.MALE,
            region=cls.region,
            employment=ParticipantProfile.Employment.FULL_TIME,
            education=ParticipantProfile.Education.DEGREE,
            height_cm='175.0',
            weight_kg='70.0',
            smoker=False,
            activity_level=ParticipantProfile.ActivityLevel.MODERATE,
            availability=ParticipantProfile.Availability.FLEXIBLE,
            max_travel_minutes=ParticipantProfile.TravelMinutes.THIRTY,
        )

        cls.study = Study.objects.create(
            organisation=cls.organisation,
            category=cls.category,
            title='Flu Vaccine Exercise Study',
            description='An exercise and flu vaccine study.',
            study_type=Study.StudyType.INTERVENTIONAL,
            phase=Study.Phase.PHASE_4,
            accepts_healthy_volunteers=True,
            sex_eligibility=Study.SexEligibility.ALL,
            min_age=21,
            max_age=65,
            smoker_rule=Study.SmokerRule.ANY,
            target_enrolment=40,
            total_visits=5,
            duration_weeks=12,
            visit_times=Study.VisitTimes.WEEKDAY_EVENINGS,
            compensation_amount='350.00',
            show_compensation=True,
            start_date=timezone.localdate(),
            recruitment_deadline=timezone.localdate() + timedelta(days=30),
            status=Study.Status.PUBLISHED,
        )
        cls.study.sites.add(cls.site)

        now = timezone.now()
        cls.application = Application.objects.create(
            participant=cls.aisyah,
            study=cls.study,
            status=Application.Status.SUBMITTED,
            preferred_site=cls.site,
            availability=Application.Availability.WEEKDAY_EVENINGS,
            consent_given_at=now,
            submitted_at=now,
        )
        ApplicationStatusEvent.objects.create(
            application=cls.application,
            from_status='',
            to_status=Application.Status.SUBMITTED,
            actor_role=ApplicationStatusEvent.ActorRole.SYSTEM,
            note='Application received',
        )
        for status in (
            Application.Status.UNDER_REVIEW,
            Application.Status.SHORTLISTED,
            Application.Status.SCREENING_SCHEDULED,
            Application.Status.SCREENING_PASSED,
            Application.Status.ENROLLED,
        ):
            change_status(
                cls.application,
                status,
                actor=cls.coordinator,
                actor_role=ApplicationStatusEvent.ActorRole.COORDINATOR,
                note='Research team update',
            )

        cls.screening = Appointment.objects.create(
            application=cls.application,
            site=cls.site,
            kind=Appointment.Kind.SCREENING,
            scheduled_for=now - timedelta(days=30),
            status=Appointment.Status.ATTENDED,
        )
        cls.visits = []
        visit_statuses = (
            Appointment.Status.ATTENDED,
            Appointment.Status.ATTENDED,
            Appointment.Status.ATTENDED,
            Appointment.Status.CONFIRMED,
            Appointment.Status.PROPOSED,
        )
        for number, status in enumerate(visit_statuses, 1):
            visit = Appointment.objects.create(
                application=cls.application,
                site=cls.site,
                kind=Appointment.Kind.VISIT,
                visit_number=number,
                scheduled_for=(
                    now + timedelta(days=10)
                    if number == 5 else now - timedelta(days=number * 7)
                ),
                status=status,
            )
            cls.visits.append(visit)

        cls.payout = Payout.objects.create(
            application=cls.application,
            amount=Decimal('140.00'),
            visits_counted=3,
            status=Payout.Status.PAID,
            reference='PN-2026-000001',
            paid_at=now,
        )

    def setUp(self):
        self.application.refresh_from_db()
        self.study.refresh_from_db()
        self.aisyah.refresh_from_db()
        self.tan.refresh_from_db()
        self.coordinator.refresh_from_db()
        self.screening.refresh_from_db()
        self.payout.refresh_from_db()
        for visit in self.visits:
            visit.refresh_from_db()

    def test_01_applications_lists_enrolled_study_as_open(self):
        self.client.force_login(self.aisyah_user)

        response = self.client.get(reverse('storefront:applications'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Open')
        self.assertContains(response, 'Flu Vaccine Exercise Study')
        self.assertContains(response, 'Enrolled')

    def test_02_application_page_shows_timeline_visits_and_compensation(self):
        self.client.force_login(self.aisyah_user)

        response = self.client.get(
            reverse(
                'storefront:application_detail',
                kwargs={'application_id': self.application.pk},
            )
        )

        self.assertEqual(response.status_code, 200)
        for text in (
            'Being reviewed',
            'Screening booked',
            'Research team',
            '3 of 5 visits attended',
            '60%',
            'S$140.00',
            'PN-2026-000001',
            'Total paid so far S$140.00',
        ):
            self.assertContains(response, text)

    def test_03_application_page_shows_what_happens_next(self):
        self.client.force_login(self.aisyah_user)

        response = self.client.get(
            reverse(
                'storefront:application_detail',
                kwargs={'application_id': self.application.pk},
            )
        )

        self.assertContains(response, 'You are taking part.')

    def test_04_confirming_proposed_future_visit_sets_confirmed_at(self):
        self.client.force_login(self.aisyah_user)
        visit = self.visits[4]

        response = self.client.post(
            reverse(
                'storefront:confirm_appointment',
                kwargs={
                    'application_id': self.application.pk,
                    'appointment_id': visit.pk,
                },
            )
        )

        self.assertRedirects(
            response,
            reverse(
                'storefront:application_detail',
                kwargs={'application_id': self.application.pk},
            ),
        )
        visit.refresh_from_db()
        self.assertEqual(visit.status, Appointment.Status.CONFIRMED)
        self.assertIsNotNone(visit.confirmed_at)

    def test_05_attended_visit_cannot_be_confirmed(self):
        self.client.force_login(self.aisyah_user)
        visit = self.visits[0]
        original_confirmed_at = visit.confirmed_at

        response = self.client.post(
            reverse(
                'storefront:confirm_appointment',
                kwargs={
                    'application_id': self.application.pk,
                    'appointment_id': visit.pk,
                },
            ),
            follow=True,
        )

        visit.refresh_from_db()
        self.assertEqual(visit.status, Appointment.Status.ATTENDED)
        self.assertEqual(visit.confirmed_at, original_confirmed_at)
        self.assertContains(response, 'This appointment cannot be confirmed.')

    def test_06_other_participant_cannot_view_application(self):
        self.client.force_login(self.tan_user)

        response = self.client.get(
            reverse(
                'storefront:application_detail',
                kwargs={'application_id': self.application.pk},
            )
        )

        self.assertEqual(response.status_code, 404)

    def test_07_withdrawing_cancels_open_visits_and_notifies_coordinator(self):
        self.client.force_login(self.aisyah_user)

        response = self.client.post(
            reverse(
                'storefront:withdraw_application',
                kwargs={'application_id': self.application.pk},
            ),
            {'reason': 'Moving overseas'},
        )

        self.assertRedirects(
            response,
            reverse(
                'storefront:application_detail',
                kwargs={'application_id': self.application.pk},
            ),
        )
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, Application.Status.WITHDRAWN)
        self.assertEqual(self.application.withdrawal_reason, 'Moving overseas')
        self.visits[3].refresh_from_db()
        self.visits[4].refresh_from_db()
        self.assertEqual(self.visits[3].status, Appointment.Status.CANCELLED)
        self.assertEqual(self.visits[4].status, Appointment.Status.CANCELLED)
        for visit in self.visits[:3]:
            visit.refresh_from_db()
            self.assertEqual(visit.status, Appointment.Status.ATTENDED)
        notifications = Notification.objects.filter(user=self.coordinator)
        self.assertEqual(notifications.count(), 1)
        self.assertIn('withdrew', notifications.get().message)

    def test_08_withdraw_page_reports_closed_application(self):
        self.client.force_login(self.aisyah_user)
        self.client.post(
            reverse(
                'storefront:withdraw_application',
                kwargs={'application_id': self.application.pk},
            ),
            {'reason': 'Moving overseas'},
        )

        response = self.client.get(
            reverse(
                'storefront:withdraw_application',
                kwargs={'application_id': self.application.pk},
            )
        )

        self.assertContains(response, 'This application is already closed.')

    def test_09_other_participant_cannot_open_withdraw_page(self):
        self.client.force_login(self.tan_user)

        response = self.client.get(
            reverse(
                'storefront:withdraw_application',
                kwargs={'application_id': self.application.pk},
            )
        )

        self.assertEqual(response.status_code, 404)
