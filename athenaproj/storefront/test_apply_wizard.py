from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import (
    Application,
    Organisation,
    ParticipantProfile,
    PreScreenQuestion,
    Region,
    Site,
    Study,
    StudyCategory,
)


class ApplyWizardTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.password = 'Kopi-Teh-2026!'
        cls.region = Region.objects.create(code='W', name='West', display_order=5)
        cls.healthy_category = StudyCategory.objects.create(
            name='Healthy Volunteer Phase I',
            slug='healthy-volunteer-phase-1',
            ml_label='healthy_phase1',
            description='Healthy volunteer studies.',
            display_order=1,
        )
        cls.heart_category = StudyCategory.objects.create(
            name='Heart and Blood Pressure',
            slug='heart-and-blood-pressure',
            ml_label='heart',
            description='Heart and blood pressure research.',
            display_order=2,
        )

        cls.organisation = Organisation.objects.create(
            name='Harbourfront General Hospital',
            org_type=Organisation.OrganisationType.HOSPITAL,
            contact_person='Nur Hidayah Salleh',
            contact_email='nur@harbourfront.sg',
        )
        cls.site = Site.objects.create(
            organisation=cls.organisation,
            name='S1',
            address='1 West Road',
            postal_code='123456',
            region=cls.region,
        )

        participant_group, _ = Group.objects.get_or_create(name='Participant')
        participant_user = User.objects.create_user(
            username='aisyah@example.com',
            email='aisyah@example.com',
            first_name='Aisyah',
            last_name='Rahman',
            password=cls.password,
        )
        participant_user.groups.add(participant_group)
        cls.aisyah = ParticipantProfile.objects.create(
            user=participant_user,
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

        cls.blood_study = cls.make_study(
            'Blood Sample Bank',
            category=cls.healthy_category,
            min_age=21,
            max_age=70,
            accepts_healthy_volunteers=True,
            target_enrolment=60,
            status=Study.Status.PUBLISHED,
        )
        cls.q1 = PreScreenQuestion.objects.create(
            study=cls.blood_study,
            text='Are you comfortable with a blood sample?',
            order=1,
            options='Yes\nNo',
            preferred_answer='Yes',
            disqualifying_answer='No',
        )
        cls.q2 = PreScreenQuestion.objects.create(
            study=cls.blood_study,
            text='Do you have a fear of needles?',
            order=2,
            options='Yes\nNo',
            preferred_answer='No',
            disqualifying_answer='Yes',
        )

        cls.heart_study = cls.make_study(
            'Midlife Heart Study',
            category=cls.heart_category,
            min_age=40,
            max_age=65,
            accepts_healthy_volunteers=True,
            target_enrolment=60,
            status=Study.Status.PUBLISHED,
        )
        PreScreenQuestion.objects.create(
            study=cls.heart_study,
            text='Have you ever had a heart check-up?',
            order=1,
            options='Yes\nNo',
            preferred_answer='Yes',
        )

        cls.sleep_study = cls.make_study(
            'Sleep Habits Study',
            category=cls.healthy_category,
            min_age=21,
            max_age=70,
            accepts_healthy_volunteers=True,
            target_enrolment=40,
            status=Study.Status.PUBLISHED,
        )
        PreScreenQuestion.objects.create(
            study=cls.sleep_study,
            text='Do you usually sleep at least 6 hours a night?',
            order=1,
            options='Yes\nNo',
            preferred_answer='Yes',
        )

        cls.calm_study = cls.make_study(
            'Calm Minds Trial',
            category=cls.heart_category,
            min_age=21,
            max_age=70,
            accepts_healthy_volunteers=True,
            target_enrolment=40,
            status=Study.Status.PUBLISHED,
        )
        PreScreenQuestion.objects.create(
            study=cls.calm_study,
            text='Would you like support with stress and focus?',
            order=1,
            options='Yes\nNo',
            preferred_answer='Yes',
        )

        cls.full_study = cls.make_study(
            'Full Study',
            category=cls.healthy_category,
            min_age=21,
            max_age=70,
            accepts_healthy_volunteers=True,
            target_enrolment=1,
            status=Study.Status.FULL,
        )
        PreScreenQuestion.objects.create(
            study=cls.full_study,
            text='Are you available for a short study visit?',
            order=1,
            options='Yes\nNo',
            preferred_answer='Yes',
        )

        other_user = User.objects.create_user(
            username='other@example.com',
            email='other@example.com',
            first_name='Other',
            last_name='Person',
            password='Password123!',
        )
        other_user.groups.add(participant_group)
        cls.other_participant = ParticipantProfile.objects.create(
            user=other_user,
            mobile='+6587654321',
            terms_accepted_at=timezone.now(),
            onboarding_completed_at=timezone.now(),
            date_of_birth=date.today().replace(year=date.today().year - 42),
            sex=ParticipantProfile.Sex.MALE,
            region=cls.region,
            employment=ParticipantProfile.Employment.FULL_TIME,
            education=ParticipantProfile.Education.DEGREE,
            height_cm='175.0',
            weight_kg='80.0',
            smoker=False,
            activity_level=ParticipantProfile.ActivityLevel.MODERATE,
            availability=ParticipantProfile.Availability.WEEKDAY_DAYTIME,
            max_travel_minutes=ParticipantProfile.TravelMinutes.THIRTY,
            consent_matching=True,
            consent_insights=False,
            consent_contact=True,
        )
        Application.objects.create(
            participant=cls.other_participant,
            study=cls.full_study,
            status=Application.Status.ENROLLED,
            preferred_site=cls.site,
            availability=Application.Availability.WEEKDAY_DAYTIME,
            consent_given_at=timezone.now(),
            submitted_at=timezone.now(),
        )

    @classmethod
    def make_study(cls, title, category, min_age, max_age, accepts_healthy_volunteers, target_enrolment, status):
        study = Study.objects.create(
            organisation=cls.organisation,
            category=category,
            title=title,
            description=f'{title} description.',
            study_type=Study.StudyType.OBSERVATIONAL,
            phase=Study.Phase.NOT_APPLICABLE,
            accepts_healthy_volunteers=accepts_healthy_volunteers,
            sex_eligibility=Study.SexEligibility.ALL,
            min_age=min_age,
            max_age=max_age,
            smoker_rule=Study.SmokerRule.ANY,
            target_enrolment=target_enrolment,
            total_visits=1,
            duration_weeks=4,
            visit_times=Study.VisitTimes.FLEXIBLE,
            compensation_amount='0.00',
            show_compensation=False,
            start_date=date.today(),
            recruitment_deadline=date.today() + timedelta(days=30),
            status=status,
        )
        study.sites.add(cls.site)
        return study

    def setUp(self):
        self.client.force_login(self.aisyah.user)

    def _complete_step_1(self, study):
        return self.client.get(reverse('storefront:apply_step1', kwargs={'slug': study.slug}))

    def _complete_step_2(self, study, answers=None):
        answers = answers or {
            f'question_{self.q1.pk}': 'Yes',
            f'question_{self.q2.pk}': 'No',
        }
        return self.client.post(
            reverse('storefront:apply_step2', kwargs={'slug': study.slug}),
            {
                **answers,
                'preferred_site': self.site.pk,
                'availability': 'weekday_evenings',
            },
        )

    def test_01_get_step_1_of_midlife_heart_study_not_eligible(self):
        response = self._complete_step_1(self.heart_study)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Not eligible this time')
        self.assertContains(response, 'Ages 40 to 65 (you are 30)')
        self.assertContains(response, 'Studies you qualify for')
        self.assertNotContains(response, 'Continue')
        self.assertFalse(
            Application.objects.filter(participant=self.aisyah, study=self.heart_study).exists()
        )

    def test_02_get_step_2_without_step_1_redirects_to_step_1(self):
        response = self.client.get(reverse('storefront:apply_step2', kwargs={'slug': self.blood_study.slug}))

        self.assertRedirects(
            response,
            reverse('storefront:apply_step1', kwargs={'slug': self.blood_study.slug}),
        )

    def test_03_step_1_then_step_2_redirects_to_step_3_and_shows_model_message(self):
        self._complete_step_1(self.blood_study)
        response = self._complete_step_2(self.blood_study)

        self.assertRedirects(
            response,
            reverse('storefront:apply_step3', kwargs={'slug': self.blood_study.slug}),
        )

        response = self.client.get(reverse('storefront:apply_step3', kwargs={'slug': self.blood_study.slug}))
        self.assertContains(response, 'A model never declines an application.')
        self.assertContains(response, 'Are you comfortable with a blood sample?')
        self.assertContains(response, 'Yes')
        self.assertContains(response, 'No')

    def test_04_step_3_without_consent_shows_error_and_creates_no_application(self):
        self._complete_step_1(self.blood_study)
        self._complete_step_2(self.blood_study)

        response = self.client.post(
            reverse('storefront:apply_step3', kwargs={'slug': self.blood_study.slug}),
            {},
        )

        self.assertContains(response, 'Tick the consent box to send your application.')
        self.assertEqual(
            Application.objects.filter(participant=self.aisyah, study=self.blood_study).count(),
            0,
        )

    def test_05_submit_with_consent_redirects_to_submitted_page_and_clears_session(self):
        with patch('ml.services.predict_screening', return_value={'probability': 0.55, 'version': 'ml2-v1.0'}):
            self._complete_step_1(self.blood_study)
            self._complete_step_2(self.blood_study)
            response = self.client.post(
                reverse('storefront:apply_step3', kwargs={'slug': self.blood_study.slug}),
                {'consent': 'on'},
            )

        self.assertEqual(response.status_code, 302)
        application = Application.objects.get(participant=self.aisyah, study=self.blood_study)
        self.assertTrue(response.url.endswith(f'/applications/{application.pk}/submitted/'))
        self.assertContains(
            self.client.get(response.url),
            'Application sent',
        )
        self.assertContains(
            self.client.get(response.url),
            'A-',
        )
        self.assertNotIn(f'apply_{self.blood_study.pk}', self.client.session)

    def test_06_posting_step_3_twice_uses_same_application(self):
        with patch('ml.services.predict_screening', return_value={'probability': 0.55, 'version': 'ml2-v1.0'}):
            self._complete_step_1(self.blood_study)
            self._complete_step_2(self.blood_study)
            response = self.client.post(
                reverse('storefront:apply_step3', kwargs={'slug': self.blood_study.slug}),
                {'consent': 'on'},
            )

        application = Application.objects.get(participant=self.aisyah, study=self.blood_study)
        self.assertTrue(response.url.endswith(f'/applications/{application.pk}/submitted/'))

        self.client.force_login(self.aisyah.user)
        second_response = self.client.post(
            reverse('storefront:apply_step3', kwargs={'slug': self.blood_study.slug}),
            {'consent': 'on'},
        )

        self.assertEqual(
            Application.objects.filter(participant=self.aisyah, study=self.blood_study).count(),
            1,
        )
        self.assertTrue(second_response.url.endswith(f'/applications/{application.pk}/'))

    def test_07_submitted_page_does_not_show_probability_text(self):
        with patch('ml.services.predict_screening', return_value={'probability': 0.55, 'version': 'ml2-v1.0'}):
            self._complete_step_1(self.blood_study)
            self._complete_step_2(self.blood_study)
            response = self.client.post(
                reverse('storefront:apply_step3', kwargs={'slug': self.blood_study.slug}),
                {'consent': 'on'},
            )

        submitted = self.client.get(response.url)
        self.assertNotContains(submitted, '0.55')
        self.assertNotContains(submitted, '55%')
        self.assertNotContains(submitted, 'probability')
        self.assertNotContains(submitted, 'Medium')

    def test_08_new_participant_auto_declined_page_shows_qualifying_studies(self):
        new_user = User.objects.create_user(
            username='newparticipant@example.com',
            email='newparticipant@example.com',
            first_name='Leah',
            last_name='Ng',
            password='Password123!',
        )
        new_user.groups.add(Group.objects.get_or_create(name='Participant')[0])
        new_profile = ParticipantProfile.objects.create(
            user=new_user,
            mobile='+6598765432',
            terms_accepted_at=timezone.now(),
            onboarding_completed_at=timezone.now(),
            date_of_birth=date.today().replace(year=date.today().year - 29),
            sex=ParticipantProfile.Sex.FEMALE,
            region=self.region,
            employment=ParticipantProfile.Employment.FULL_TIME,
            education=ParticipantProfile.Education.DEGREE,
            height_cm='165.0',
            weight_kg='60.0',
            smoker=False,
            activity_level=ParticipantProfile.ActivityLevel.MODERATE,
            availability=ParticipantProfile.Availability.WEEKDAY_EVENINGS,
            max_travel_minutes=ParticipantProfile.TravelMinutes.THIRTY,
            consent_matching=True,
            consent_insights=True,
            consent_contact=True,
        )
        self.client.force_login(new_user)

        self.client.get(reverse('storefront:apply_step1', kwargs={'slug': self.blood_study.slug}))
        self.client.post(
            reverse('storefront:apply_step2', kwargs={'slug': self.blood_study.slug}),
            {
                f'question_{self.q1.pk}': 'Yes',
                f'question_{self.q2.pk}': 'Yes',
                'preferred_site': self.site.pk,
                'availability': 'weekday_evenings',
            },
        )
        response = self.client.post(
            reverse('storefront:apply_step3', kwargs={'slug': self.blood_study.slug}),
            {'consent': 'on'},
        )

        self.assertEqual(response.status_code, 302)
        submitted = self.client.get(response.url)
        self.assertContains(submitted, 'Not eligible this time')
        self.assertContains(submitted, 'Here are studies you qualify for')

    def test_09_full_study_page_and_waitlist_flow(self):
        response = self.client.get(reverse('storefront:study_detail', kwargs={'slug': self.full_study.slug}))
        self.assertContains(response, 'Join the waitlist')

        self._complete_step_1(self.full_study)
        self.client.post(
            reverse('storefront:apply_step2', kwargs={'slug': self.full_study.slug}),
            {
                f'question_{self.full_study.pre_screen_questions.first().pk}': 'Yes',
                'preferred_site': self.site.pk,
                'availability': 'weekday_evenings',
            },
        )

        with patch('ml.services.predict_screening', return_value={'probability': 0.55, 'version': 'ml2-v1.0'}):
            response = self.client.post(
                reverse('storefront:apply_step3', kwargs={'slug': self.full_study.slug}),
                {'consent': 'on'},
            )

        self.assertEqual(response.status_code, 302)
        submitted = self.client.get(response.url)
        self.assertContains(submitted, 'You are on the waitlist')

    def test_10_study_page_after_submit_shows_view_application(self):
        with patch('ml.services.predict_screening', return_value={'probability': 0.55, 'version': 'ml2-v1.0'}):
            self._complete_step_1(self.blood_study)
            self._complete_step_2(self.blood_study)
            response = self.client.post(
                reverse('storefront:apply_step3', kwargs={'slug': self.blood_study.slug}),
                {'consent': 'on'},
            )

        application = Application.objects.get(participant=self.aisyah, study=self.blood_study)
        self.assertTrue(response.url.endswith(f'/applications/{application.pk}/submitted/'))

        study_response = self.client.get(reverse('storefront:study_detail', kwargs={'slug': self.blood_study.slug}))
        self.assertContains(study_response, 'View my application')

    def test_11_other_participant_cannot_view_aisyah_submitted_page(self):
        with patch('ml.services.predict_screening', return_value={'probability': 0.55, 'version': 'ml2-v1.0'}):
            self._complete_step_1(self.blood_study)
            self._complete_step_2(self.blood_study)
            response = self.client.post(
                reverse('storefront:apply_step3', kwargs={'slug': self.blood_study.slug}),
                {'consent': 'on'},
            )

        application = Application.objects.get(participant=self.aisyah, study=self.blood_study)
        self.client.force_login(self.other_participant.user)
        page_response = self.client.get(
            reverse('storefront:application_submitted', kwargs={'application_id': application.pk})
        )

        self.assertEqual(page_response.status_code, 404)
