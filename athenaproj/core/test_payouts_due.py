from django.test import TestCase
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User, Group
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal

from core.models import (
    Region, StudyCategory, Organisation, Site, Study,
    ParticipantProfile, Application, Appointment, Payout, Notification, StaffProfile
)
from core.services import (
    earned_amount, amount_due, request_payout, mark_visit,
    save_visit_date, complete_participation
)


class PayoutsDueTestCase(TestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # Create region
        region_w = Region.objects.create(code='W', name='West', display_order=1)

        # Create category
        category = StudyCategory.objects.create(
            name='Healthy Volunteer Phase I',
            slug='hv-phase-1',
            ml_label='HV_Phase_1',
            description='Healthy volunteer phase 1 studies',
            display_order=1
        )

        # Create organisation and site
        org = Organisation.objects.create(name='Kent Ridge')
        site = Site.objects.create(
            name='K1',
            organisation=org,
            region=region_w,
            address='123 Main St',
            postal_code='123456'
        )

        # Create coordinator user (drlim)
        coord_user = User.objects.create_user(
            username='drlim@kentridge-crc.sg',
            first_name='Daniel',
            last_name='Lim',
            email='drlim@kentridge-crc.sg',
            password='AthenaDemo2026!'
        )
        coord_profile = StaffProfile.objects.create(
            user=coord_user,
            organisation=org,
            job_title='Clinical research coordinator',
            mobile='9123 4567'
        )

        # Create staff user (priya)
        priya_user = User.objects.create_user(
            username='priya@athena.sg',
            first_name='Priya',
            last_name='Admin',
            email='priya@athena.sg',
            password='AthenaDemo2026!'
        )
        StaffProfile.objects.create(
            user=priya_user,
            organisation=None,
            job_title='Operations executive',
            mobile='9000 0000'
        )
        # Add to Staff group
        staff_group, _ = Group.objects.get_or_create(name='Staff')
        priya_user.groups.add(staff_group)

        # Create study
        from datetime import date
        study = Study.objects.create(
            organisation=org,
            category=category,
            title='Flu Vaccine Exercise Study',
            status=Study.Status.PUBLISHED,
            description='Test study for vaccine exercise',
            study_type=Study.StudyType.OBSERVATIONAL,
            phase=Study.Phase.NOT_APPLICABLE,
            accepts_healthy_volunteers=True,
            sex_eligibility=Study.SexEligibility.ALL,
            min_age=21,
            max_age=65,
            smoker_rule=Study.SmokerRule.ANY,
            target_enrolment=40,
            total_visits=5,
            duration_weeks=5,
            visit_times=Study.VisitTimes.FLEXIBLE,
            compensation_amount=Decimal('350.00'),
            show_compensation=True,
            start_date=date(2026, 11, 15),
            recruitment_deadline=date(2026, 12, 31)
        )

        # Create participant (Aisyah)
        participant_user = User.objects.create_user(
            username='aisyah@example.com',
            first_name='Aisyah',
            last_name='Rahman',
            email='aisyah@example.com',
            password='ParticipantPass123!'
        )
        participant = ParticipantProfile.objects.create(
            user=participant_user,
            mobile='91234567',
            terms_accepted_at=timezone.now(),
            date_of_birth='1990-05-15',
            sex='female',
            region=region_w,
            consent_insights=True,
            consent_contact=True,
            consent_matching=True
        )

        # Create enrolled application
        application = Application.objects.create(
            participant=participant,
            study=study,
            preferred_site=site,
            availability=Application.Availability.FLEXIBLE,
            consent_given_at=timezone.now(),
            submitted_at=timezone.now(),
            status=Application.Status.ENROLLED
        )

        # Create 5 visit appointments
        now = timezone.now()

        # Visits 1-3: attended with past dates
        for i in range(1, 4):
            apt = Appointment.objects.create(
                application=application,
                site=site,
                kind=Appointment.Kind.VISIT,
                visit_number=i,
                status=Appointment.Status.ATTENDED,
                scheduled_for=now - timedelta(days=5 - i)
            )

        # Visit 4: confirmed 1 hour ago (so marking as attended should work)
        apt4 = Appointment.objects.create(
            application=application,
            site=site,
            kind=Appointment.Kind.VISIT,
            visit_number=4,
            status=Appointment.Status.CONFIRMED,
            scheduled_for=now - timedelta(hours=1)
        )

        # Visit 5: proposed 10 days ahead
        apt5 = Appointment.objects.create(
            application=application,
            site=site,
            kind=Appointment.Kind.VISIT,
            visit_number=5,
            status=Appointment.Status.PROPOSED,
            scheduled_for=now + timedelta(days=10)
        )

        # Create one paid payout of 140.00
        payout = Payout.objects.create(
            application=application,
            amount=Decimal('140.00'),
            status=Payout.Status.PAID,
            visits_counted=2,
            reference='PN-2026-000001'
        )

        # Store references for use in test methods
        cls.participant = participant
        cls.application = application
        cls.study = study
        cls.coord_user = coord_user
        cls.priya_user = priya_user
        cls.site = site
        cls.now = now

        # Create extra participants for tests that need fresh applications
        # Participant 2 (for test 04)
        p2_user = User.objects.create_user(
            username='participant2@example.com',
            first_name='Ahmad',
            last_name='Hassan',
            email='participant2@example.com',
            password='ParticipantPass123!'
        )
        cls.participant2 = ParticipantProfile.objects.create(
            user=p2_user,
            mobile='91234567',
            terms_accepted_at=timezone.now(),
            date_of_birth='1985-03-20',
            sex='male',
            region=region_w,
            consent_insights=True,
            consent_contact=True,
            consent_matching=True
        )

        # Participant 3 (for test 07)
        p3_user = User.objects.create_user(
            username='participant3@example.com',
            first_name='Siti',
            last_name='Ahmad',
            email='participant3@example.com',
            password='ParticipantPass123!'
        )
        cls.participant3 = ParticipantProfile.objects.create(
            user=p3_user,
            mobile='91234567',
            terms_accepted_at=timezone.now(),
            date_of_birth='1988-07-10',
            sex='female',
            region=region_w,
            consent_insights=True,
            consent_contact=True,
            consent_matching=True
        )

    def test_01_earned_and_amount_due(self):
        """earned_amount should be 210.00 and amount_due should be 70.00"""
        self.application.refresh_from_db()

        earned = earned_amount(self.application)
        due = amount_due(self.application)

        # 3 attended visits out of 5 = 3/5 × 350.00 = 210.00
        self.assertEqual(earned, Decimal('210.00'))

        # Earned 210.00, already paid 140.00, nothing requested = 70.00 due
        self.assertEqual(due, Decimal('70.00'))

    def test_02_request_payout_creates_notification(self):
        """request_payout should create requested payout and notify priya"""
        self.application.refresh_from_db()

        # Clear any existing notifications
        Notification.objects.all().delete()

        # Request payout
        request_payout(self.application, self.coord_user)

        # Check payout was created
        requested = Payout.objects.filter(
            application=self.application,
            status=Payout.Status.REQUESTED
        ).first()

        self.assertIsNotNone(requested)
        self.assertEqual(requested.amount, Decimal('70.00'))
        self.assertEqual(requested.visits_counted, 3)

        # Check priya was notified
        notification = Notification.objects.filter(
            user=self.priya_user
        ).first()

        self.assertIsNotNone(notification)
        self.assertIn('S$70.00', notification.message)

    def test_03_request_payout_twice_raises_error(self):
        """Second request_payout should raise ValidationError"""
        self.application.refresh_from_db()

        # First request should succeed
        request_payout(self.application, self.coord_user)

        # Second request should raise ValidationError
        with self.assertRaises(ValidationError) as context:
            request_payout(self.application, self.coord_user)

        self.assertIn('Nothing is due right now', str(context.exception))

    def test_04_mark_missed_reduces_amount_due(self):
        """After marking visit 4 missed, amount_due should stay 0.00"""
        # Fresh application without requested payouts
        app = Application.objects.create(
            participant=self.participant2,
            study=self.study,
            preferred_site=self.site,
            availability=Application.Availability.FLEXIBLE,
            consent_given_at=timezone.now(),
            submitted_at=timezone.now(),
            status=Application.Status.ENROLLED
        )

        # Copy visits but mark visit 4 as confirmed
        now = timezone.now()
        for i in range(1, 4):
            Appointment.objects.create(
                application=app,
                site=self.site,
                kind=Appointment.Kind.VISIT,
                visit_number=i,
                status=Appointment.Status.ATTENDED,
                scheduled_for=now - timedelta(days=5 - i)
            )

        apt4 = Appointment.objects.create(
            application=app,
            site=self.site,
            kind=Appointment.Kind.VISIT,
            visit_number=4,
            status=Appointment.Status.CONFIRMED,
            scheduled_for=now - timedelta(hours=1)
        )

        Appointment.objects.create(
            application=app,
            site=self.site,
            kind=Appointment.Kind.VISIT,
            visit_number=5,
            status=Appointment.Status.PROPOSED,
            scheduled_for=now + timedelta(days=10)
        )

        # Add paid payout of 140
        Payout.objects.create(
            application=app,
            amount=Decimal('140.00'),
            status=Payout.Status.PAID,
            visits_counted=2
        )

        # Request payout (3 attended = 210 earned, 140 paid = 70 due)
        request_payout(app, self.coord_user)

        # Mark visit 4 as missed (still 3 attended, earned stays 210, requested stays 70)
        mark_visit(apt4, False, self.coord_user)
        app.refresh_from_db()

        # amount_due should be 0.00 (already requested the 70.00)
        due = amount_due(app)
        self.assertEqual(due, Decimal('0.00'))

    def test_05_mark_future_visit_raises_error(self):
        """Marking a future visit attended should raise ValidationError"""
        visit5 = self.application.appointments.get(visit_number=5)

        # Visit 5 is 10 days in future, should not be markable
        with self.assertRaises(ValidationError) as context:
            mark_visit(visit5, True, self.coord_user)

        self.assertIn('cannot', str(context.exception).lower())

        # Verify visit is still proposed
        visit5.refresh_from_db()
        self.assertEqual(visit5.status, Appointment.Status.PROPOSED)

    def test_06_mark_and_save_visits_comprehensive(self):
        """Mark visit 4 attended, save visit 5 to 2h ago, mark attended"""
        visit4 = self.application.appointments.get(visit_number=4)
        visit5 = self.application.appointments.get(visit_number=5)

        # Mark visit 4 attended
        mark_visit(visit4, True, self.coord_user)

        # Save visit 5 to 2 hours ago
        two_hours_ago = timezone.now() - timedelta(hours=2)
        save_visit_date(visit5, two_hours_ago, self.coord_user)

        # Verify visit 5 is back to proposed
        visit5.refresh_from_db()
        self.assertEqual(visit5.status, Appointment.Status.PROPOSED)

        # Mark visit 5 attended
        mark_visit(visit5, True, self.coord_user)

        # All 5 visits attended: earned = 5/5 × 350 = 350.00
        earned = earned_amount(self.application)
        self.assertEqual(earned, Decimal('350.00'))

        # Paid 140 + requested 70 = 210, so due = 350 - 210 = 140.00
        # Wait, need to check if there's a requested payout from earlier tests
        # In a fresh test, no requested yet, so due = 350 - 140 = 210
        due = amount_due(self.application)
        self.assertEqual(due, Decimal('210.00'))

    def test_07_complete_participation_validation(self):
        """Cannot complete with proposed/confirmed, but ok when all attended/missed"""
        # Create fresh application
        app = Application.objects.create(
            participant=self.participant3,
            study=self.study,
            preferred_site=self.site,
            availability=Application.Availability.FLEXIBLE,
            consent_given_at=timezone.now(),
            submitted_at=timezone.now(),
            status=Application.Status.ENROLLED
        )

        now = timezone.now()

        # 4 attended, 1 proposed
        for i in range(1, 5):
            Appointment.objects.create(
                application=app,
                site=self.site,
                kind=Appointment.Kind.VISIT,
                visit_number=i,
                status=Appointment.Status.ATTENDED,
                scheduled_for=now - timedelta(days=i)
            )

        visit5 = Appointment.objects.create(
            application=app,
            site=self.site,
            kind=Appointment.Kind.VISIT,
            visit_number=5,
            status=Appointment.Status.PROPOSED,
            scheduled_for=now - timedelta(days=1)
        )

        # Try to complete while visit 5 is proposed - should fail
        with self.assertRaises(ValidationError):
            complete_participation(app, self.coord_user)

        # Mark visit 5 as missed
        mark_visit(visit5, False, self.coord_user)

        # Now complete should succeed
        complete_participation(app, self.coord_user)

        # Verify status is completed
        app.refresh_from_db()
        self.assertEqual(app.status, Application.Status.COMPLETED)

    def test_08_rounding_earned_amount(self):
        """Test rounding: 100 comp, 3 visits: 1/3 = 33.33, 2/3 = 66.67"""
        # Create study with 100 compensation and 3 visits
        from datetime import date
        study = Study.objects.create(
            organisation=self.study.organisation,
            category=self.study.category,
            title='Rounding Test Study',
            status=Study.Status.PUBLISHED,
            description='Rounding test',
            study_type=Study.StudyType.OBSERVATIONAL,
            phase=Study.Phase.NOT_APPLICABLE,
            accepts_healthy_volunteers=True,
            sex_eligibility=Study.SexEligibility.ALL,
            min_age=21,
            max_age=65,
            smoker_rule=Study.SmokerRule.ANY,
            target_enrolment=40,
            total_visits=3,
            duration_weeks=3,
            visit_times=Study.VisitTimes.FLEXIBLE,
            compensation_amount=Decimal('100.00'),
            show_compensation=True,
            start_date=date(2026, 11, 15),
            recruitment_deadline=date(2026, 12, 31)
        )

        # Create application
        app = Application.objects.create(
            participant=self.participant,
            study=study,
            preferred_site=self.site,
            availability=Application.Availability.FLEXIBLE,
            consent_given_at=timezone.now(),
            submitted_at=timezone.now(),
            status=Application.Status.ENROLLED
        )

        now = timezone.now()

        # Create 3 visits, initially all proposed
        visits = []
        for i in range(1, 4):
            v = Appointment.objects.create(
                application=app,
                site=self.site,
                kind=Appointment.Kind.VISIT,
                visit_number=i,
                status=Appointment.Status.PROPOSED,
                scheduled_for=now - timedelta(days=5 - i)
            )
            visits.append(v)

        # Mark visit 1 attended: 1/3 × 100 = 33.333... → 33.33
        mark_visit(visits[0], True, self.coord_user)
        app.refresh_from_db()
        earned = earned_amount(app)
        self.assertEqual(earned, Decimal('33.33'))

        # Mark visit 2 attended: 2/3 × 100 = 66.666... → 66.67
        mark_visit(visits[1], True, self.coord_user)
        app.refresh_from_db()
        earned = earned_amount(app)
        self.assertEqual(earned, Decimal('66.67'))

    def test_09_zero_compensation_study(self):
        """Study with 0.00 compensation: amount_due = 0.00, request raises error"""
        # Create study with 0 compensation
        from datetime import date
        study = Study.objects.create(
            organisation=self.study.organisation,
            category=self.study.category,
            title='Free Study',
            status=Study.Status.PUBLISHED,
            description='Zero compensation test',
            study_type=Study.StudyType.OBSERVATIONAL,
            phase=Study.Phase.NOT_APPLICABLE,
            accepts_healthy_volunteers=True,
            sex_eligibility=Study.SexEligibility.ALL,
            min_age=21,
            max_age=65,
            smoker_rule=Study.SmokerRule.ANY,
            target_enrolment=40,
            total_visits=3,
            duration_weeks=3,
            visit_times=Study.VisitTimes.FLEXIBLE,
            compensation_amount=Decimal('0.00'),
            show_compensation=True,
            start_date=date(2026, 11, 15),
            recruitment_deadline=date(2026, 12, 31)
        )

        # Create application
        app = Application.objects.create(
            participant=self.participant,
            study=study,
            preferred_site=self.site,
            availability=Application.Availability.FLEXIBLE,
            consent_given_at=timezone.now(),
            submitted_at=timezone.now(),
            status=Application.Status.ENROLLED
        )

        now = timezone.now()

        # Create visits and mark attended
        for i in range(1, 4):
            v = Appointment.objects.create(
                application=app,
                site=self.site,
                kind=Appointment.Kind.VISIT,
                visit_number=i,
                status=Appointment.Status.ATTENDED,
                scheduled_for=now - timedelta(days=5 - i)
            )

        # amount_due should be 0.00
        due = amount_due(app)
        self.assertEqual(due, Decimal('0.00'))

        # request_payout should raise ValidationError
        with self.assertRaises(ValidationError):
            request_payout(app, self.coord_user)
