"""Regression tests for bugs found in the full-application evaluation."""
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from adminpanel.forms import StudyForm
from core.models import (
    Application, Appointment, Organisation, Payout, Review, Study,
)
from core.services import (
    applicant_mix, approve_study, band_distribution, coordinator_dashboard,
    pay_payouts, study_funnel,
)


class EvaluationFixTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        call_command('seed_demo', verbosity=0)

    def setUp(self):
        self.aisyah = User.objects.get(username='aisyah@example.com')
        self.coordinator = User.objects.get(username='drlim@kentridge-crc.sg')
        self.staff = User.objects.get(username='priya@athena.sg')
        self.org = self.coordinator.staff_profile.organisation
        self.flu = Study.objects.get(title__startswith='Exercise and the Immune')
        self.memory = Study.objects.get(title__startswith='Memory Games')

    # Security -------------------------------------------------------------

    def test_participant_login_ignores_offsite_next(self):
        for next_url in ('https://evil.example/', '//evil.example/'):
            response = self.client.post(
                f'/accounts/login/?next={next_url}',
                {'email': 'aisyah@example.com', 'password': 'AthenaDemo2026!'},
            )
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response['Location'], '/account/')
            self.client.logout()

    def test_panel_login_ignores_offsite_next(self):
        response = self.client.post('/panel/login/', {
            'email': 'drlim@kentridge-crc.sg',
            'password': 'AthenaDemo2026!',
            'next': 'https://evil.example/',
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], '/panel/')

    def test_login_keeps_local_next(self):
        response = self.client.post(
            '/accounts/login/?next=/for-you/',
            {'email': 'aisyah@example.com', 'password': 'AthenaDemo2026!'},
        )
        self.assertEqual(response['Location'], '/for-you/')

    # Crashes --------------------------------------------------------------

    def test_review_reject_page_renders(self):
        review = Review.objects.filter(status=Review.Status.PENDING).first()
        self.client.force_login(self.staff)
        response = self.client.get(reverse('adminpanel:review_reject', args=[review.pk]))
        self.assertEqual(response.status_code, 200)

    def test_apply_steps_404_for_unknown_or_hidden_study(self):
        self.client.force_login(self.aisyah)
        draft = Study.objects.filter(status=Study.Status.DRAFT).first()
        for slug in ('no-such-study', draft.slug):
            for step in ('apply_step1', 'apply_step2', 'apply_step3'):
                url = reverse(f'storefront:{step}', kwargs={'slug': slug})
                self.assertEqual(self.client.get(url).status_code, 404, url)

    def test_tampered_ids_do_not_crash_panel(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get('/panel/payouts/pay/?ids=abc').status_code, 200)
        response = self.client.post('/panel/reviews/', {'review_id': 'abc'})
        self.assertEqual(response.status_code, 404)
        self.client.force_login(self.coordinator)
        self.assertEqual(self.client.get('/panel/insights/?study_id=abc').status_code, 200)

    def test_complete_on_non_enrolled_application_reports_error(self):
        application = Application.objects.filter(
            study__organisation=self.org,
            status=Application.Status.SCREENING_SCHEDULED,
        ).first()
        self.client.force_login(self.coordinator)
        url = reverse('adminpanel:participation_detail', args=[application.pk])
        response = self.client.post(url, {'action': 'complete'}, follow=True)
        self.assertEqual(response.status_code, 200)
        application.refresh_from_db()
        self.assertEqual(application.status, Application.Status.SCREENING_SCHEDULED)

    # Behaviour ------------------------------------------------------------

    def test_attended_and_missed_offered_for_past_visits(self):
        application = Application.objects.get(
            participant__user=self.aisyah, study=self.flu,
        )
        visit = application.appointments.filter(
            kind=Appointment.Kind.VISIT, status=Appointment.Status.CONFIRMED,
        ).first()
        visit.scheduled_for = timezone.now() - timedelta(hours=2)
        visit.save()
        self.client.force_login(self.coordinator)
        response = self.client.get(
            reverse('adminpanel:participation_detail', args=[application.pk])
        )
        self.assertContains(response, 'value="mark_attended"')
        self.assertContains(response, 'value="mark_missed"')
        local = timezone.localtime(visit.scheduled_for)
        self.assertContains(response, f'value="{local:%Y-%m-%dT%H:%M}"')

    def test_enrolled_application_links_to_visits_and_payouts(self):
        application = Application.objects.filter(
            study__organisation=self.org, status=Application.Status.ENROLLED,
        ).first()
        self.client.force_login(self.coordinator)
        response = self.client.get(
            reverse('adminpanel:application_detail', args=[application.pk])
        )
        self.assertContains(
            response,
            reverse('adminpanel:participation_detail', args=[application.pk]),
        )

    def test_staff_study_edit_saves_changed_fields(self):
        form = StudyForm(
            instance=self.memory, organisation=self.memory.organisation, staff_mode=True,
        )
        data = {}
        for name, field in form.fields.items():
            value = form[name].value()
            if value is None or value is False:
                continue
            if isinstance(value, (list, tuple)):
                data[name] = [getattr(item, 'pk', item) for item in value]
            else:
                data[name] = value
        data['title'] = 'Memory Games, edited by staff'
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse('adminpanel:study_edit', args=[self.memory.pk]), data,
        )
        self.assertEqual(response.status_code, 302, getattr(response, 'context', None)
                         and response.context['form'].errors)
        self.memory.refresh_from_db()
        self.assertEqual(self.memory.title, 'Memory Games, edited by staff')

    def test_dashboard_lists_high_priority_first(self):
        rows = list(coordinator_dashboard(self.coordinator)['under_review_apps'])
        ranks = {'high': 0, 'medium': 1, 'low': 2, 'unscored': 3}
        bands = [ranks[application.ml2_band] for application in rows]
        self.assertEqual(bands, sorted(bands))
        self.assertEqual(rows[0].ml2_band, Application.Band.HIGH)

    def test_band_distribution_is_ordered_with_percentages(self):
        rows = band_distribution(Application.objects.filter(study=self.flu))
        order = [band for band, _ in Application.Band.choices]
        self.assertEqual(
            [row['ml2_band'] for row in rows],
            [band for band in order if band in {row['ml2_band'] for row in rows}],
        )
        self.assertTrue(all(0 <= row['percent'] <= 100 for row in rows))

    def test_applicant_mix_counts_people_once_and_includes_completed(self):
        applications = Application.objects.filter(study__organisation=self.org)
        mix = applicant_mix(applications)
        people = applications.filter(
            participant__consent_insights=True, participant__sex__isnull=False,
        ).values('participant').distinct().count()
        self.assertEqual(sum(mix['sex']['applied'].values()), people)
        memory_mix = applicant_mix(Application.objects.filter(study=self.memory))
        self.assertTrue(memory_mix['sex']['enrolled'])

    def test_seeded_funnel_never_widens(self):
        funnel = study_funnel(Application.objects.filter(study__organisation=self.org))
        self.assertGreaterEqual(funnel['screened'], funnel['passed_screening'])
        self.assertGreaterEqual(funnel['passed_screening'], funnel['enrolled'])

    def test_seeded_requested_payouts_can_be_paid(self):
        requested = list(
            Payout.objects.filter(status=Payout.Status.REQUESTED).values_list('pk', flat=True)
        )
        count, _ = pay_payouts(requested, self.staff)
        self.assertEqual(count, len(requested))

    def test_reseeding_after_payment_does_not_request_again(self):
        requested = list(
            Payout.objects.filter(status=Payout.Status.REQUESTED).values_list('pk', flat=True)
        )
        pay_payouts(requested, self.staff)
        call_command('seed_demo', verbosity=0)
        self.assertFalse(Payout.objects.filter(status=Payout.Status.REQUESTED).exists())

    def test_inactive_organisation_study_cannot_be_approved(self):
        Organisation.objects.filter(pk=self.memory.organisation_id).update(is_active=False)
        self.memory.refresh_from_db()
        self.memory.status = Study.Status.PAUSED
        with self.assertRaises(ValidationError):
            approve_study(self.memory, self.staff)

    # Display --------------------------------------------------------------

    def test_profile_page_has_no_raw_none(self):
        self.client.force_login(self.aisyah)
        response = self.client.get('/account/')
        # Ethnicity is blank for Aisyah; it used to render as a bare "None".
        self.assertContains(
            response, '<dt>Ethnicity</dt><dd>Not given</dd>', html=True,
        )

    def test_insights_filter_keeps_selected_study(self):
        self.client.force_login(self.coordinator)
        response = self.client.get(f'/panel/insights/?study_id={self.flu.pk}')
        self.assertContains(response, f'value="{self.flu.pk}" selected')

    def test_platform_insights_uses_readable_labels(self):
        self.client.force_login(self.staff)
        response = self.client.get('/panel/insights/')
        self.assertContains(response, 'Passed pre-screen')
        self.assertNotContains(response, 'Passed_Pre_Screen')
        self.assertNotContains(response, 'Age_Bands')

    def test_ml_monitor_shows_probability_as_percentage(self):
        self.client.force_login(self.staff)
        response = self.client.get('/panel/ml/')
        self.assertContains(response, 'ML-2 never declines anyone')
        self.assertNotRegex(response.content.decode(), r'High \([01]%\)')
