from datetime import timedelta

from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from core.models import (
    Application,
    Organisation,
    ParticipantProfile,
    PredictionLog,
    Region,
    Site,
    Study,
    StudyCategory,
)
from core.services import band_for, get_settings, override_rate, update_thresholds
from adminpanel.forms import ThresholdForm
from ml.services import model_card, prediction_stats


class MLMonitorTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.password = 'Kopi-Teh-2026!'
        cls.region = Region.objects.create(code='W', name='West', display_order=5)
        cls.category = StudyCategory.objects.create(
            name='Sleep',
            slug='sleep',
            ml_label='sleep',
            description='Sleep research.',
            display_order=1,
        )
        cls.organisation = Organisation.objects.create(
            name='Test Organisation',
            org_type=Organisation.OrganisationType.UNIVERSITY,
            contact_person='Priya Nair',
            contact_email='priya@test.sg',
        )
        cls.site = Site.objects.create(
            organisation=cls.organisation,
            name='West site',
            address='1 Test Road',
            postal_code='123456',
            region=cls.region,
        )
        cls.admin = cls.make_user('admin@athena.sg', 'Wei Ling', 'Tan', 'Admin')
        cls.staff = cls.make_user('priya@athena.sg', 'Priya', 'Nair', 'Staff')
        cls.study = Study.objects.create(
            organisation=cls.organisation,
            category=cls.category,
            title='Sleep study',
            description='A study about sleep.',
            study_type=Study.StudyType.OBSERVATIONAL,
            accepts_healthy_volunteers=True,
            min_age=21,
            max_age=80,
            target_enrolment=10,
            total_visits=1,
            duration_weeks=4,
            visit_times=Study.VisitTimes.FLEXIBLE,
            compensation_amount=100,
            show_compensation=True,
            start_date=timezone.localdate(),
            recruitment_deadline=timezone.localdate() + timedelta(days=30),
            status=Study.Status.PUBLISHED,
        )
        cls.study.sites.add(cls.site)
        cls.applications = []
        for index, band in enumerate(
            (Application.Band.HIGH, Application.Band.MEDIUM,
             Application.Band.LOW, Application.Band.UNSCORED),
            start=1,
        ):
            user = cls.make_user(
                f'participant{index}@example.com',
                f'Participant{index}',
                'Test',
                'Participant',
            )
            profile = ParticipantProfile.objects.create(
                user=user,
                mobile=f'+65912345{index:02d}',
                terms_accepted_at=timezone.now(),
                date_of_birth=timezone.localdate().replace(year=1990),
                sex=ParticipantProfile.Sex.FEMALE,
                region=cls.region,
                employment=ParticipantProfile.Employment.FULL_TIME,
                education=ParticipantProfile.Education.DEGREE,
                height_cm=170,
                weight_kg=70,
                smoker=False,
                activity_level=ParticipantProfile.ActivityLevel.MODERATE,
                motivation=ParticipantProfile.Motivation.HELP_RESEARCH,
                availability=ParticipantProfile.Availability.FLEXIBLE,
                max_travel_minutes='30',
            )
            application = Application.objects.create(
                participant=profile,
                study=cls.study,
                preferred_site=cls.site,
                availability=Application.Availability.FLEXIBLE,
                consent_given_at=timezone.now(),
                submitted_at=timezone.now(),
                ml2_band=band,
                ml2_probability=None if band == Application.Band.UNSCORED else 0.8,
            )
            if band == Application.Band.MEDIUM:
                application.original_band = Application.Band.MEDIUM
                application.ml2_band = Application.Band.HIGH
                application.band_overridden = True
                application.save(update_fields=[
                    'original_band', 'ml2_band', 'band_overridden', 'updated_at',
                ])
            cls.applications.append(application)
        now = timezone.now()
        for days_ago, succeeded in ((1, True), (2, True), (3, False), (40, True)):
            log = PredictionLog.objects.create(
                model_name=PredictionLog.ModelName.ML2,
                model_version='ml2-v1.0',
                application=cls.applications[0],
                participant=cls.applications[0].participant,
                features={},
                output={'band': 'high', 'probability': 0.8},
                succeeded=succeeded,
                error_message='' if succeeded else 'test failure',
            )
            PredictionLog.objects.filter(pk=log.pk).update(
                created_at=now - timedelta(days=days_ago),
            )

    @classmethod
    def make_user(cls, email, first_name, last_name, group_name):
        user = User.objects.create_user(
            username=email,
            email=email,
            first_name=first_name,
            last_name=last_name,
            password=cls.password,
        )
        user.groups.add(Group.objects.get(name=group_name))
        return user

    def test_01_model_card_reads_ml2_metadata(self):
        card = model_card('ml2')
        self.assertEqual(card['version'], 'ml2-v1.0')
        self.assertTrue(card['loaded'])
        self.assertIn('roc_auc', card['metrics'])

    def test_02_prediction_stats_counts_recent_predictions_and_failures(self):
        self.assertEqual(
            prediction_stats('ml2'),
            {'count': 3, 'failures': 1},
        )

    def test_03_override_rate_counts_scored_overrides(self):
        overridden, scored, percentage = override_rate()
        self.assertEqual((overridden, scored, round(percentage)), (1, 3, 33))

    def test_04_threshold_form_rejects_reversed_order(self):
        form = ThresholdForm({'high': '0.40', 'medium': '0.70'})
        self.assertFalse(form.is_valid())
        self.assertIn('High must be above Medium', str(form.errors))

    def test_05_threshold_form_checks_boundaries(self):
        self.assertFalse(ThresholdForm({'high': '1.00', 'medium': '0.40'}).is_valid())
        self.assertTrue(ThresholdForm({'high': '0.99', 'medium': '0.01'}).is_valid())

    def test_06_update_thresholds_only_affects_new_bands(self):
        update_thresholds(0.75, 0.40, self.admin)
        self.assertEqual(band_for(0.72, get_settings()), Application.Band.MEDIUM)
        self.assertEqual(
            self.applications[0].ml2_band,
            Application.Band.HIGH,
        )

    def test_07_staff_can_monitor_but_cannot_change_settings(self):
        self.client.force_login(self.staff)
        response = self.client.get('/panel/ml/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'ML-2 never declines anyone')
        self.assertContains(response, 'Loaded')
        response = self.client.get('/panel/ml/settings/')
        self.assertEqual(response.status_code, 403)

    def test_08_admin_can_save_thresholds_and_monitor_shows_them(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            '/panel/ml/settings/',
            {'high': '0.80', 'medium': '0.50'},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Current thresholds: High from 0.8, Medium from 0.5.')
