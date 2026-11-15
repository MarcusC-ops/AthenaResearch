from datetime import date
from decimal import Decimal

from django.contrib.auth.models import Group, Permission, User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import (
    Application,
    Organisation,
    ParticipantProfile,
    Region,
    Review,
    Site,
    Study,
    StudyCategory,
    StaffProfile,
    SupportRequest,
)
from core.services import (
    approve_review,
    demand_supply_by_category,
    reject_review,
    reply_to_support,
)


class ReviewsSupportPlatformTestCase(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.password = 'Kopi-Teh-2026!'
        cls.region = Region.objects.create(code='W', name='West', display_order=1)
        cls.categories = {
            slug: StudyCategory.objects.create(
                name=name, slug=slug, ml_label=label,
                description=f'{name} studies.', display_order=index,
            )
            for index, (name, slug, label) in enumerate((
                ('Sleep', 'sleep', 'sleep'),
                ('Mental Health', 'mental-health', 'mental_health'),
                ('Cognitive', 'cognitive', 'cognitive'),
            ), 1)
        }
        cls.organisation = Organisation.objects.create(
            name='Research Organisation',
            org_type=Organisation.OrganisationType.UNIVERSITY,
            contact_person='Priya Nair', contact_email='priya@athena.sg',
        )
        cls.site = Site.objects.create(
            name='W1', organisation=cls.organisation, region=cls.region,
            address='1 West Road', postal_code='119077',
        )
        cls.priya = User.objects.create_user(
            username='priya@athena.sg', email='priya@athena.sg',
            first_name='Priya', last_name='Nair', password=cls.password,
        )
        staff_group = Group.objects.get_or_create(name='Staff')[0]
        staff_group.permissions.add(
            Permission.objects.get(codename='panel_access'),
            Permission.objects.get(codename='staff_access'),
        )
        cls.priya.groups.add(staff_group)
        StaffProfile.objects.create(
            user=cls.priya, job_title='Operations executive', mobile='+6591234567',
        )
        cls.participant_group = Group.objects.get_or_create(name='Participant')[0]
        cls.participant_group.permissions.add(
            Permission.objects.get(codename='participant_access'),
        )

        def make_study(title, category, target):
            study = Study.objects.create(
                organisation=cls.organisation, category=category, title=title,
                description=f'{title} description.',
                study_type=Study.StudyType.OBSERVATIONAL,
                phase=Study.Phase.NOT_APPLICABLE,
                accepts_healthy_volunteers=True,
                sex_eligibility=Study.SexEligibility.ALL,
                min_age=21, max_age=65, smoker_rule=Study.SmokerRule.ANY,
                target_enrolment=target, total_visits=5, duration_weeks=5,
                visit_times=Study.VisitTimes.FLEXIBLE,
                compensation_amount=Decimal('100.00'), show_compensation=True,
                start_date=date(2026, 1, 1), recruitment_deadline=date(2026, 12, 31),
                status=Study.Status.PUBLISHED,
            )
            study.sites.add(cls.site)
            return study

        cls.memory = make_study('Memory Games', cls.categories['cognitive'], 10)
        cls.sleep_1 = make_study('Sleep Study One', cls.categories['sleep'], 10)
        cls.sleep_2 = make_study('Sleep Study Two', cls.categories['sleep'], 5)

        def make_participant(label, consent=True, first_pick='sleep'):
            user = User.objects.create_user(
                username=f'{label.lower()}@example.com',
                email=f'{label.lower()}@example.com',
                first_name=label, password=cls.password,
            )
            user.groups.add(cls.participant_group)
            profile = ParticipantProfile.objects.create(
                user=user, mobile='+6591234567', terms_accepted_at=timezone.now(),
                date_of_birth=date(1990, 1, 1), sex=ParticipantProfile.Sex.FEMALE,
                region=cls.region, consent_matching=consent,
                consent_insights=True, ml1_categories=[first_pick],
            )
            return profile

        cls.p1 = make_participant('P1')
        cls.p2 = make_participant('P2')
        cls.p3 = make_participant('P3')
        make_participant('NoConsent', consent=False)
        make_participant('M1', first_pick='mental_health')
        make_participant('M2', first_pick='mental_health')

        def make_application(profile, study, status=Application.Status.SUBMITTED):
            return Application.objects.create(
                participant=profile, study=study, preferred_site=cls.site,
                availability=Application.Availability.FLEXIBLE,
                consent_given_at=timezone.now(), submitted_at=timezone.now(),
                status=status,
            )

        cls.p1_application = make_application(cls.p1, cls.memory)
        cls.support_request = SupportRequest.objects.create(
            application=cls.p1_application,
            topic=SupportRequest.Topic.COMPENSATION,
            question='When will I be paid?',
        )
        cls.review = Review.objects.create(
            participant=cls.p1, study=cls.memory, rating=4,
        )
        for index in range(2):
            make_application(
                make_participant(f'SleepEnrolled{index}', consent=False),
                cls.sleep_1,
                Application.Status.ENROLLED,
            )

    def test_01_approve_review_publishes_rating(self):
        approve_review(self.review, self.priya)
        self.assertEqual(Review.objects.get(pk=self.review.pk).status, Review.Status.APPROVED)
        response = self.client.get(
            reverse('storefront:study_detail', args=[self.memory.slug]),
        )
        self.assertContains(response, '4.0 / 5 (1 review)')

    def test_02_reject_approved_review_fails(self):
        self.review.refresh_from_db()
        approve_review(self.review, self.priya)
        with self.assertRaises(ValidationError):
            reject_review(self.review, self.priya, 'Not suitable.')

    def test_03_reply_to_support(self):
        reply_to_support(
            self.support_request, self.priya,
            'Payouts are made within 5 working days.',
        )
        request = SupportRequest.objects.get(pk=self.support_request.pk)
        self.assertEqual(request.status, SupportRequest.Status.ANSWERED)
        self.assertEqual(request.replied_by, self.priya)

    def test_04_second_support_reply_fails(self):
        self.support_request.refresh_from_db()
        reply_to_support(
            self.support_request, self.priya,
            'Payouts are made within 5 working days.',
        )
        with self.assertRaisesMessage(ValidationError, 'This question already has a reply.'):
            reply_to_support(self.support_request, self.priya, 'Second answer')
        self.assertEqual(
            SupportRequest.objects.get(pk=self.support_request.pk).reply,
            'Payouts are made within 5 working days.',
        )

    def test_05_participant_sees_support_reply(self):
        self.support_request.refresh_from_db()
        reply_to_support(
            self.support_request, self.priya,
            'Payouts are made within 5 working days.',
        )
        self.client.login(username='p1@example.com', password=self.password)
        response = self.client.get(
            reverse('storefront:application_detail', args=[self.p1_application.pk]),
        )
        self.assertContains(response, 'Payouts are made within 5 working days.')
        self.assertContains(response, 'Athena team')
        self.assertNotContains(response, 'Priya')

    def test_06_demand_supply_by_category(self):
        data = {
            item['category'].slug: item
            for item in demand_supply_by_category()
        }
        self.assertEqual(data['sleep']['interested_participants'], 3)
        self.assertEqual(data['sleep']['open_studies'], 2)
        self.assertEqual(data['sleep']['places_left'], 13)
        self.assertEqual(data['mental-health']['interested_participants'], 2)
        self.assertEqual(data['mental-health']['open_studies'], 0)

    def test_07_staff_platform_insights_page(self):
        self.client.login(username='priya@athena.sg', password=self.password)
        response = self.client.get(reverse('adminpanel:insights'))
        self.assertContains(response, 'Platform insights')
        self.assertContains(response, 'Demand and supply by category')
