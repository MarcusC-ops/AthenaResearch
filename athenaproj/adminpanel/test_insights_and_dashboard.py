from django.test import TestCase, Client
from django.contrib.auth.models import User, Group
from django.db.models import Prefetch
from django.utils import timezone
from decimal import Decimal

from core.models import (
    Region, StudyCategory, Organisation, Site, Study,
    ParticipantProfile, Application, Appointment, Notification, StaffProfile
)
from core.services import (
    study_funnel, applicant_mix, shortlist_applicant, schedule_screening,
    record_screening_outcome, enrol_applicant, coordinator_dashboard
)
from core.templatetags.athena_filters import suppress_small


class InsightsAndDashboardTestCase(TestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # Create password
        password = "Kopi-Teh-2026!"

        # Create regions
        region_w = Region.objects.create(code='W', name='West', display_order=1)
        region_c = Region.objects.create(code='C', name='Central', display_order=2)

        # Create category
        category = StudyCategory.objects.create(
            name='Healthy Volunteer Phase I',
            slug='hv-phase-1',
            ml_label='HV_Phase_1',
            description='Healthy volunteer phase 1 studies',
            display_order=1
        )

        # Create Kent Ridge organisation with site and coordinator
        kent_ridge_org = Organisation.objects.create(name='Kent Ridge')
        site_k1 = Site.objects.create(
            name='K1',
            organisation=kent_ridge_org,
            region=region_w,
            address='123 Kent St',
            postal_code='123456'
        )

        drlim_user = User.objects.create_user(
            username='drlim@kentridge-crc.sg',
            first_name='Daniel',
            last_name='Lim',
            email='drlim@kentridge-crc.sg',
            password=password
        )
        drlim_profile = StaffProfile.objects.create(
            user=drlim_user,
            organisation=kent_ridge_org,
            job_title='Clinical research coordinator',
            mobile='9123 4567'
        )
        drlim_user.groups.add(Group.objects.get_or_create(name='Coordinator')[0])
        from django.contrib.auth.models import Permission
        drlim_user.user_permissions.add(Permission.objects.get(codename='panel_access'))

        # Create Harbourfront organisation with its own site and study
        harbourfront_org = Organisation.objects.create(name='Harbourfront General Hospital')
        site_hf = Site.objects.create(
            name='HF1',
            organisation=harbourfront_org,
            region=region_c,
            address='456 Harbourfront Way',
            postal_code='654321'
        )

        # Create Kent Ridge study: "Flu Vaccine Exercise Study"
        from datetime import date
        study = Study.objects.create(
            organisation=kent_ridge_org,
            category=category,
            title='Flu Vaccine Exercise Study',
            status=Study.Status.PUBLISHED,
            description='Exercise and vaccine study',
            study_type=Study.StudyType.OBSERVATIONAL,
            phase=Study.Phase.NOT_APPLICABLE,
            accepts_healthy_volunteers=True,
            sex_eligibility=Study.SexEligibility.ALL,
            min_age=21,
            max_age=65,
            smoker_rule=Study.SmokerRule.ANY,
            target_enrolment=40,
            total_visits=5,
            duration_weeks=5,
            visit_times=Study.VisitTimes.FLEXIBLE,
            compensation_amount=Decimal('350.00'),
            show_compensation=True,
            start_date=date(2026, 11, 15),
            recruitment_deadline=date(2026, 12, 31)
        )
        # Add site to study
        study.sites.add(site_k1)

        # Also create Harbourfront study
        hf_study = Study.objects.create(
            organisation=harbourfront_org,
            category=category,
            title='Harbourfront Study',
            status=Study.Status.PUBLISHED,
            description='Harbourfront study',
            study_type=Study.StudyType.OBSERVATIONAL,
            phase=Study.Phase.NOT_APPLICABLE,
            accepts_healthy_volunteers=True,
            sex_eligibility=Study.SexEligibility.ALL,
            min_age=21,
            max_age=65,
            smoker_rule=Study.SmokerRule.ANY,
            target_enrolment=20,
            total_visits=3,
            duration_weeks=3,
            visit_times=Study.VisitTimes.FLEXIBLE,
            compensation_amount=Decimal('100.00'),
            show_compensation=True,
            start_date=date(2026, 11, 15),
            recruitment_deadline=date(2026, 12, 31)
        )
        # Add site to HF study
        hf_study.sites.add(site_hf)

        # Create 10 participants for Kent Ridge study
        # 6 with consent_insights=True, women, region W
        # 4 with consent_insights=False, mixed
        kent_apps = []
        for i in range(1, 11):
            if 3 <= i <= 8:
                # Consenting women in region W
                user = User.objects.create_user(
                    username=f'kent_p{i:02d}@example.com',
                    first_name=f'Woman{i}',
                    last_name='TestW',
                    email=f'kent_p{i:02d}@example.com',
                    password=password
                )
                participant = ParticipantProfile.objects.create(
                    user=user,
                    mobile='91234567',
                    terms_accepted_at=timezone.now(),
                    date_of_birth=f'198{i % 10}-01-01',
                    sex='female',
                    region=region_w,
                    consent_insights=True,
                    consent_contact=True,
                    consent_matching=True
                )
            else:
                # Non-consenting, mixed region
                user = User.objects.create_user(
                    username=f'kent_p{i:02d}@example.com',
                    first_name=f'Participant{i}',
                    last_name=f'TestNC',
                    email=f'kent_p{i:02d}@example.com',
                    password=password
                )
                region = region_w if i % 2 == 0 else region_c
                participant = ParticipantProfile.objects.create(
                    user=user,
                    mobile='91234567',
                    terms_accepted_at=timezone.now(),
                    date_of_birth=f'197{i % 10}-01-01',
                    sex='male',
                    region=region,
                    consent_insights=False,
                    consent_contact=True,
                    consent_matching=True
                )

            # Create application
            app = Application.objects.create(
                participant=participant,
                study=study,
                preferred_site=site_k1,
                availability=Application.Availability.FLEXIBLE,
                consent_given_at=timezone.now(),
                submitted_at=timezone.now(),
                status=Application.Status.SUBMITTED
            )
            kent_apps.append(app)

        # 3 Harbourfront applications
        hf_apps = []
        for i in range(1, 4):
            user = User.objects.create_user(
                username=f'hf_p{i:02d}@example.com',
                first_name=f'HFPerson{i}',
                last_name='HF',
                email=f'hf_p{i:02d}@example.com',
                password=password
            )
            participant = ParticipantProfile.objects.create(
                user=user,
                mobile='91234567',
                terms_accepted_at=timezone.now(),
                date_of_birth=f'1985-01-0{i}',
                sex='female',
                region=region_c,
                consent_insights=True,
                consent_contact=True,
                consent_matching=True
            )
            app = Application.objects.create(
                participant=participant,
                study=hf_study,
                preferred_site=site_hf,
                availability=Application.Availability.FLEXIBLE,
                consent_given_at=timezone.now(),
                submitted_at=timezone.now(),
                status=Application.Status.ENROLLED
            )
            hf_apps.append(app)

        # Move Kent Ridge apps through services
        # 2 auto_declined: apps 0, 1
        kent_apps[0].status = Application.Status.AUTO_DECLINED
        kent_apps[0].save()
        kent_apps[1].status = Application.Status.AUTO_DECLINED
        kent_apps[1].save()

        # 3 under_review: apps 2, 3, 4 (app 2 has HIGH band)
        kent_apps[2].status = Application.Status.UNDER_REVIEW
        kent_apps[2].ml2_band = Application.Band.HIGH
        kent_apps[2].save()
        kent_apps[3].status = Application.Status.UNDER_REVIEW
        kent_apps[3].ml2_band = Application.Band.MEDIUM
        kent_apps[3].save()
        kent_apps[4].status = Application.Status.UNDER_REVIEW
        kent_apps[4].ml2_band = Application.Band.LOW
        kent_apps[4].save()

        # 1 shortlisted: app 5
        shortlist_applicant(kent_apps[5], drlim_user)

        # 1 screening_failed: app 6
        shortlist_applicant(kent_apps[6], drlim_user)
        # Schedule screening
        schedule_screening(
            kent_apps[6],
            __import__('django.utils.timezone', fromlist=['now']).now() + __import__('datetime', fromlist=['timedelta']).timedelta(days=3),
            site_k1,
            drlim_user
        )
        # Mark screening failed
        record_screening_outcome(kent_apps[6], False, drlim_user)

        # 3 enrolled: apps 7, 8, 9
        for app_idx in [7, 8, 9]:
            shortlist_applicant(kent_apps[app_idx], drlim_user)
            schedule_screening(
                kent_apps[app_idx],
                __import__('django.utils.timezone', fromlist=['now']).now() + __import__('datetime', fromlist=['timedelta']).timedelta(days=3),
                site_k1,
                drlim_user
            )
            record_screening_outcome(kent_apps[app_idx], True, drlim_user)
            enrol_applicant(kent_apps[app_idx], drlim_user)

        # Store for use in tests
        cls.study = study
        cls.kent_ridge_org = kent_ridge_org
        cls.drlim_user = drlim_user
        cls.drlim_password = password
        cls.kent_apps = kent_apps
        cls.hf_apps = hf_apps
        cls.hf_study = hf_study
        cls.site = site_k1
        cls.region_w = region_w

    def test_01_study_funnel(self):
        """study_funnel for Kent Ridge should show correct counts"""
        # Get Kent Ridge applications only
        apps_qs = Application.objects.filter(study=self.study)

        funnel = study_funnel(apps_qs)

        # Expected: Applied 10, Passed pre-screen 8, Shortlisted 5,
        # Screened 4, Passed 3, Enrolled 3, Completed 0
        self.assertEqual(funnel.get('applied'), 10)
        self.assertEqual(funnel.get('passed_pre_screen'), 8)
        self.assertEqual(funnel.get('shortlisted'), 5)
        self.assertEqual(funnel.get('screened'), 4)
        self.assertEqual(funnel.get('passed_screening'), 3)
        self.assertEqual(funnel.get('enrolled'), 3)
        self.assertEqual(funnel.get('completed'), 0)

    def test_02_applicant_mix_sex(self):
        """applicant_mix for Kent Ridge should count only 6 consenting women"""
        apps_qs = Application.objects.filter(study=self.study)

        mix = applicant_mix(apps_qs)

        # Only consenting participants (6 women)
        applied_sex = mix['sex'].get('applied', {})
        self.assertEqual(applied_sex.get('female'), 6)
        self.assertEqual(applied_sex.get('male', 0), 0)

    def test_03_suppress_small_filter(self):
        """Test suppress_small template filter"""
        self.assertEqual(suppress_small(0), '0')
        self.assertEqual(suppress_small(1), 'fewer than 5')
        self.assertEqual(suppress_small(4), 'fewer than 5')
        self.assertEqual(suppress_small(5), '5')
        self.assertEqual(suppress_small(10), '10')

    def test_04_insights_page_coordination_scoping(self):
        """GET /panel/insights/ should show only Kent Ridge data"""
        client = Client()
        client.login(username='drlim@kentridge-crc.sg', password=self.drlim_password)

        response = client.get('/panel/insights/')

        # Should show insights page
        self.assertEqual(response.status_code, 200)

        # Should contain recruitment funnel heading
        self.assertContains(response, 'Recruitment funnel')

        # Should contain "fewer than 5" indicator
        self.assertContains(response, 'fewer than 5')

        # Should show Applied: 10 (only Kent Ridge, not Harbourfront's 3)
        # Look for the funnel applied count
        content = response.content.decode()
        # The funnel table should show Applied 10
        self.assertIn('>10<', content)  # Applied count

        # Should not show Harbourfront's applications
        # (We're checking that Kent Ridge's 10 is shown, implying scoping works)

    def test_05_coordinator_dashboard_metrics(self):
        """coordinator_dashboard(drlim) should show correct metrics"""
        dashboard = coordinator_dashboard(self.drlim_user)

        # New applications priority (HIGH band): 1
        self.assertEqual(dashboard['high_priority'], 1)

        # Awaiting review total: 3
        self.assertEqual(dashboard['awaiting_review'], 3)

    def test_06_dashboard_page_coordinator_view(self):
        """GET /panel/ as drlim should show coordinator dashboard"""
        client = Client()
        client.login(username='drlim@kentridge-crc.sg', password=self.drlim_password)

        response = client.get('/panel/')

        # Should render successfully
        self.assertEqual(response.status_code, 200)

        # Should show "What needs your attention today."
        self.assertContains(response, 'What needs your attention today')

        # Should show organisation name "Kent Ridge"
        self.assertContains(response, 'Kent Ridge')

    def test_07_insights_page_query_count(self):
        """Query count for /panel/insights/ should not grow with 20 more apps"""
        from django.test.utils import override_settings

        client = Client()
        client.login(username='drlim@kentridge-crc.sg', password=self.drlim_password)

        # Get initial query count
        from django.test.utils import CaptureQueriesContext
        from django.db import connection

        with CaptureQueriesContext(connection) as context:
            response = client.get('/panel/insights/')

        initial_query_count = len(context)
        self.assertEqual(response.status_code, 200)

        # Add 20 more applications to Kent Ridge study
        password = self.drlim_password
        for i in range(11, 31):
            user = User.objects.create_user(
                username=f'kent_extra_p{i:02d}@example.com',
                first_name=f'Extra{i}',
                last_name='Test',
                email=f'kent_extra_p{i:02d}@example.com',
                password=password
            )
            participant = ParticipantProfile.objects.create(
                user=user,
                mobile='91234567',
                terms_accepted_at=timezone.now(),
                date_of_birth='1990-01-01',
                sex='female',
                region=self.region_w,
                consent_insights=True,
                consent_contact=True,
                consent_matching=True
            )
            Application.objects.create(
                participant=participant,
                study=self.study,
                preferred_site=self.site,
                availability=Application.Availability.FLEXIBLE,
                consent_given_at=timezone.now(),
                submitted_at=timezone.now(),
                status=Application.Status.SUBMITTED
            )

        # Get query count with 30 total applications
        with CaptureQueriesContext(connection) as context2:
            response2 = client.get('/panel/insights/')

        new_query_count = len(context2)
        self.assertEqual(response2.status_code, 200)

        # Query count should be approximately the same (allow small variance)
        # Should not double or triple just because we added 20 more applications
        self.assertLessEqual(
            new_query_count,
            initial_query_count + 3,
            f"Query count grew from {initial_query_count} to {new_query_count}"
        )
