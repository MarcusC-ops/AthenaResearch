from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from core.models import (
    Application,
    Notification,
    Organisation,
    ParticipantProfile,
    Payout,
    Region,
    Review,
    Site,
    Study,
    StudyCategory,
    SupportRequest,
)
from core.services import (
    approved_reviews,
    create_support_request,
    save_review,
    study_rating,
)


class ReviewsAndSupportTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.region = Region.objects.create(
            code='W',
            name='West',
            display_order=5,
        )
        cls.category = StudyCategory.objects.create(
            name='Cognitive',
            slug='cognitive',
            ml_label='cognitive',
            description='Cognitive research.',
            display_order=1,
        )
        cls.organisation = Organisation.objects.create(
            name='Cognitive Research Centre',
            org_type=Organisation.OrganisationType.UNIVERSITY,
            contact_person='Research Lead',
            contact_email='research@example.com',
        )
        cls.site = Site.objects.create(
            organisation=cls.organisation,
            name='Cognitive Site W',
            address='1 West Road',
            postal_code='123456',
            region=cls.region,
        )
        cls.study = Study.objects.create(
            organisation=cls.organisation,
            category=cls.category,
            title='Memory Games and Bilingual Brains',
            description='A study of memory and language.',
            study_type=Study.StudyType.BEHAVIOURAL,
            phase=Study.Phase.NOT_APPLICABLE,
            accepts_healthy_volunteers=True,
            sex_eligibility=Study.SexEligibility.ALL,
            min_age=21,
            max_age=80,
            smoker_rule=Study.SmokerRule.ANY,
            target_enrolment=40,
            total_visits=2,
            duration_weeks=8,
            visit_times=Study.VisitTimes.FLEXIBLE,
            compensation_amount='50.00',
            show_compensation=True,
            start_date=timezone.localdate(),
            recruitment_deadline=timezone.localdate() + timedelta(days=30),
            status=Study.Status.PUBLISHED,
        )
        cls.study.sites.add(cls.site)

        participant_group, _ = Group.objects.get_or_create(name='Participant')
        cls.profiles = {}
        cls.applications = {}
        for index in range(1, 7):
            user = User.objects.create_user(
                username=f'p{index}@example.com',
                email=f'p{index}@example.com',
                first_name=f'P{index}',
                password='Kopi-Teh-2026!',
            )
            user.groups.add(participant_group)
            profile = ParticipantProfile.objects.create(
                user=user,
                mobile=f'+658000000{index}',
                terms_accepted_at=timezone.now(),
                onboarding_completed_at=timezone.now(),
                date_of_birth=date.today().replace(year=date.today().year - 30),
                sex=ParticipantProfile.Sex.FEMALE,
                region=cls.region,
                employment=ParticipantProfile.Employment.FULL_TIME,
                education=ParticipantProfile.Education.DEGREE,
                height_cm='165.0',
                weight_kg='60.0',
                smoker=False,
                activity_level=ParticipantProfile.ActivityLevel.MODERATE,
                availability=ParticipantProfile.Availability.FLEXIBLE,
                max_travel_minutes=ParticipantProfile.TravelMinutes.THIRTY,
            )
            cls.profiles[f'P{index}'] = profile
            application = Application.objects.create(
                participant=profile,
                study=cls.study,
                status=(
                    Application.Status.COMPLETED
                    if index <= 5 else Application.Status.UNDER_REVIEW
                ),
                preferred_site=cls.site,
                availability=Application.Availability.FLEXIBLE,
                consent_given_at=timezone.now(),
                submitted_at=timezone.now(),
            )
            cls.applications[f'P{index}'] = application

        staff_group, _ = Group.objects.get_or_create(name='Staff')
        cls.staff_user = User.objects.create_user(
            username='priya@athena.sg',
            email='priya@athena.sg',
            first_name='Priya',
            last_name='Nair',
            password='Kopi-Teh-2026!',
        )
        cls.staff_user.groups.add(staff_group)

    def setUp(self):
        self.study.refresh_from_db()
        for profile in self.profiles.values():
            profile.refresh_from_db()
        for application in self.applications.values():
            application.refresh_from_db()
        self.staff_user.refresh_from_db()

    def test_01_saving_review_creates_pending_review_without_rating(self):
        review = save_review(
            self.profiles['P1'],
            self.study,
            5,
            'Fun and well organised',
        )

        self.assertEqual(review.status, Review.Status.PENDING)
        self.assertEqual(review.rating, 5)
        self.assertEqual(study_rating(self.study), (None, 0))

    def test_02_approved_review_is_included_in_study_rating(self):
        review = save_review(self.profiles['P1'], self.study, 5)
        review.status = Review.Status.APPROVED
        review.save(update_fields=['status', 'updated_at'])

        self.assertEqual(study_rating(self.study), (5.0, 1))
        self.assertEqual(list(approved_reviews(self.study)), [review])

    def test_03_incomplete_participant_cannot_review_study(self):
        with self.assertRaisesMessage(ValidationError, 'after you complete it'):
            save_review(self.profiles['P6'], self.study, 5)

    def test_04_pending_review_can_be_edited_without_duplicate(self):
        review = save_review(self.profiles['P2'], self.study, 4)
        updated_review = save_review(self.profiles['P2'], self.study, 3)

        self.assertEqual(updated_review.pk, review.pk)
        self.assertEqual(updated_review.rating, 3)
        self.assertEqual(
            Review.objects.filter(
                participant=self.profiles['P2'],
                study=self.study,
            ).count(),
            1,
        )

    def test_05_checked_review_cannot_be_edited(self):
        review = save_review(self.profiles['P2'], self.study, 4)
        review.status = Review.Status.APPROVED
        review.save(update_fields=['status', 'updated_at'])

        with self.assertRaisesMessage(ValidationError, 'already been checked'):
            save_review(self.profiles['P2'], self.study, 3)

    def test_06_review_rating_database_range(self):
        for invalid_rating in (6, 0):
            with self.subTest(rating=invalid_rating):
                with self.assertRaises(IntegrityError):
                    with transaction.atomic():
                        Review.objects.create(
                            participant=self.profiles['P1'],
                            study=self.study,
                            rating=invalid_rating,
                        )

        lower = Review.objects.create(
            participant=self.profiles['P1'],
            study=self.study,
            rating=1,
        )
        upper = Review.objects.create(
            participant=self.profiles['P2'],
            study=self.study,
            rating=5,
        )
        self.assertEqual((lower.rating, upper.rating), (1, 5))

    def test_07_review_pair_is_unique_in_database(self):
        Review.objects.create(
            participant=self.profiles['P1'],
            study=self.study,
            rating=5,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Review.objects.create(
                    participant=self.profiles['P1'],
                    study=self.study,
                    rating=4,
                )

    def test_08_study_rating_counts_approved_reviews_only(self):
        statuses_and_ratings = (
            ('P1', 5, Review.Status.APPROVED),
            ('P2', 3, Review.Status.APPROVED),
            ('P3', 4, Review.Status.APPROVED),
            ('P4', 1, Review.Status.REJECTED),
        )
        for participant, rating, status in statuses_and_ratings:
            Review.objects.create(
                participant=self.profiles[participant],
                study=self.study,
                rating=rating,
                status=status,
                rejection_reason=(
                    'Not suitable for publication.'
                    if status == Review.Status.REJECTED else ''
                ),
            )

        self.assertEqual(study_rating(self.study), (4.0, 3))
        self.assertEqual(
            list(approved_reviews(self.study).values_list('rating', flat=True)),
            [4, 3, 5],
        )

    def test_09_payout_amount_must_be_positive_in_database(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Payout.objects.create(
                    application=self.applications['P1'],
                    amount=Decimal('0.00'),
                    status=Payout.Status.PAID,
                )

    def test_10_payout_reference_is_unique_in_database(self):
        Payout.objects.create(
            application=self.applications['P1'],
            amount=Decimal('10.00'),
            status=Payout.Status.PAID,
            reference='PN-2026-000001',
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Payout.objects.create(
                    application=self.applications['P2'],
                    amount=Decimal('20.00'),
                    status=Payout.Status.PAID,
                    reference='PN-2026-000001',
                )

    def test_11_support_request_saves_and_notifies_staff(self):
        support_request = create_support_request(
            self.applications['P1'],
            SupportRequest.Topic.COMPENSATION,
            'When will I be paid?',
        )

        self.assertEqual(support_request.status, SupportRequest.Status.OPEN)
        self.assertEqual(
            Notification.objects.filter(user=self.staff_user).count(),
            1,
        )
        self.assertIn(
            'Compensation',
            Notification.objects.get(user=self.staff_user).message,
        )
