from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, Permission, User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import (
    Application,
    Appointment,
    Organisation,
    ParticipantProfile,
    Payout,
    Region,
    Site,
    Study,
    StudyCategory,
    StaffProfile,
)
from core.services import amount_due, next_payout_reference, pay_payouts, reject_payout


class PayPayoutsTestCase(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.password = 'Kopi-Teh-2026!'
        cls.region = Region.objects.create(code='W', name='West', display_order=1)
        cls.category = StudyCategory.objects.create(
            name='Healthy Volunteer Phase I',
            slug='healthy-volunteer-phase-1',
            ml_label='healthy_phase1',
            description='Healthy volunteer studies.',
            display_order=1,
        )
        cls.organisation = Organisation.objects.create(
            name='Kent Ridge',
            org_type=Organisation.OrganisationType.UNIVERSITY,
            contact_person='Daniel Lim',
            contact_email='drlim@kentridge-crc.sg',
        )
        cls.site = Site.objects.create(
            name='K1', organisation=cls.organisation, region=cls.region,
            address='1 Kent Ridge Road', postal_code='119077',
        )
        cls.study = Study.objects.create(
            organisation=cls.organisation, category=cls.category,
            title='Payout Study', description='A payout study.',
            study_type=Study.StudyType.OBSERVATIONAL,
            phase=Study.Phase.NOT_APPLICABLE,
            accepts_healthy_volunteers=True,
            sex_eligibility=Study.SexEligibility.ALL,
            min_age=21, max_age=65, smoker_rule=Study.SmokerRule.ANY,
            target_enrolment=20, total_visits=5, duration_weeks=5,
            visit_times=Study.VisitTimes.FLEXIBLE,
            compensation_amount=Decimal('350.00'), show_compensation=True,
            start_date=date(2026, 1, 1),
            recruitment_deadline=date(2026, 12, 31),
            status=Study.Status.PUBLISHED,
        )
        cls.study.sites.add(cls.site)

        cls.priya = User.objects.create_user(
            username='priya@athena.sg', email='priya@athena.sg',
            first_name='Priya', last_name='Nair', password=cls.password,
        )
        cls.priya_group = Group.objects.get_or_create(name='Staff')[0]
        cls.priya_group.permissions.add(
            Permission.objects.get(codename='panel_access'),
            Permission.objects.get(codename='staff_access'),
        )
        cls.priya.groups.add(cls.priya_group)
        StaffProfile.objects.create(
            user=cls.priya, job_title='Operations executive', mobile='+6591234567',
        )
        cls.coordinator = User.objects.create_user(
            username='drlim@kentridge-crc.sg', email='drlim@kentridge-crc.sg',
            first_name='Daniel', last_name='Lim', password=cls.password,
        )
        coordinator_group = Group.objects.get_or_create(name='Coordinator')[0]
        coordinator_group.permissions.add(Permission.objects.get(codename='panel_access'))
        cls.coordinator.groups.add(coordinator_group)
        StaffProfile.objects.create(
            user=cls.coordinator, organisation=cls.organisation,
            job_title='Coordinator', mobile='+6591234567',
        )
        participant_group = Group.objects.get_or_create(name='Participant')[0]
        participant_group.permissions.add(
            Permission.objects.get(codename='participant_access'),
        )

        cls.payouts = {}
        for label, amount, attended in (
            ('A1', Decimal('140.00'), 2),
            ('A2', Decimal('70.00'), 1),
            ('A3', Decimal('140.00'), 1),
        ):
            participant_user = User.objects.create_user(
                username=f'{label.lower()}@example.com',
                email=f'{label.lower()}@example.com',
                first_name=label, password=cls.password,
            )
            participant_user.groups.add(participant_group)
            profile = ParticipantProfile.objects.create(
                user=participant_user, mobile='+6591234567',
                terms_accepted_at=timezone.now(),
                onboarding_completed_at=timezone.now(),
                date_of_birth=date(1990, 1, 1), sex=ParticipantProfile.Sex.FEMALE,
                region=cls.region,
            )
            application = Application.objects.create(
                participant=profile, study=cls.study,
                preferred_site=cls.site,
                availability=Application.Availability.FLEXIBLE,
                consent_given_at=timezone.now(), submitted_at=timezone.now(),
            )
            for visit_number in range(1, attended + 1):
                Appointment.objects.create(
                    application=application, site=cls.site,
                    kind=Appointment.Kind.VISIT, visit_number=visit_number,
                    status=Appointment.Status.ATTENDED,
                )
            cls.payouts[label] = Payout.objects.create(
                application=application, amount=amount,
                visits_counted=attended, status=Payout.Status.REQUESTED,
            )

        a4_user = User.objects.create_user(
            username='a4@example.com', email='a4@example.com',
            first_name='A4', password=cls.password,
        )
        a4_user.groups.add(participant_group)
        a4_profile = ParticipantProfile.objects.create(
            user=a4_user, mobile='+6591234567', terms_accepted_at=timezone.now(),
            date_of_birth=date(1990, 1, 1), sex=ParticipantProfile.Sex.FEMALE,
            region=cls.region,
        )
        a4_application = Application.objects.create(
            participant=a4_profile, study=cls.study, preferred_site=cls.site,
            availability=Application.Availability.FLEXIBLE,
            consent_given_at=timezone.now(), submitted_at=timezone.now(),
        )
        for visit_number in range(1, 6):
            Appointment.objects.create(
                application=a4_application, site=cls.site,
                kind=Appointment.Kind.VISIT, visit_number=visit_number,
                status=Appointment.Status.ATTENDED,
            )
        cls.a4_payout = Payout.objects.create(
            application=a4_application, amount=Decimal('350.00'),
            visits_counted=5, status=Payout.Status.PAID,
            reference=f'PN-{timezone.localdate().year}-000007',
            paid_by=cls.priya, paid_at=timezone.now(),
        )

    def test_01_next_payout_reference(self):
        self.assertEqual(
            next_payout_reference(timezone.localdate().year),
            f'PN-{timezone.localdate().year}-000008',
        )

    def test_02_pay_valid_payouts(self):
        result = pay_payouts(
            [self.payouts['A1'].pk, self.payouts['A2'].pk], self.priya,
        )
        self.assertEqual(result, (2, Decimal('210.00')))
        for label, reference in (('A1', '000008'), ('A2', '000009')):
            payout = Payout.objects.get(pk=self.payouts[label].pk)
            self.assertEqual(payout.status, Payout.Status.PAID)
            self.assertEqual(payout.reference, f'PN-{timezone.localdate().year}-{reference}')
            self.assertEqual(payout.paid_by, self.priya)
            self.assertIsNotNone(payout.paid_at)

    def test_03_pay_over_earned_fails(self):
        with self.assertRaises(ValidationError):
            pay_payouts([self.payouts['A3'].pk], self.priya)
        payout = Payout.objects.get(pk=self.payouts['A3'].pk)
        self.assertEqual(payout.status, Payout.Status.REQUESTED)
        self.assertIsNone(payout.reference)

    def test_04_pay_batch_is_atomic(self):
        with self.assertRaises(ValidationError):
            pay_payouts(
                [self.payouts['A1'].pk, self.payouts['A3'].pk], self.priya,
            )
        self.assertEqual(
            Payout.objects.get(pk=self.payouts['A1'].pk).status,
            Payout.Status.REQUESTED,
        )
        self.assertEqual(
            Payout.objects.get(pk=self.payouts['A3'].pk).status,
            Payout.Status.REQUESTED,
        )

    def test_05_reject_requires_reason(self):
        with self.assertRaises(ValidationError):
            reject_payout(self.payouts['A3'], self.priya, '')
        reject_payout(self.payouts['A3'], self.priya, 'Only one visit was attended.')
        payout = Payout.objects.get(pk=self.payouts['A3'].pk)
        self.assertEqual(payout.status, Payout.Status.REJECTED)
        self.assertEqual(payout.rejection_reason, 'Only one visit was attended.')

    def test_06_rejected_amount_is_due_again(self):
        self.payouts['A3'].refresh_from_db()
        reject_payout(self.payouts['A3'], self.priya, 'Only one visit was attended.')
        self.assertEqual(amount_due(self.payouts['A3'].application), Decimal('70.00'))

    def test_07_coordinator_cannot_open_payouts(self):
        self.client.login(username='drlim@kentridge-crc.sg', password=self.password)
        response = self.client.get(reverse('adminpanel:payouts'))
        self.assertEqual(response.status_code, 403)

    def test_08_paid_payout_is_visible_to_participant(self):
        self.client.login(username='priya@athena.sg', password=self.password)
        response = self.client.post(
            reverse('adminpanel:payouts'),
            {'ids': [self.payouts['A2'].pk]},
        )
        self.assertEqual(response.status_code, 200)
        response = self.client.post(
            reverse('adminpanel:payout_pay'),
            {'ids': [self.payouts['A2'].pk]},
        )
        self.assertRedirects(response, reverse('adminpanel:payouts'))
        participant = self.payouts['A2'].application.participant.user
        self.client.login(username=participant.username, password=self.password)
        response = self.client.get(
            reverse('storefront:application_detail',
                    args=[self.payouts['A2'].application.pk]),
        )
        self.assertContains(response, 'Paid')
        self.assertContains(
            response, f'PN-{timezone.localdate().year}-000008',
        )
