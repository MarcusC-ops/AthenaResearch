from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.utils import timezone

from core.models import Condition, ParticipantProfile, PredictionLog, Region, StudyCategory
from core.services import refresh_interest_predictions
from ml.services import build_ml1_features, model_health, predict_interest


class ML1ServiceTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.region_w = Region.objects.create(code='W', name='West', display_order=1)
        cls.asthma = Condition.objects.create(name='Asthma', ml_flag='respiratory')
        cls.insomnia = Condition.objects.create(name='Insomnia', ml_flag='sleep')
        labels = [
            'cognitive', 'healthy_phase1', 'heart', 'lifestyle', 'mental_health',
            'metabolic', 'respiratory', 'sleep', 'womens_health',
        ]
        for order, label in enumerate(labels, 1):
            StudyCategory.objects.create(
                name=label.replace('_', ' ').title(),
                slug=label,
                ml_label=label,
                description=f'{label} research.',
                display_order=order,
            )
        cls.user = User.objects.create_user(
            username='aisyah@example.com', email='aisyah@example.com',
            first_name='Aisyah', last_name='Rahman',
            password='Kopi-Teh-2026!',
        )
        cls.user.groups.add(Group.objects.get(name='Participant'))
        cls.profile = ParticipantProfile.objects.create(
            user=cls.user, mobile='+6591234567', terms_accepted_at=timezone.now(),
            date_of_birth=date.today().replace(year=date.today().year - 24),
            sex='female', region=cls.region_w, employment='student',
            education='degree', height_cm='160.0', weight_kg='52.0',
            smoker=False, activity_level='high', motivation='help_research',
            availability='weekday_evenings', max_travel_minutes='30',
            consent_matching=True, onboarding_completed_at=timezone.now(),
        )
        cls.profile.conditions.add(cls.insomnia)

    def test_01_build_ml1_features_has_expected_flags(self):
        self.profile.refresh_from_db()
        features = build_ml1_features(self.profile)
        self.assertEqual(len(features), 18)
        self.assertEqual(features['flag_sleep'], 1)
        self.assertEqual(features['flag_respiratory'], 0)

    def test_02_predict_interest_returns_three_different_labels(self):
        self.profile.refresh_from_db()
        result = predict_interest(self.profile)
        labels = [item['category'] for item in result['top_three']]
        self.assertEqual(len(labels), 3)
        self.assertEqual(len(set(labels)), 3)
        self.assertTrue(set(labels).issubset(set(
            StudyCategory.objects.values_list('ml_label', flat=True)
        )))

    def test_03_predict_interest_writes_success_log(self):
        self.profile.refresh_from_db()
        predict_interest(self.profile)
        log = PredictionLog.objects.get(participant=self.profile)
        self.assertEqual(PredictionLog.objects.filter(participant=self.profile).count(), 1)
        self.assertEqual(log.model_name, 'ml1')
        self.assertTrue(log.succeeded)
        self.assertEqual(log.model_version, 'ml1-v1.1')

    def test_04_predict_interest_logs_missing_model_failure(self):
        self.profile.refresh_from_db()
        with TemporaryDirectory() as directory:
            with patch('ml.services.MODEL_DIR', Path(directory)):
                self.assertIsNone(predict_interest(self.profile))
        log = PredictionLog.objects.get(participant=self.profile)
        self.assertFalse(log.succeeded)
        self.assertTrue(log.error_message)

    def test_05_model_health_reflects_model_files(self):
        self.assertEqual(model_health(), {'ml1': True, 'ml2': True})
        with TemporaryDirectory() as directory:
            with patch('ml.services.MODEL_DIR', Path(directory)):
                self.assertEqual(model_health(), {'ml1': False, 'ml2': False})

    def test_06_refresh_interest_predictions_stores_prediction(self):
        self.profile.refresh_from_db()
        refresh_interest_predictions(self.profile)
        self.profile.refresh_from_db()
        self.assertEqual(len(self.profile.ml1_categories), 3)
        self.assertEqual(self.profile.ml1_model_version, 'ml1-v1.1')
        self.assertIsNotNone(self.profile.ml1_predicted_at)

    def test_07_refresh_without_consent_clears_prediction_without_log(self):
        self.profile.refresh_from_db()
        refresh_interest_predictions(self.profile)
        log_count = PredictionLog.objects.filter(participant=self.profile).count()
        self.profile.consent_matching = False
        self.profile.save(update_fields=['consent_matching'])
        refresh_interest_predictions(self.profile)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.ml1_categories, [])
        self.assertEqual(self.profile.ml1_model_version, '')
        self.assertIsNone(self.profile.ml1_predicted_at)
        self.assertEqual(PredictionLog.objects.filter(participant=self.profile).count(), log_count)
