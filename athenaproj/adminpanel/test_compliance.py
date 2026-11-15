from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from core.models import (
    Notification,
    Organisation,
    PreScreenQuestion,
    Region,
    Site,
    StaffProfile,
    Study,
    StudyCategory,
)
from core.services import run_compliance_checks, submit_study_for_review


class StudyComplianceTests(TestCase):
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
        cls.organisation = Organisation.objects.create(
            name='Kent Ridge Clinical Research Centre',
            org_type=Organisation.OrganisationType.UNIVERSITY,
            contact_person='Daniel Lim',
            contact_email='drlim@kentridge-crc.sg',
        )
        cls.site = Site.objects.create(
            organisation=cls.organisation,
            name='W1',
            address='21 Lower Kent Ridge Road',
            postal_code='119077',
            region=cls.region,
        )

        cls.coordinator = User.objects.create_user(
            username='drlim@kentridge-crc.sg',
            email='drlim@kentridge-crc.sg',
            first_name='Daniel',
            last_name='Lim',
        )
        cls.coordinator.groups.add(Group.objects.get(name='Coordinator'))
        StaffProfile.objects.create(
            user=cls.coordinator,
            organisation=cls.organisation,
            job_title='Clinical research coordinator',
            mobile='+6591234567',
        )

        cls.staff = User.objects.create_user(
            username='priya@athena.sg',
            email='priya@athena.sg',
            first_name='Priya',
            last_name='Nair',
        )
        cls.staff.groups.add(Group.objects.get(name='Staff'))
        StaffProfile.objects.create(
            user=cls.staff,
            organisation=None,
            job_title='Operations executive',
            mobile='+6591234567',
        )

        today = timezone.localdate()
        deadline = today + timedelta(days=30)
        cls.study = Study.objects.create(
            organisation=cls.organisation,
            category=cls.category,
            title='Sleep Habits Study',
            description='A study about sleep habits.',
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
            recruitment_deadline=deadline,
            irb_name='NUS-IRB',
            irb_reference='NUS-IRB-2026-0412',
            irb_expiry=deadline + timedelta(days=90),
            irb_approved_text=True,
            status=Study.Status.DRAFT,
            created_by=cls.coordinator,
            last_edited_by=cls.coordinator,
        )
        cls.study.sites.add(cls.site)
        cls.question = PreScreenQuestion.objects.create(
            study=cls.study,
            text='Do you work night shifts?',
            order=1,
            options='Yes\nNo',
            preferred_answer='No',
            disqualifying_answer='',
        )

    def setUp(self):
        self.study.refresh_from_db()
        self.question = PreScreenQuestion.objects.get(pk=type(self).question.pk)
        self.question.refresh_from_db()
        self.coordinator.refresh_from_db()
        self.staff.refresh_from_db()

    def check_by_code(self, code):
        return next(
            result for result in run_compliance_checks(self.study)
            if result.code == code
        )

    def test_01_all_seven_compliance_checks_pass(self):
        self.assertEqual(len(run_compliance_checks(self.study)), 7)
        self.assertTrue(all(result.passed for result in run_compliance_checks(self.study)))

    def test_02_earn_wording_fails(self):
        self.study.description = 'Earn $120 for your time'
        result = self.check_by_code('wording')
        self.assertFalse(result.passed)
        self.assertIn('earn', result.detail.lower())

    def test_03_fast_cash_and_guaranteed_are_reported(self):
        self.study.description = 'Fast cash and guaranteed results'
        result = self.check_by_code('wording')
        self.assertFalse(result.passed)
        self.assertIn('fast cash', result.detail.lower())
        self.assertIn('guaranteed', result.detail.lower())

    def test_04_word_boundaries_do_not_match_substrings(self):
        self.study.description = 'Freedom to withdraw at any time, earnestly explained'
        self.assertTrue(self.check_by_code('wording').passed)

    def test_05_irb_expiry_must_be_after_deadline(self):
        self.study.irb_expiry = self.study.recruitment_deadline
        self.assertFalse(self.check_by_code('irb_expiry').passed)
        self.study.irb_expiry = self.study.recruitment_deadline + timedelta(days=1)
        self.assertTrue(self.check_by_code('irb_expiry').passed)

    def test_06_compensation_display_requires_approved_text(self):
        self.study.irb_approved_text = False
        self.study.show_compensation = True
        self.assertFalse(self.check_by_code('compensation').passed)
        self.study.show_compensation = False
        self.assertTrue(self.check_by_code('compensation').passed)

    def test_07_missing_question_fails_check(self):
        self.question.delete()
        self.study.refresh_from_db()
        self.assertFalse(self.check_by_code('questions').passed)

    def test_08_submission_with_a_failed_check_keeps_draft(self):
        self.study.description = 'Earn $120 for your time'
        self.study.save(update_fields=['description', 'updated_at'])
        with self.assertRaisesMessage(
            ValidationError,
            'Fix the failed checks before you submit.',
        ):
            submit_study_for_review(self.study, self.coordinator)
        self.study.refresh_from_db()
        self.assertEqual(self.study.status, Study.Status.DRAFT)

    def test_09_successful_submission_sets_status_and_notifies_staff(self):
        submitted = submit_study_for_review(self.study, self.coordinator)
        self.study.refresh_from_db()
        self.assertEqual(self.study.status, Study.Status.PENDING_REVIEW)
        self.assertIsNotNone(self.study.submitted_at)
        self.assertEqual(submitted.pk, self.study.pk)
        self.assertTrue(
            Notification.objects.filter(
                user=self.staff,
                message__contains='Sleep Habits Study',
            ).exists()
        )

    def test_10_submitting_twice_raises_validation_error(self):
        submit_study_for_review(self.study, self.coordinator)
        self.study.refresh_from_db()
        with self.assertRaisesMessage(
            ValidationError,
            'Only draft or returned listings can be edited.',
        ):
            submit_study_for_review(self.study, self.coordinator)
