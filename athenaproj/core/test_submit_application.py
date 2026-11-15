from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from core.models import (
    Application,
    ApplicationAnswer,
    ApplicationStatusEvent,
    Organisation,
    ParticipantProfile,
    PreScreenQuestion,
    Region,
    Site,
    Study,
    StudyCategory,
)
from core.services import NotEligible, submit_application


class SubmitApplicationTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.region = Region.objects.create(code='W', name='West', display_order=5)
        cls.category = StudyCategory.objects.create(
            name='Healthy Volunteer Phase I',
            slug='healthy-volunteer-phase-1',
            ml_label='healthy_phase1',
            description='Healthy volunteer research.',
            display_order=1,
        )
        cls.organisation = Organisation.objects.create(
            name='Kent Ridge Clinical Research Centre',
            org_type=Organisation.OrganisationType.UNIVERSITY,
            contact_person='Daniel Lim',
            contact_email='drlim@example.com',
        )
        cls.site = Site.objects.create(
            organisation=cls.organisation,
            name='S1',
            address='1 West Road',
            postal_code='123456',
            region=cls.region,
        )
        user = User.objects.create_user(
            username='aisyah@example.com',
            email='aisyah@example.com',
            first_name='Aisyah',
            password='password',
        )
        cls.profile = ParticipantProfile.objects.create(
            user=user,
            mobile='+6591234567',
            terms_accepted_at=timezone.now(),
            onboarding_completed_at=timezone.now(),
            date_of_birth=date.today().replace(year=date.today().year - 24),
            sex=ParticipantProfile.Sex.FEMALE,
            region=cls.region,
            smoker=False,
            height_cm='160.0',
            weight_kg='52.0',
        )
        cls.blood = cls.make_study('Blood Sample Bank', 60, 21, 70)
        cls.flu = cls.make_study('Flu Vaccine Exercise Study', 1, 21, 70)
        cls.heart = cls.make_study('Midlife Heart Study', 60, 40, 65)
        cls.q1 = PreScreenQuestion.objects.create(
            study=cls.blood,
            text='Are you comfortable having a small blood sample taken?',
            order=1,
            preferred_answer='Yes',
            disqualifying_answer='No',
        )
        cls.q2 = PreScreenQuestion.objects.create(
            study=cls.blood,
            text='Do you have a strong fear of needles that makes you feel faint?',
            order=2,
            preferred_answer='No',
            disqualifying_answer='Yes',
        )
        for study in (cls.flu, cls.heart):
            PreScreenQuestion.objects.create(
                study=study, text='Question', order=1, preferred_answer='Yes'
            )
        other_user = User.objects.create_user(
            username='other@example.com', email='other@example.com'
        )
        other = ParticipantProfile.objects.create(
            user=other_user,
            mobile='+6581234567',
            terms_accepted_at=timezone.now(),
            onboarding_completed_at=timezone.now(),
            date_of_birth=date.today().replace(year=date.today().year - 24),
            sex=ParticipantProfile.Sex.FEMALE,
            region=cls.region,
            height_cm='160.0',
            weight_kg='52.0',
        )
        Application.objects.create(
            participant=other,
            study=cls.flu,
            status=Application.Status.ENROLLED,
            preferred_site=cls.site,
            availability=Application.Availability.FLEXIBLE,
            consent_given_at=timezone.now(),
            submitted_at=timezone.now(),
        )

    @classmethod
    def make_study(cls, title, target, min_age, max_age):
        study = Study.objects.create(
            organisation=cls.organisation,
            category=cls.category,
            title=title,
            study_type=Study.StudyType.OBSERVATIONAL,
            phase=Study.Phase.NOT_APPLICABLE,
            accepts_healthy_volunteers=True,
            sex_eligibility=Study.SexEligibility.ALL,
            min_age=min_age,
            max_age=max_age,
            smoker_rule=Study.SmokerRule.ANY,
            target_enrolment=target,
            total_visits=1,
            duration_weeks=4,
            visit_times=Study.VisitTimes.FLEXIBLE,
            compensation_amount='0.00',
            show_compensation=False,
            start_date=date.today(),
            recruitment_deadline=date.today() + timedelta(days=30),
            status=Study.Status.PUBLISHED,
        )
        study.sites.add(cls.site)
        return study

    def answers(self, q1='Yes', q2='No'):
        return {self.q1.pk: q1, self.q2.pk: q2}

    def setUp(self):
        self.profile.refresh_from_db()
        for study in (self.blood, self.flu, self.heart):
            study.refresh_from_db()

    def submit(self, study=None, answers=None, consent=True):
        return submit_application(
            self.profile,
            study or self.blood,
            answers if answers is not None else self.answers(),
            self.site.pk,
            Application.Availability.FLEXIBLE,
            consent,
        )

    def test_01_disqualifying_answer_auto_declines_without_ml2(self):
        with patch('ml.services.predict_screening') as predict:
            application, created = self.submit(answers=self.answers(q2='Yes'))
        self.assertTrue(created)
        self.assertEqual(application.status, Application.Status.AUTO_DECLINED)
        predict.assert_not_called()
        self.assertEqual(application.status_events.count(), 2)

    def test_02_medium_prediction_goes_under_review(self):
        with patch('ml.services.predict_screening', return_value={
            'probability': 0.55, 'version': 'ml2-v1.0'
        }):
            application, _ = self.submit()
        self.assertEqual(application.status, Application.Status.UNDER_REVIEW)
        self.assertEqual(application.ml2_band, Application.Band.MEDIUM)
        self.assertEqual(application.ml2_probability, 0.55)

    def test_03_duplicate_submit_returns_same_application(self):
        with patch('ml.services.predict_screening', return_value={
            'probability': 0.55, 'version': 'ml2-v1.0'
        }):
            first, created = self.submit()
            second, duplicate = self.submit()
        self.assertTrue(created)
        self.assertFalse(duplicate)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Application.objects.filter(
            participant=self.profile, study=self.blood
        ).count(), 1)

    def test_04_high_prediction_auto_shortlists(self):
        study = self.make_study('High Priority Study', 60, 21, 70)
        study.auto_shortlist_high = True
        study.save(update_fields=['auto_shortlist_high'])
        question = PreScreenQuestion.objects.create(
            study=study, text='Question', order=1, preferred_answer='Yes'
        )
        with patch('ml.services.predict_screening', return_value={
            'probability': 0.82, 'version': 'ml2-v1.0'
        }):
            application, _ = self.submit(study, {question.pk: 'Yes'})
        self.assertEqual(application.status, Application.Status.SHORTLISTED)
        self.assertEqual(application.ml2_band, Application.Band.HIGH)
        self.assertTrue(application.auto_shortlisted)
        self.assertEqual(
            application.status_events.latest('id').note, 'Shortlisted by System'
        )

    def test_05_full_study_waitlists_and_keeps_high_band(self):
        with patch('ml.services.predict_screening', return_value={
            'probability': 0.82, 'version': 'ml2-v1.0'
        }):
            application, _ = self.submit(self.flu, {
                self.flu.pre_screen_questions.first().pk: 'Yes'
            })
        self.assertEqual(application.status, Application.Status.WAITLISTED)
        self.assertEqual(application.ml2_band, Application.Band.HIGH)

    def test_06_missing_prediction_is_unscored_under_review(self):
        study = self.make_study('Unscored Study', 60, 21, 70)
        question = PreScreenQuestion.objects.create(
            study=study, text='Question', order=1, preferred_answer='Yes'
        )
        with patch('ml.services.predict_screening', return_value=None):
            application, _ = self.submit(study, {question.pk: 'Yes'})
        self.assertEqual(application.ml2_band, Application.Band.UNSCORED)
        self.assertEqual(application.status, Application.Status.UNDER_REVIEW)

    def test_07_ineligible_submission_creates_nothing(self):
        with self.assertRaises(NotEligible):
            self.submit(self.heart, {
                self.heart.pre_screen_questions.first().pk: 'Yes'
            })
        self.assertFalse(Application.objects.filter(
            participant=self.profile, study=self.heart
        ).exists())

    def test_08_false_consent_rolls_back_everything(self):
        with self.assertRaises(ValidationError):
            self.submit(consent=False)
        self.assertFalse(Application.objects.filter(
            participant=self.profile, study=self.blood
        ).exists())
        self.assertEqual(ApplicationAnswer.objects.count(), 0)
        self.assertEqual(ApplicationStatusEvent.objects.count(), 0)

    def test_09_missing_answer_rolls_back_everything(self):
        with self.assertRaises(ValidationError):
            self.submit(answers={self.q1.pk: 'Yes'})
        self.assertFalse(Application.objects.filter(
            participant=self.profile, study=self.blood
        ).exists())

    def test_10_band_boundaries(self):
        for probability, band in (
            (0.70, Application.Band.HIGH),
            (0.6999, Application.Band.MEDIUM),
            (0.40, Application.Band.MEDIUM),
            (0.3999, Application.Band.LOW),
        ):
            study = self.make_study(f'Boundary {probability}', 60, 21, 70)
            question = PreScreenQuestion.objects.create(
                study=study, text='Question', order=1, preferred_answer='Yes'
            )
            with patch('ml.services.predict_screening', return_value={
                'probability': probability, 'version': 'ml2-v1.0'
            }):
                application, _ = self.submit(study, {question.pk: 'Yes'})
            self.assertEqual(application.ml2_band, band)

    def test_11_first_application_category_is_set(self):
        with patch('ml.services.predict_screening', return_value={
            'probability': 0.55, 'version': 'ml2-v1.0'
        }):
            self.submit()
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.first_application_category, self.category)
