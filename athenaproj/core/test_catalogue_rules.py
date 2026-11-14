from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models.deletion import RestrictedError
from django.test import TestCase
from django.utils import timezone

from core.models import (
    Organisation,
    PreScreenQuestion,
    Region,
    Site,
    Study,
    StudyCategory,
)


class CatalogueRulesTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        region = Region.objects.create(code='W', name='West', display_order=5)
        category = StudyCategory.objects.create(
            name='Sleep',
            slug='sleep',
            ml_label='sleep',
            description='Explore sleep research.',
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
            name='Kent Ridge Clinic',
            address='21 Lower Kent Ridge Road',
            postal_code='119077',
            region=region,
        )
        cls.study = Study.objects.create(
            organisation=organisation,
            category=category,
            title='Sleep Habits Study',
            description='A study about sleep habits.',
            study_type=Study.StudyType.OBSERVATIONAL,
            accepts_healthy_volunteers=True,
            min_age=21,
            max_age=65,
            target_enrolment=40,
            total_visits=4,
            duration_weeks=8,
            visit_times=Study.VisitTimes.WEEKDAY_EVENINGS,
            compensation_amount='120.00',
            show_compensation=True,
            start_date=timezone.localdate(),
            recruitment_deadline=timezone.localdate() + timedelta(days=30),
            status=Study.Status.PUBLISHED,
        )
        cls.study.sites.add(site)
        cls.question = PreScreenQuestion.objects.create(
            study=cls.study,
            text='Do you work night shifts?',
            options='Yes\nNo',
            disqualifying_answer='Yes',
            preferred_answer='No',
            order=1,
        )

    def setUp(self):
        self.study.refresh_from_db()
        self.question.refresh_from_db()

    def test_01_age_order_constraint_raises_integrity_error(self):
        with self.assertRaises(IntegrityError):
            with self.atomic():
                self.study.min_age = 50
                self.study.max_age = 30
                self.study.save()

    def test_02_bmi_order_constraint_raises_integrity_error(self):
        with self.assertRaises(IntegrityError):
            with self.atomic():
                self.study.min_bmi = Decimal('30.0')
                self.study.max_bmi = Decimal('20.0')
                self.study.save()

    def test_03_target_minimum_constraint_raises_integrity_error(self):
        with self.assertRaises(IntegrityError):
            with self.atomic():
                self.study.target_enrolment = 0
                self.study.save()

    def test_04_visits_minimum_constraint_raises_integrity_error(self):
        with self.assertRaises(IntegrityError):
            with self.atomic():
                self.study.total_visits = 0
                self.study.save()

    def test_05_compensation_non_negative_constraint_raises_integrity_error(self):
        with self.assertRaises(IntegrityError):
            with self.atomic():
                self.study.compensation_amount = Decimal('-1.00')
                self.study.save()

    def test_06_boundary_values_save(self):
        self.study.min_age = 21
        self.study.max_age = 21
        self.study.target_enrolment = 1
        self.study.total_visits = 1
        self.study.compensation_amount = Decimal('0.00')
        self.study.save()
        self.study.refresh_from_db()
        self.assertEqual(self.study.target_enrolment, 1)

    def test_07_non_interventional_phase_raises_validation_error(self):
        self.study.phase = Study.Phase.PHASE_2
        with self.assertRaisesMessage(ValidationError, 'Only interventional studies have a phase.'):
            self.study.full_clean()

    def test_08_same_day_deadline_raises_validation_error(self):
        self.study.recruitment_deadline = self.study.start_date
        with self.assertRaisesMessage(
            ValidationError,
            'The recruitment deadline must be after the start date.',
        ):
            self.study.full_clean()

    def test_09_duplicate_organisation_raises_integrity_error(self):
        with self.assertRaises(IntegrityError):
            with self.atomic():
                Organisation.objects.create(
                    name='Kent Ridge Clinical Research Centre',
                    org_type=Organisation.OrganisationType.UNIVERSITY,
                    contact_person='Another Person',
                    contact_email='another@example.sg',
                )

    def test_10_deleting_organisation_raises_restricted_error(self):
        with self.assertRaises(RestrictedError):
            self.study.organisation.delete()
        self.assertTrue(
            Organisation.objects.filter(name='Kent Ridge Clinical Research Centre').exists()
        )

    def test_11_invalid_disqualifying_answer_raises_validation_error(self):
        self.question.disqualifying_answer = 'Maybe'
        with self.assertRaises(ValidationError):
            self.question.full_clean()

    def test_12_deleting_study_deletes_question(self):
        question_id = self.question.id
        self.study.delete()
        self.assertFalse(PreScreenQuestion.objects.filter(id=question_id).exists())

    def atomic(self):
        from django.db import transaction

        return transaction.atomic()
