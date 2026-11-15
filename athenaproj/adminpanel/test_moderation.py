from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from core.models import (
    Notification,
    Organisation,
    ParticipantProfile,
    PreScreenQuestion,
    Region,
    Site,
    StaffProfile,
    Study,
    StudyCategory,
)
from core.services import approve_study, return_study, unpublish_study


class StudyModerationTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.region = Region.objects.create(
            code='W',
            name='West',
            display_order=5,
        )
        cls.category = StudyCategory.objects.create(
            name='Sleep',
            slug='sleep',
            ml_label='sleep',
            description='Explore sleep research.',
            display_order=8,
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

        cls.coordinator = User.objects.create_user(
            username='drlim@kentridge-crc.sg',
            email='drlim@kentridge-crc.sg',
            first_name='Daniel',
            last_name='Lim',
            password='Kopi-Teh-2026!',
        )
        cls.coordinator.groups.add(Group.objects.get(name='Coordinator'))
        StaffProfile.objects.create(
            user=cls.coordinator,
            organisation=cls.organisation,
            job_title='Clinical research coordinator',
            mobile='+6591234567',
        )

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
            organisation=None,
            job_title='Operations executive',
            mobile='+6591234568',
        )

        cls.participant = User.objects.create_user(
            username='aisyah@example.com',
            email='aisyah@example.com',
            first_name='Aisyah',
            last_name='Rahman',
            password='Kopi-Teh-2026!',
        )
        cls.participant.groups.add(Group.objects.get(name='Participant'))
        ParticipantProfile.objects.create(
            user=cls.participant,
            mobile='+6591234569',
            terms_accepted_at=cls.participant.date_joined,
        )

        today = timezone.localdate()
        deadline = today + timedelta(days=30)
        common = {
            'organisation': cls.organisation,
            'category': cls.category,
            'visit_plan': 'Visit 1: sleep questionnaire.',
            'study_type': Study.StudyType.OBSERVATIONAL,
            'accepts_healthy_volunteers': True,
            'min_age': 21,
            'max_age': 65,
            'target_enrolment': 40,
            'total_visits': 1,
            'duration_weeks': 4,
            'visit_times': Study.VisitTimes.FLEXIBLE,
            'compensation_amount': Decimal('120.00'),
            'show_compensation': True,
            'start_date': today,
            'recruitment_deadline': deadline,
            'irb_name': 'NUS-IRB',
            'irb_reference': 'NUS-IRB-2026-0412',
            'irb_expiry': deadline + timedelta(days=90),
            'irb_approved_text': True,
        }
        cls.sleep_study = Study.objects.create(
            title='Sleep Habits Study',
            description='A study about sleep habits in Singapore.',
            status=Study.Status.PENDING_REVIEW,
            created_by=cls.coordinator,
            last_edited_by=cls.coordinator,
            **common,
        )
        cls.sleep_study.sites.add(cls.site)

        cls.earn_study = Study.objects.create(
            title='Earn Fast Study',
            description='This study will earn attention from participants.',
            status=Study.Status.PENDING_REVIEW,
            created_by=cls.coordinator,
            last_edited_by=cls.coordinator,
            **common,
        )
        cls.earn_study.sites.add(cls.site)

        cls.live_study = Study.objects.create(
            title='Live Study',
            description='A live study about sleep habits.',
            status=Study.Status.PUBLISHED,
            created_by=cls.coordinator,
            last_edited_by=cls.coordinator,
            published_at=timezone.now(),
            **common,
        )
        cls.live_study.sites.add(cls.site)

        for study in (cls.sleep_study, cls.earn_study, cls.live_study):
            PreScreenQuestion.objects.create(
                study=study,
                text='Do you work night shifts?',
                order=1,
                options='Yes\nNo',
                preferred_answer='No',
                disqualifying_answer='',
            )

    def setUp(self):
        self.sleep_study = Study.objects.get(pk=type(self).sleep_study.pk)
        self.sleep_study.refresh_from_db()
        self.earn_study = Study.objects.get(pk=type(self).earn_study.pk)
        self.earn_study.refresh_from_db()
        self.live_study = Study.objects.get(pk=type(self).live_study.pk)
        self.live_study.refresh_from_db()
        self.coordinator = User.objects.get(pk=type(self).coordinator.pk)
        self.coordinator.refresh_from_db()
        self.staff = User.objects.get(pk=type(self).staff.pk)
        self.staff.refresh_from_db()
        self.participant = User.objects.get(pk=type(self).participant.pk)
        self.participant.refresh_from_db()

    def test_01_approve_compliant_study_and_notify_coordinator(self):
        approve_study(self.sleep_study, self.staff)
        self.sleep_study.refresh_from_db()
        self.assertEqual(self.sleep_study.status, Study.Status.PUBLISHED)
        self.assertIsNotNone(self.sleep_study.published_at)
        self.assertEqual(self.sleep_study.reviewed_by, self.staff)
        self.assertTrue(
            Notification.objects.filter(
                user=self.coordinator,
                message__icontains='approved',
            ).exists()
        )

    def test_02_approval_rejects_non_compliant_study(self):
        with self.assertRaises(ValidationError):
            approve_study(self.earn_study, self.staff)
        self.earn_study.refresh_from_db()
        self.assertEqual(self.earn_study.status, Study.Status.PENDING_REVIEW)

    def test_03_failed_compliance_disables_approve_button(self):
        self.client.force_login(self.staff)
        response = self.client.get(
            f'/panel/moderation/{self.earn_study.pk}/'
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Fail')
        self.assertRegex(
            response.content.decode(),
            r'<button[^>]*disabled[^>]*>Approve and publish</button>',
        )

    def test_04_direct_approval_post_still_checks_compliance(self):
        self.client.force_login(self.staff)
        response = self.client.post(
            f'/panel/moderation/{self.earn_study.pk}/',
            {'action': 'approve'},
        )
        self.assertEqual(response.status_code, 302)
        self.earn_study.refresh_from_db()
        self.assertEqual(self.earn_study.status, Study.Status.PENDING_REVIEW)

    def test_05_return_requires_comments_and_saves_them(self):
        with self.assertRaises(ValidationError):
            return_study(self.earn_study, self.staff, '')
        return_study(
            self.earn_study,
            self.staff,
            'Please remove the word earn.',
        )
        self.earn_study.refresh_from_db()
        self.assertEqual(
            self.earn_study.status,
            Study.Status.CHANGES_REQUESTED,
        )
        self.assertEqual(
            self.earn_study.moderation_comments,
            'Please remove the word earn.',
        )

    def test_06_unpublish_pauses_study_and_hides_storefront_page(self):
        unpublish_study(
            self.live_study,
            self.staff,
            'IRB renewal pending',
        )
        self.live_study.refresh_from_db()
        self.assertEqual(self.live_study.status, Study.Status.PAUSED)
        self.assertEqual(
            self.live_study.paused_reason,
            'IRB renewal pending',
        )
        response = self.client.get('/studies/live-study/')
        self.assertEqual(response.status_code, 404)

    def test_07_paused_study_can_be_approved_again(self):
        unpublish_study(
            self.live_study,
            self.staff,
            'IRB renewal pending',
        )
        self.live_study.refresh_from_db()
        approve_study(self.live_study, self.staff)
        self.live_study.refresh_from_db()
        self.assertEqual(self.live_study.status, Study.Status.PUBLISHED)
        self.assertEqual(self.live_study.paused_reason, '')

    def test_08_moderation_is_forbidden_to_coordinators_and_participants(self):
        self.client.force_login(self.coordinator)
        self.assertEqual(self.client.get('/panel/moderation/').status_code, 403)
        self.client.force_login(self.participant)
        self.assertEqual(self.client.get('/panel/moderation/').status_code, 403)
