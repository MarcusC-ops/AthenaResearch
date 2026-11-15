from datetime import datetime, timedelta

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Application, Appointment, Payout, Study


class FinalRegressionTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        call_command('seed_demo', verbosity=0)

    def setUp(self):
        self.aisyah = User.objects.get(username='aisyah@example.com')
        self.coordinator = User.objects.get(
            username='drlim@kentridge-crc.sg'
        )
        self.staff = User.objects.get(username='priya@athena.sg')
        self.admin = User.objects.get(username='admin@athena.sg')
        self.study = Study.objects.get(
            slug='healthy-volunteer-blood-sample-bank-for-lab-test-development'
        )
        self.study.refresh_from_db()

    def test_01_aisyah_completes_the_web_application_journey(self):
        self.client.force_login(self.aisyah)
        study_url = reverse(
            'storefront:study_detail',
            kwargs={'slug': self.study.slug},
        )
        self.assertEqual(self.client.get(study_url).status_code, 200)
        self.assertEqual(
            self.client.get(
                reverse(
                    'storefront:apply_step1',
                    kwargs={'slug': self.study.slug},
                )
            ).status_code,
            200,
        )
        questions = list(self.study.pre_screen_questions.order_by('order'))
        answers = {
            f'question_{question.pk}': question.preferred_answer
            or question.option_list()[0]
            for question in questions
        }
        answers.update({
            'preferred_site': str(self.study.sites.first().pk),
            'availability': 'flexible',
        })
        self.assertEqual(
            self.client.post(
                reverse(
                    'storefront:apply_step2',
                    kwargs={'slug': self.study.slug},
                ),
                answers,
            ).status_code,
            302,
        )
        response = self.client.post(
            reverse(
                'storefront:apply_step3',
                kwargs={'slug': self.study.slug},
            ),
            {'consent': 'on'},
        )
        self.assertEqual(response.status_code, 302)
        application = Application.objects.get(
            participant=self.aisyah.participant_profile,
            study=self.study,
        )
        self.assertEqual(application.status, Application.Status.UNDER_REVIEW)

        self.client.force_login(self.coordinator)
        detail_url = reverse(
            'adminpanel:application_detail',
            kwargs={'application_id': application.pk},
        )
        self.assertEqual(self.client.get(detail_url).status_code, 200)
        self.client.post(detail_url, {'action': 'shortlist'})
        when = timezone.localtime(timezone.now() + timedelta(days=2))
        screening_response = self.client.post(
            detail_url,
            {
                'action': 'schedule_screening',
                'when': when.strftime('%Y-%m-%dT%H:%M'),
                'site': str(self.study.sites.first().pk),
            },
        )
        self.assertEqual(screening_response.status_code, 302)
        application.refresh_from_db()
        self.assertEqual(
            application.status,
            Application.Status.SCREENING_SCHEDULED,
        )
        screening = application.appointments.get(
            kind=Appointment.Kind.SCREENING,
        )

        self.client.force_login(self.aisyah)
        self.assertEqual(
            self.client.post(
                reverse(
                    'storefront:confirm_appointment',
                    kwargs={
                        'application_id': application.pk,
                        'appointment_id': screening.pk,
                    },
                )
            ).status_code,
            302,
        )
        self.client.force_login(self.coordinator)
        self.client.post(detail_url, {'action': 'screening_passed'})
        self.client.post(detail_url, {'action': 'enrol'})
        application.refresh_from_db()
        self.assertEqual(application.status, Application.Status.ENROLLED)

        participation_url = reverse(
            'adminpanel:participation_detail',
            kwargs={'application_id': application.pk},
        )
        for visit in application.appointments.filter(
            kind=Appointment.Kind.VISIT,
        ):
            self.client.post(
                participation_url,
                {
                    'action': 'save_date',
                    'appointment_id': str(visit.pk),
                    'scheduled_for': datetime.now().strftime(
                        '%Y-%m-%dT%H:%M'
                    ),
                },
            )
            self.client.post(
                participation_url,
                {
                    'action': 'mark_attended',
                    'appointment_id': str(visit.pk),
                },
            )
        self.client.post(
            participation_url,
            {'action': 'request_payout'},
        )
        payout = application.payouts.get(status=Payout.Status.REQUESTED)

        self.client.force_login(self.staff)
        self.client.post(
            reverse('adminpanel:payouts'),
            {'ids': [str(payout.pk)]},
        )
        self.client.post(
            reverse('adminpanel:payout_pay'),
            {'ids': [str(payout.pk)]},
        )
        self.client.force_login(self.coordinator)
        self.client.post(participation_url, {'action': 'complete'})
        application.refresh_from_db()
        self.assertEqual(application.status, Application.Status.COMPLETED)

        self.client.force_login(self.aisyah)
        review_url = reverse(
            'storefront:review_application',
            kwargs={'application_id': application.pk},
        )
        self.assertEqual(
            self.client.post(
                review_url,
                {'rating': '5', 'comment': 'A clear study experience.'},
            ).status_code,
            302,
        )

    def test_02_seeded_personas_have_role_landing_pages(self):
        checks = [
            ('aisyah@example.com', reverse('storefront:for_you')),
            ('mrtan@example.com', reverse('storefront:applications')),
            ('drlim@kentridge-crc.sg', reverse('adminpanel:dashboard')),
            ('priya@athena.sg', reverse('adminpanel:dashboard')),
            ('admin@athena.sg', reverse('adminpanel:ml_monitor')),
        ]
        for username, url in checks:
            with self.subTest(username=username):
                self.client.force_login(User.objects.get(username=username))
                self.assertEqual(self.client.get(url).status_code, 200)


class AccessControlMatrixTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        call_command('seed_demo', verbosity=0)

    def setUp(self):
        self.users = {
            'participant': User.objects.get(username='aisyah@example.com'),
            'coordinator': User.objects.get(
                username='drlim@kentridge-crc.sg'
            ),
            'staff': User.objects.get(username='priya@athena.sg'),
            'admin': User.objects.get(username='admin@athena.sg'),
        }
        self.application = Application.objects.get(
            participant__user__username='aisyah@example.com',
            study__slug='exercise-and-the-immune-response-to-a-seasonal-flu-vaccine',
        )
        self.study = self.application.study

    def test_03_every_role_has_expected_url_access(self):
        public = [
            '/',
            '/studies/',
            '/support/',
            '/accounts/register/',
            '/accounts/login/',
            '/panel/login/',
        ]
        participant = [
            '/account/',
            '/onboarding/',
            '/for-you/',
            '/shortlist/',
            '/shortlist/compare/',
            '/applications/',
            f'/applications/{self.application.pk}/',
            f'/applications/{self.application.pk}/submitted/',
            f'/applications/{self.application.pk}/withdraw/',
            f'/applications/{self.application.pk}/review/',
            f'/applications/{self.application.pk}/contact/',
        ]
        panel = [
            '/panel/',
            '/panel/notifications/',
            '/panel/studies/',
            f'/panel/studies/{self.study.pk}/',
            f'/panel/studies/{self.study.pk}/preview/',
            f'/panel/studies/{self.study.pk}/applicants/',
            f'/panel/applications/{self.application.pk}/',
            '/panel/participation/',
            f'/panel/participation/{self.application.pk}/',
            '/panel/insights/',
        ]
        staff_only = [
            '/panel/moderation/',
            '/panel/organisations/',
            '/panel/participants/',
            '/panel/taxonomy/',
            '/panel/payouts/',
            '/panel/reviews/',
            '/panel/support/',
            '/panel/ml/',
        ]
        admin_only = ['/panel/ml/settings/', '/panel/staff/', '/panel/demo-data/']

        for path in public:
            with self.subTest(role='anonymous', path=path):
                self.client.logout()
                self.assertEqual(self.client.get(path).status_code, 200)
        for path in participant:
            with self.subTest(role='participant', path=path):
                self.client.force_login(self.users['participant'])
                self.assertNotEqual(self.client.get(path).status_code, 403)
            for role in ('coordinator', 'staff', 'admin'):
                with self.subTest(role=role, path=path):
                    self.client.force_login(self.users[role])
                    self.assertEqual(self.client.get(path).status_code, 403)
        for path in panel:
            for role in ('coordinator', 'staff', 'admin'):
                with self.subTest(role=role, path=path):
                    self.client.force_login(self.users[role])
                    self.assertNotEqual(self.client.get(path).status_code, 403)
            with self.subTest(role='participant', path=path):
                self.client.force_login(self.users['participant'])
                self.assertEqual(self.client.get(path).status_code, 403)
        for path in staff_only:
            for role in ('staff', 'admin'):
                with self.subTest(role=role, path=path):
                    self.client.force_login(self.users[role])
                    self.assertNotEqual(self.client.get(path).status_code, 403)
            for role in ('participant', 'coordinator'):
                with self.subTest(role=role, path=path):
                    self.client.force_login(self.users[role])
                    self.assertEqual(self.client.get(path).status_code, 403)
        for path in admin_only:
            self.client.force_login(self.users['admin'])
            with self.subTest(role='admin', path=path):
                self.assertNotEqual(self.client.get(path).status_code, 403)
            for role in ('participant', 'coordinator', 'staff'):
                with self.subTest(role=role, path=path):
                    self.client.force_login(self.users[role])
                    self.assertEqual(self.client.get(path).status_code, 403)
