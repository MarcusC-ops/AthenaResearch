from datetime import date, timedelta

from django.contrib.auth.models import User
from django.test import TestCase

from core.models import (
    Application,
    ApplicationStatusEvent,
    Organisation,
    ParticipantProfile,
    Region,
    Site,
    Study,
    StudyCategory,
)
from core.services import (
    ALLOWED_MOVES,
    InvalidStatusMove,
    StudyFull,
    change_status,
    enrolled_count,
    is_full,
    refresh_capacity,
)


class StatusMachineTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.region = Region.objects.create(code='W', name='West', display_order=5)
        cls.category = StudyCategory.objects.create(
            name='Sleep', slug='sleep', ml_label='sleep',
            description='Sleep research.',
            display_order=1,
        )
        cls.organisation = Organisation.objects.create(
            name='Sleep Research Organisation',
            org_type=Organisation.OrganisationType.UNIVERSITY,
            contact_person='Research Lead',
            contact_email='lead@example.com',
        )
        cls.site = Site.objects.create(
            organisation=cls.organisation,
            name='Sleep Site W',
            address='1 West Road',
            postal_code='123456',
            region=cls.region,
        )
        cls.study = Study.objects.create(
            organisation=cls.organisation,
            category=cls.category,
            title='Sleep Habits Study',
            study_type=Study.StudyType.OBSERVATIONAL,
            phase=Study.Phase.NOT_APPLICABLE,
            accepts_healthy_volunteers=True,
            sex_eligibility=Study.SexEligibility.ALL,
            min_age=21,
            max_age=70,
            smoker_rule=Study.SmokerRule.ANY,
            target_enrolment=2,
            total_visits=1,
            duration_weeks=4,
            visit_times=Study.VisitTimes.FLEXIBLE,
            compensation_amount='0.00',
            show_compensation=False,
            start_date=date.today(),
            recruitment_deadline=date.today() + timedelta(days=30),
            status=Study.Status.PUBLISHED,
        )
        cls.study.sites.add(cls.site)
        cls.participants = []
        for index in range(1, 4):
            user = User.objects.create_user(
                username=f'p{index}@example.com',
                email=f'p{index}@example.com',
                first_name=f'P{index}',
                password='password',
            )
            cls.participants.append(
                ParticipantProfile.objects.create(
                    user=user,
                    mobile=f'+658000000{index}',
                    terms_accepted_at=__import__('django').utils.timezone.now(),
                    date_of_birth=date.today().replace(year=date.today().year - 24),
                    sex=ParticipantProfile.Sex.FEMALE,
                    region=cls.region,
                    onboarding_completed_at=__import__('django').utils.timezone.now(),
                )
            )
        cls.applications = []
        for profile in cls.participants:
            application = Application.objects.create(
                participant=profile,
                study=cls.study,
                status=Application.Status.SCREENING_PASSED,
                preferred_site=cls.site,
                availability=Application.Availability.FLEXIBLE,
                consent_given_at=__import__('django').utils.timezone.now(),
                submitted_at=__import__('django').utils.timezone.now(),
            )
            ApplicationStatusEvent.objects.create(
                application=application,
                to_status=Application.Status.SCREENING_PASSED,
            )
            cls.applications.append(application)

    def setUp(self):
        for application in self.applications:
            application.refresh_from_db()
        self.study.refresh_from_db()

    def test_01_change_to_enrolled_writes_event_and_counts(self):
        application = change_status(
            self.applications[0], Application.Status.ENROLLED
        )
        event = application.status_events.latest('id')
        self.assertEqual(application.status, Application.Status.ENROLLED)
        self.assertEqual((event.from_status, event.to_status), (
            Application.Status.SCREENING_PASSED, Application.Status.ENROLLED
        ))
        self.assertEqual(enrolled_count(self.study), 1)

    def test_02_invalid_move_keeps_enrolled_status(self):
        application = change_status(
            self.applications[0], Application.Status.ENROLLED
        )
        with self.assertRaises(InvalidStatusMove):
            change_status(application, Application.Status.SHORTLISTED)
        application.refresh_from_db()
        self.assertEqual(application.status, Application.Status.ENROLLED)

    def test_03_two_enrolments_make_study_full(self):
        change_status(self.applications[0], Application.Status.ENROLLED)
        change_status(self.applications[1], Application.Status.ENROLLED)
        self.study.refresh_from_db()
        self.assertEqual(self.study.status, Study.Status.FULL)

    def test_04_enrolling_when_full_raises_and_writes_no_event(self):
        change_status(self.applications[0], Application.Status.ENROLLED)
        change_status(self.applications[1], Application.Status.ENROLLED)
        events = self.applications[2].status_events.count()
        with self.assertRaises(StudyFull):
            change_status(self.applications[2], Application.Status.ENROLLED)
        self.applications[2].refresh_from_db()
        self.assertEqual(self.applications[2].status, Application.Status.SCREENING_PASSED)
        self.assertEqual(self.applications[2].status_events.count(), events)

    def test_05_screening_passed_can_be_waitlisted(self):
        application = change_status(
            self.applications[2], Application.Status.WAITLISTED
        )
        self.assertEqual(application.status, Application.Status.WAITLISTED)

    def test_06_withdrawing_reopens_a_place(self):
        change_status(self.applications[0], Application.Status.ENROLLED)
        change_status(self.applications[1], Application.Status.ENROLLED)
        change_status(self.applications[1], Application.Status.WITHDRAWN)
        self.study.refresh_from_db()
        self.assertEqual(self.study.status, Study.Status.PUBLISHED)
        self.assertEqual(self.study.places_left, 1)

    def test_07_completed_still_holds_a_place(self):
        change_status(self.applications[0], Application.Status.ENROLLED)
        change_status(self.applications[0], Application.Status.COMPLETED)
        self.assertEqual(enrolled_count(self.study), 1)

    def test_08_completed_is_final(self):
        change_status(self.applications[0], Application.Status.ENROLLED)
        change_status(self.applications[0], Application.Status.COMPLETED)
        with self.assertRaises(InvalidStatusMove):
            change_status(self.applications[0], Application.Status.UNDER_REVIEW)

    def test_09_every_application_status_has_allowed_moves(self):
        self.assertEqual(
            set(Application.Status.values),
            set(ALLOWED_MOVES),
        )

    def test_10_refresh_capacity_leaves_draft_unchanged(self):
        draft = Study.objects.create(
            organisation=self.organisation,
            category=self.category,
            title='Draft Sleep Study',
            study_type=Study.StudyType.OBSERVATIONAL,
            phase=Study.Phase.NOT_APPLICABLE,
            accepts_healthy_volunteers=True,
            sex_eligibility=Study.SexEligibility.ALL,
            min_age=21,
            max_age=70,
            smoker_rule=Study.SmokerRule.ANY,
            target_enrolment=1,
            total_visits=1,
            duration_weeks=4,
            visit_times=Study.VisitTimes.FLEXIBLE,
            compensation_amount='0.00',
            show_compensation=False,
            start_date=date.today(),
            recruitment_deadline=date.today() + timedelta(days=30),
            status=Study.Status.DRAFT,
        )
        draft.sites.add(self.site)
        Application.objects.create(
            participant=self.participants[0],
            study=draft,
            status=Application.Status.ENROLLED,
            preferred_site=self.site,
            availability=Application.Availability.FLEXIBLE,
            consent_given_at=__import__('django').utils.timezone.now(),
            submitted_at=__import__('django').utils.timezone.now(),
        )
        refresh_capacity(draft)
        draft.refresh_from_db()
        self.assertEqual(draft.status, Study.Status.DRAFT)
