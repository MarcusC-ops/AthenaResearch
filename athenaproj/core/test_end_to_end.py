from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import (
    Application,
    Appointment,
    Condition,
    Organisation,
    ParticipantProfile,
    Payout,
    PreScreenQuestion,
    Region,
    Site,
    Study,
    StudyCategory,
    StaffProfile,
)


class ParticipantLifecycleTests(TestCase):
    password = 'Kopi-Teh-2026!'

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Group.objects.get_or_create(name='Participant')
        Group.objects.get_or_create(name='Coordinator')
        Group.objects.get_or_create(name='Staff')
        Group.objects.get_or_create(name='Admin')
        cls.regions = {
            code: Region.objects.create(
                code=code,
                name=name,
                display_order=order,
            )
            for order, (code, name) in enumerate(
                [('C', 'Central'), ('N', 'North'), ('NE', 'North-East'),
                 ('E', 'East'), ('W', 'West')],
                1,
            )
        }
        cls.category = StudyCategory.objects.create(
            name='Healthy Volunteer Phase I',
            slug='healthy-volunteer-phase-1',
            ml_label='healthy_phase1',
            description='Healthy volunteer studies.',
            display_order=1,
        )
        cls.organisation = Organisation.objects.create(
            name='Kent Ridge Clinical Research Centre',
            org_type=Organisation.OrganisationType.UNIVERSITY,
            contact_person='Daniel Lim',
            contact_email='drlim@kentridge-crc.sg',
        )
        cls.site = Site.objects.create(
            organisation=cls.organisation,
            name='K1',
            address='21 Lower Kent Ridge Road',
            postal_code='119077',
            region=cls.regions['W'],
        )
        cls.coordinator = cls._create_panel_user(
            'drlim@kentridge-crc.sg',
            'Daniel',
            'Lim',
            'Coordinator',
            organisation=cls.organisation,
        )
        cls.staff = cls._create_panel_user(
            'priya@athena.sg',
            'Priya',
            'Nair',
            'Staff',
        )
        cls.admin = cls._create_panel_user(
            'admin@athena.sg',
            'Wei Ling',
            'Tan',
            'Admin',
        )
        cls.study = Study.objects.create(
            organisation=cls.organisation,
            category=cls.category,
            title='Flu Vaccine Exercise Study',
            description='A study about exercise and flu vaccines.',
            visit_plan='Visit 1: screening\nVisit 2: follow-up',
            study_type=Study.StudyType.INTERVENTIONAL,
            phase=Study.Phase.PHASE_1,
            accepts_healthy_volunteers=True,
            sex_eligibility=Study.SexEligibility.ALL,
            min_age=21,
            max_age=45,
            smoker_rule=Study.SmokerRule.ANY,
            target_enrolment=40,
            total_visits=2,
            duration_weeks=4,
            visit_times=Study.VisitTimes.FLEXIBLE,
            compensation_amount=Decimal('100.00'),
            show_compensation=True,
            start_date=timezone.localdate(),
            recruitment_deadline=timezone.localdate() + timedelta(days=30),
            status=Study.Status.PUBLISHED,
        )
        cls.study.sites.add(cls.site)
        PreScreenQuestion.objects.create(
            study=cls.study,
            text='Can you exercise three times a week?',
            order=1,
            options='Yes\nNo',
            preferred_answer='Yes',
        )

    @classmethod
    def _create_panel_user(cls, email, first_name, last_name, group_name, organisation=None):
        user = User.objects.create_user(
            username=email,
            email=email,
            first_name=first_name,
            last_name=last_name,
            password=cls.password,
        )
        user.groups.add(Group.objects.get(name=group_name))
        StaffProfile.objects.create(
            user=user,
            organisation=organisation,
            job_title='Research team member',
            mobile='+6591234567',
        )
        return user

    def _register_and_onboard(self):
        self.client.post(
            reverse('accounts:register'),
            {
                'first_name': 'Mei',
                'last_name': 'Tan',
                'email': 'mei@example.com',
                'mobile': '9876 5432',
                'password': self.password,
                'confirm_password': self.password,
                'terms_accepted': 'on',
            },
        )
        self.client.post(
            reverse('storefront:onboarding'),
            {
                'date_of_birth': (date.today() - timedelta(days=365 * 28)).isoformat(),
                'sex': ParticipantProfile.Sex.FEMALE,
                'region': self.regions['W'].pk,
                'ethnicity': 'prefer_not',
                'employment': ParticipantProfile.Employment.FULL_TIME,
                'education': ParticipantProfile.Education.DEGREE,
                'height_cm': '165.0',
                'weight_kg': '60.0',
                'activity_level': ParticipantProfile.ActivityLevel.MODERATE,
                'smoker': '',
                'motivation': ParticipantProfile.Motivation.HELP_RESEARCH,
                'availability': ParticipantProfile.Availability.FLEXIBLE,
                'max_travel_minutes': ParticipantProfile.TravelMinutes.THIRTY,
                'consent_matching': 'on',
                'consent_insights': 'on',
                'consent_contact': 'on',
            },
        )
        self.assertEqual(self.client.get(reverse('storefront:for_you')).status_code, 200)

    def _application_url(self):
        return reverse(
            'storefront:application_detail',
            kwargs={'application_id': Application.objects.get(
                participant__user__username='mei@example.com',
                study=self.study,
            ).pk},
        )

    def _apply(self):
        self.client.get(
            reverse(
                'storefront:shortlist_add',
                kwargs={'study_id': self.study.pk},
            )
        )
        self.client.post(
            reverse(
                'storefront:shortlist_add',
                kwargs={'study_id': self.study.pk},
            ),
        )
        self.client.get(
            reverse(
                'storefront:apply_step1',
                kwargs={'slug': self.study.slug},
            )
        )
        self.client.get(
            reverse(
                'storefront:apply_step2',
                kwargs={'slug': self.study.slug},
            )
        )
        question = self.study.pre_screen_questions.get()
        self.client.post(
            reverse(
                'storefront:apply_step2',
                kwargs={'slug': self.study.slug},
            ),
            {
                f'question_{question.pk}': 'Yes',
                'preferred_site': self.site.pk,
                'availability': Application.Availability.FLEXIBLE,
            },
        )
        with patch(
            'ml.services.predict_screening',
            return_value={'probability': 0.55, 'version': 'ml2-v1.0'},
        ):
            response = self.client.post(
                reverse(
                    'storefront:apply_step3',
                    kwargs={'slug': self.study.slug},
                ),
                {'consent': 'on'},
            )
        self.assertEqual(response.status_code, 302)
        return Application.objects.get(
            participant__user__username='mei@example.com',
            study=self.study,
        )

    def _panel_login(self, user):
        self.client.post(
            reverse('adminpanel:login'),
            {'email': user.email, 'password': self.password},
        )

    def _shortlist_and_schedule(self, application):
        self._panel_login(self.coordinator)
        detail_url = reverse(
            'adminpanel:application_detail',
            kwargs={'application_id': application.pk},
        )
        self.client.post(detail_url, {'action': 'shortlist'})
        when = timezone.localtime(timezone.now() + timedelta(days=2))
        self.client.post(
            detail_url,
            {
                'action': 'schedule_screening',
                'when': when.strftime('%Y-%m-%dT%H:%M'),
                'site': self.site.pk,
            },
        )
        return application

    def _enrol(self, application):
        self._panel_login(self.coordinator)
        detail_url = reverse(
            'adminpanel:application_detail',
            kwargs={'application_id': application.pk},
        )
        self.client.post(detail_url, {'action': 'screening_passed'})
        self.client.post(detail_url, {'action': 'enrol'})
        application.refresh_from_db()
        return application

    def _attend_visit(self, application, number):
        visit = application.appointments.get(
            kind=Appointment.Kind.VISIT,
            visit_number=number,
        )
        participation_url = reverse(
            'adminpanel:participation_detail',
            kwargs={'application_id': application.pk},
        )
        self._panel_login(self.coordinator)
        self.client.post(
            participation_url,
            {
                'action': 'save_date',
                'appointment_id': visit.pk,
                'scheduled_for': (
                    timezone.localtime(timezone.now() - timedelta(hours=1))
                    .strftime('%Y-%m-%dT%H:%M')
                ),
            },
        )
        self.client.post(
            participation_url,
            {'action': 'mark_attended', 'appointment_id': visit.pk},
        )
        return visit

    def _run_until(self, step):
        self._register_and_onboard()
        if step >= 2:
            application = self._apply()
        else:
            return None
        if step >= 4:
            self._shortlist_and_schedule(application)
        if step >= 5:
            self.client.force_login(
                User.objects.get(username='mei@example.com')
            )
            screening = application.appointments.get(
                kind=Appointment.Kind.SCREENING,
            )
            self.client.post(
                reverse(
                    'storefront:confirm_appointment',
                    kwargs={
                        'application_id': application.pk,
                        'appointment_id': screening.pk,
                    },
                )
            )
            application = self._enrol(application)
        if step >= 6:
            self._attend_visit(application, 1)
            self.client.post(
                reverse(
                    'adminpanel:participation_detail',
                    kwargs={'application_id': application.pk},
                ),
                {'action': 'request_payout'},
            )
        if step >= 7:
            payout = application.payouts.get(status=Payout.Status.REQUESTED)
            self._panel_login(self.staff)
            self.client.post(
                reverse('adminpanel:payouts'),
                {'ids': [payout.pk]},
            )
            self.client.post(
                reverse('adminpanel:payout_pay'),
                {'ids': [payout.pk]},
            )
        if step >= 8:
            self._attend_visit(application, 2)
            self.client.post(
                reverse(
                    'adminpanel:participation_detail',
                    kwargs={'application_id': application.pk},
                ),
                {'action': 'request_payout'},
            )
            payout = application.payouts.filter(
                status=Payout.Status.REQUESTED,
            ).latest('pk')
            self._panel_login(self.staff)
            self.client.post(
                reverse('adminpanel:payouts'),
                {'ids': [payout.pk]},
            )
            self.client.post(
                reverse('adminpanel:payout_pay'),
                {'ids': [payout.pk]},
            )
            self._panel_login(self.coordinator)
            self.client.post(
                reverse(
                    'adminpanel:participation_detail',
                    kwargs={'application_id': application.pk},
                ),
                {'action': 'complete'},
            )
        if step >= 9:
            self.client.force_login(
                User.objects.get(username='mei@example.com')
            )
            self.client.post(
                reverse(
                    'storefront:review_application',
                    kwargs={'application_id': application.pk},
                ),
                {'rating': '5', 'comment': 'Well run and friendly'},
            )
        return application

    def test_01_register_and_onboard_participant(self):
        self._run_until(1)
        self.assertEqual(self.client.get('/for-you/').status_code, 200)

    def test_02_shortlist_and_submit_application(self):
        application = self._run_until(2)
        self.assertEqual(application.status, Application.Status.UNDER_REVIEW)
        self.assertContains(self.client.get('/shortlist/'), 'Shortlist (1)')
        self.assertContains(
            self.client.get(
                reverse(
                    'storefront:application_submitted',
                    kwargs={'application_id': application.pk},
                )
            ),
            'Application sent',
        )

    def test_03_coordinator_reviews_and_shortlists(self):
        application = self._run_until(3)
        self._panel_login(self.coordinator)
        queue = self.client.get(
            reverse(
                'adminpanel:applicants',
                kwargs={'study_id': self.study.pk},
            )
        )
        self.assertContains(queue, application.reference)
        self.assertContains(queue, 'Medium')
        self.assertContains(queue, '55%')
        self.client.post(
            reverse(
                'adminpanel:application_detail',
                kwargs={'application_id': application.pk},
            ),
            {'action': 'shortlist'},
        )
        self.assertContains(
            self.client.get(
                reverse(
                    'adminpanel:application_detail',
                    kwargs={'application_id': application.pk},
                )
            ),
            'Mei Tan',
        )

    def test_04_schedule_and_confirm_screening(self):
        application = self._run_until(4)
        self.client.force_login(User.objects.get(username='mei@example.com'))
        page = self.client.get(self._application_url())
        self.assertContains(page, 'Screening booked')
        self.assertContains(page, 'Confirm appointment')
        screening = application.appointments.get(kind=Appointment.Kind.SCREENING)
        self.client.post(
            reverse(
                'storefront:confirm_appointment',
                kwargs={
                    'application_id': application.pk,
                    'appointment_id': screening.pk,
                },
            )
        )
        application.refresh_from_db()
        self.assertEqual(application.appointments.get(kind='screening').status, 'confirmed')

    def test_05_pass_screening_and_enrol(self):
        application = self._run_until(5)
        self.client.force_login(User.objects.get(username='mei@example.com'))
        page = self.client.get(self._application_url())
        self.assertContains(page, 'Enrolled')
        self.assertContains(page, '0 of 2 visits attended')

    def test_06_attend_first_visit_and_request_payout(self):
        application = self._run_until(6)
        self._panel_login(self.coordinator)
        page = self.client.get(
            reverse(
                'adminpanel:participation_detail',
                kwargs={'application_id': application.pk},
            )
        )
        self.assertContains(page, 'S$50.00')
        self.assertTrue(application.payouts.filter(status=Payout.Status.REQUESTED).exists())

    def test_07_staff_pays_first_payout(self):
        application = self._run_until(7)
        self.client.force_login(User.objects.get(username='mei@example.com'))
        page = self.client.get(self._application_url())
        self.assertContains(page, 'Paid')
        self.assertContains(page, 'PN-')

    def test_08_complete_visits_and_pay_second_payout(self):
        application = self._run_until(8)
        application.refresh_from_db()
        self.assertEqual(application.status, Application.Status.COMPLETED)
        self.assertEqual(application.payouts.filter(status=Payout.Status.PAID).count(), 2)

    def test_09_submit_and_approve_review(self):
        application = self._run_until(9)
        study_page = self.client.get(
            reverse(
                'storefront:study_detail',
                kwargs={'slug': self.study.slug},
            )
        )
        self.assertContains(study_page, 'No reviews yet')
        review = application.study.reviews.get()
        self._panel_login(self.staff)
        self.client.post(
            reverse('adminpanel:reviews'),
            {'review_id': review.pk},
        )
        study_page = self.client.get(
            reverse(
                'storefront:study_detail',
                kwargs={'slug': self.study.slug},
            )
        )
        self.assertContains(study_page, '5.0 / 5 (1 review)')

    def test_10_timeline_has_the_complete_participant_journey(self):
        application = self._run_until(9)
        self.client.force_login(User.objects.get(username='mei@example.com'))
        content = self.client.get(self._application_url()).content.decode()
        content = content[
            content.index('application-timeline'):
            content.index('</ol>', content.index('application-timeline'))
        ]
        labels = [
            'Received',
            'Being reviewed',
            'Shortlisted',
            'Screening booked',
            'Screening passed',
            'Enrolled',
            'Completed',
        ]
        positions = [content.index(label) for label in labels]
        self.assertEqual(positions, sorted(positions))
