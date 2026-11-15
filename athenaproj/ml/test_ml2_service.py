import tempfile
from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from core.models import (
    AppSetting,
    Application,
    ApplicationAnswer,
    Organisation,
    ParticipantProfile,
    PreScreenQuestion,
    Region,
    Site,
    Study,
    StudyCategory,
)
from core.services import get_settings
from ml.services import build_ml2_features, model_health, predict_screening


class ML2ServiceTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.region = Region.objects.create(code='W', name='West', display_order=5)
        cls.category = StudyCategory.objects.create(
            name='Sleep', slug='sleep', ml_label='sleep',
            description='Sleep research.', display_order=1,
        )
        cls.organisation = Organisation.objects.create(
            name='Sleep Research Organisation',
            org_type=Organisation.OrganisationType.UNIVERSITY,
            contact_person='Research Lead',
            contact_email='lead@example.com',
        )
        cls.site = Site.objects.create(
            organisation=cls.organisation,
            name='W1',
            address='1 West Road',
            postal_code='123456',
            region=cls.region,
        )
        user = User.objects.create_user(
            username='aisyah@example.com', email='aisyah@example.com'
        )
        cls.profile = ParticipantProfile.objects.create(
            user=user,
            mobile='+6591234567',
            terms_accepted_at=timezone.now(),
            onboarding_completed_at=timezone.now(),
            date_of_birth=date.today().replace(year=date.today().year - 24),
            sex=ParticipantProfile.Sex.FEMALE,
            region=cls.region,
            height_cm='160.0',
            weight_kg='52.0',
            smoker=False,
        )
        cls.study = Study.objects.create(
            organisation=cls.organisation,
            category=cls.category,
            title='Sleep Study',
            study_type=Study.StudyType.OBSERVATIONAL,
            phase=Study.Phase.NOT_APPLICABLE,
            accepts_healthy_volunteers=True,
            sex_eligibility=Study.SexEligibility.ALL,
            min_age=21,
            max_age=65,
            smoker_rule=Study.SmokerRule.ANY,
            target_enrolment=60,
            total_visits=4,
            duration_weeks=8,
            visit_times=Study.VisitTimes.WEEKDAY_EVENINGS,
            compensation_amount='0.00',
            show_compensation=False,
            start_date=date.today(),
            recruitment_deadline=date.today() + timedelta(days=30),
            status=Study.Status.PUBLISHED,
        )
        cls.study.sites.add(cls.site)
        cls.q1 = PreScreenQuestion.objects.create(
            study=cls.study, text='Q1', order=1, preferred_answer='Yes'
        )
        cls.q2 = PreScreenQuestion.objects.create(
            study=cls.study, text='Q2', order=2, preferred_answer='No'
        )
        cls.application = Application.objects.create(
            participant=cls.profile,
            study=cls.study,
            status=Application.Status.UNDER_REVIEW,
            preferred_site=cls.site,
            availability=Application.Availability.WEEKDAY_EVENINGS,
            consent_given_at=timezone.now(),
            submitted_at=timezone.now(),
        )
        ApplicationAnswer.objects.create(
            application=cls.application, question=cls.q1, answer='Yes'
        )
        ApplicationAnswer.objects.create(
            application=cls.application, question=cls.q2, answer='Yes'
        )

    def test_01_build_ml2_features_has_expected_values(self):
        features = build_ml2_features(self.application)
        self.assertEqual(len(features), 18)
        self.assertEqual(features['region_match'], 1)
        self.assertEqual(features['availability_match'], 1)
        self.assertEqual(features['preferred_answer_share'], 0.5)
        self.assertEqual(features['age_range_width'], 44)

    def test_02_predict_screening_returns_probability_and_version(self):
        result = predict_screening(self.application)
        self.assertIsNotNone(result)
        self.assertGreaterEqual(result['probability'], 0)
        self.assertLessEqual(result['probability'], 1)
        self.assertEqual(result['version'], 'ml2-v1.0')

    def test_03_predict_screening_logs_success(self):
        predict_screening(self.application)
        log = self.application.prediction_logs.get(model_name='ml2')
        self.assertTrue(log.succeeded)
        self.assertEqual(log.application_id, self.application.pk)

    def test_04_missing_model_logs_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch('ml.services.MODEL_DIR', directory):
                result = predict_screening(self.application)
        self.assertIsNone(result)
        log = self.application.prediction_logs.get(model_name='ml2')
        self.assertFalse(log.succeeded)

    def test_05_model_health_reports_both_models(self):
        self.assertEqual(model_health(), {'ml1': True, 'ml2': True})

    def test_06_get_settings_creates_defaults(self):
        settings = get_settings()
        self.assertEqual(settings.pk, 1)
        self.assertEqual(settings.ml2_high_threshold, 0.70)
        self.assertEqual(settings.ml2_medium_threshold, 0.40)

    def test_07_invalid_threshold_order_raises_integrity_error(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                AppSetting.objects.create(
                    ml2_medium_threshold=0.80, ml2_high_threshold=0.70
                )

    def test_08_threshold_bounds_raise_integrity_error(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                AppSetting.objects.create(
                    ml2_medium_threshold=0.0, ml2_high_threshold=0.70
                )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                AppSetting.objects.create(
                    ml2_medium_threshold=0.40, ml2_high_threshold=1.0
                )
