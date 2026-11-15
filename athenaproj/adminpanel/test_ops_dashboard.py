from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.utils import timezone

from core.models import (
    Application,
    Organisation,
    ParticipantProfile,
    Payout,
    Region,
    Review,
    Site,
    StaffProfile,
    Study,
    StudyCategory,
    SupportRequest,
)
from core.services import change_status, ops_dashboard


class OperationsDashboardTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.staff = User.objects.create_user(
            username='priya@athena.sg',
            email='priya@athena.sg',
            first_name='Priya',
            last_name='Nair',
            password='Kopi-Teh-2026!',
        )
        cls.staff.groups.add(Group.objects.get(name='Staff'))
        StaffProfile.objects.create(
            user=cls.staff,
            job_title='Operations executive',
            mobile='+6591234567',
        )

        cls.region = Region.objects.create(
            code='W', name='West', display_order=5,
        )
        cls.category = StudyCategory.objects.create(
            name='Sleep',
            slug='sleep',
            ml_label='sleep',
            description='Explore sleep research.',
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
            region=cls.region,
        )

        today = timezone.localdate()
        common_study = {
            'organisation': cls.organisation,
            'category': cls.category,
            'description': 'A study about sleep habits in Singapore.',
            'study_type': Study.StudyType.OBSERVATIONAL,
            'accepts_healthy_volunteers': True,
            'min_age': 21,
            'max_age': 65,
            'target_enrolment': 10,
            'total_visits': 1,
            'duration_weeks': 4,
            'visit_times': Study.VisitTimes.FLEXIBLE,
            'compensation_amount': Decimal('100.00'),
            'show_compensation': False,
            'start_date': today,
            'recruitment_deadline': today + timedelta(days=14),
            'irb_name': 'NUS-IRB',
            'irb_reference': 'NUS-IRB-2026-0412',
            'irb_approved_text': True,
        }
        cls.pending_study = Study.objects.create(
            title='Study awaiting review',
            status=Study.Status.PENDING_REVIEW,
            irb_expiry=today + timedelta(days=60),
            **common_study,
        )
        cls.expiring_study = Study.objects.create(
            title='Approval expiring in 20 days',
            status=Study.Status.PUBLISHED,
            irb_expiry=today + timedelta(days=20),
            **common_study,
        )
        cls.later_study = Study.objects.create(
            title='Approval expiring in 31 days',
            status=Study.Status.PUBLISHED,
            irb_expiry=today + timedelta(days=31),
            **common_study,
        )
        cls.full_study = Study.objects.create(
            title='Full study with a waitlist',
            status=Study.Status.FULL,
            irb_expiry=today + timedelta(days=60),
            **common_study,
        )
        for study in (
            cls.pending_study, cls.expiring_study, cls.later_study,
            cls.full_study,
        ):
            study.sites.add(cls.site)

        participants = []
        for first_name, email, mobile in (
            ('Aisyah', 'aisyah@example.com', '+6591234567'),
            ('Tan', 'mrtan@example.com', '+6581234567'),
        ):
            user = User.objects.create_user(
                username=email,
                email=email,
                first_name=first_name,
                password='Kopi-Teh-2026!',
            )
            user.groups.add(Group.objects.get(name='Participant'))
            participants.append(ParticipantProfile.objects.create(
                user=user,
                mobile=mobile,
                terms_accepted_at=timezone.now(),
            ))

        applications = []
        for participant in participants:
            application = Application.objects.create(
                participant=participant,
                study=cls.full_study,
                preferred_site=cls.site,
                availability=Application.Availability.FLEXIBLE,
                consent_given_at=timezone.now(),
                submitted_at=timezone.now(),
            )
            change_status(application, Application.Status.WAITLISTED)
            applications.append(application)

        cls.payout = Payout.objects.create(
            application=applications[0],
            amount=Decimal('100.00'),
            visits_counted=1,
            status=Payout.Status.REQUESTED,
            requested_by=cls.staff,
        )
        cls.review = Review.objects.create(
            participant=participants[0],
            study=cls.full_study,
            rating=5,
            status=Review.Status.PENDING,
        )
        cls.support = SupportRequest.objects.create(
            application=applications[0],
            topic=SupportRequest.Topic.APPLICATION,
            question='How is my application progressing?',
            status=SupportRequest.Status.OPEN,
        )

    def setUp(self):
        self.staff.refresh_from_db()
        self.pending_study.refresh_from_db()
        self.expiring_study.refresh_from_db()
        self.later_study.refresh_from_db()
        self.full_study.refresh_from_db()
        self.payout.refresh_from_db()
        self.review.refresh_from_db()
        self.support.refresh_from_db()

    def test_01_dashboard_counts_all_four_queues(self):
        dashboard = ops_dashboard()
        self.assertEqual(dashboard['listing_count'], 1)
        self.assertEqual(dashboard['payout_count'], 1)
        self.assertEqual(dashboard['review_count'], 1)
        self.assertEqual(dashboard['support_count'], 1)

    def test_02_irb_alert_includes_20_days_but_not_31_days(self):
        alerts = ops_dashboard()['alerts']
        irb_study_ids = {
            alert['study'].pk
            for alert in alerts
            if isinstance(alert, dict) and alert['kind'] == 'irb'
        }
        self.assertIn(self.expiring_study.pk, irb_study_ids)
        self.assertNotIn(self.later_study.pk, irb_study_ids)

    def test_03_full_study_alert_counts_two_waitlisted_applications(self):
        alerts = ops_dashboard()['alerts']
        waitlist_alerts = [
            alert for alert in alerts
            if isinstance(alert, dict) and alert['kind'] == 'waitlist'
            and alert['study'].pk == self.full_study.pk
        ]
        self.assertEqual(len(waitlist_alerts), 1)
        self.assertEqual(waitlist_alerts[0]['count'], 2)

    def test_04_staff_dashboard_shows_nonempty_queues(self):
        self.client.force_login(self.staff)
        response = self.client.get('/panel/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Operations')
        self.assertNotContains(response, 'All clear')
        for label in (
            'Listings awaiting moderation',
            'Payouts awaiting payment',
            'Reviews to moderate',
            'Support questions (open)',
        ):
            self.assertContains(response, label)

    def test_05_empty_queues_show_all_clear_four_times(self):
        self.pending_study.status = Study.Status.DRAFT
        self.pending_study.save(update_fields=['status', 'updated_at'])
        self.payout.status = Payout.Status.PAID
        self.payout.save(update_fields=['status', 'updated_at'])
        self.review.status = Review.Status.APPROVED
        self.review.save(update_fields=['status', 'updated_at'])
        self.support.status = SupportRequest.Status.ANSWERED
        self.support.save(update_fields=['status', 'updated_at'])

        self.client.force_login(self.staff)
        response = self.client.get('/panel/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'All clear', count=4)

    def test_06_missing_model_files_show_load_failure(self):
        self.client.force_login(self.staff)
        with TemporaryDirectory() as directory:
            with patch('ml.services.MODEL_DIR', Path(directory)):
                response = self.client.get('/panel/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'The ML-1 model file could not be loaded.')
        self.assertContains(response, 'The ML-2 model file could not be loaded.')
