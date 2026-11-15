from datetime import timedelta

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.utils import timezone

from core.models import Application, Organisation, ParticipantProfile, Region, Site, Study, StudyCategory
from core.services import alternatives_for, popular_studies


class AlternativesAndPopularTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        region = Region.objects.create(code='W', name='West', display_order=5)
        sleep_category = StudyCategory.objects.create(
            name='Sleep',
            slug='sleep',
            ml_label='sleep',
            description='Sleep and recovery research.',
            display_order=1,
        )
        mental_category = StudyCategory.objects.create(
            name='Mental Health',
            slug='mental-health',
            ml_label='mental_health',
            description='Mental health and wellbeing research.',
            display_order=2,
        )
        heart_category = StudyCategory.objects.create(
            name='Heart and Blood Pressure',
            slug='heart-and-blood-pressure',
            ml_label='heart',
            description='Heart and blood pressure research.',
            display_order=3,
        )
        organisation = Organisation.objects.create(
            name='Harbourfront General Hospital',
            org_type=Organisation.OrganisationType.HOSPITAL,
            contact_person='Nur Hidayah Salleh',
            contact_email='nur@example.sg',
        )
        site = Site.objects.create(
            organisation=organisation,
            name='W',
            address='1 West Road',
            postal_code='123456',
            region=region,
        )

        participant_group, _ = Group.objects.get_or_create(name='Participant')
        user = User.objects.create_user(
            username='aisyah@example.com',
            email='aisyah@example.com',
            first_name='Aisyah',
            last_name='Rahman',
            password='Password123!',
        )
        user.groups.add(participant_group)
        cls.aisyah = ParticipantProfile.objects.create(
            user=user,
            mobile='+6591234567',
            terms_accepted_at=timezone.now(),
            onboarding_completed_at=timezone.now(),
            date_of_birth=timezone.localdate().replace(year=timezone.localdate().year - 30),
            sex=ParticipantProfile.Sex.FEMALE,
            region=region,
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
        cls.aisyah.ml1_categories = ['mental_health', 'sleep']
        cls.aisyah.save(update_fields=['ml1_categories', 'updated_at'])

        def make_study(
            title,
            category,
            min_age,
            max_age,
            status=Study.Status.PUBLISHED,
            published_at=None,
            recruitment_deadline=None,
        ):
            study = Study.objects.create(
                organisation=organisation,
                category=category,
                title=title,
                description=f'{title} description.',
                study_type=Study.StudyType.OBSERVATIONAL,
                phase=Study.Phase.NOT_APPLICABLE,
                accepts_healthy_volunteers=True,
                sex_eligibility=Study.SexEligibility.ALL,
                min_age=min_age,
                max_age=max_age,
                smoker_rule=Study.SmokerRule.ANY,
                target_enrolment=40,
                total_visits=1,
                duration_weeks=4,
                visit_times=Study.VisitTimes.WEEKDAY_EVENINGS,
                compensation_amount='0.00',
                show_compensation=False,
                start_date=timezone.localdate(),
                recruitment_deadline=recruitment_deadline or (timezone.localdate() + timedelta(days=30)),
                status=status,
                published_at=published_at or timezone.now(),
            )
            study.sites.add(site)
            return study

        cls.s1 = make_study('Sleep Habits Study', sleep_category, 21, 70, published_at=timezone.now() - timedelta(days=45), recruitment_deadline=timezone.localdate() + timedelta(days=30))
        cls.s2 = make_study('Night Owls Study', sleep_category, 21, 70, published_at=timezone.now() - timedelta(days=20), recruitment_deadline=timezone.localdate() + timedelta(days=10))
        cls.s3 = make_study('Calm Minds Trial', mental_category, 21, 70, published_at=timezone.now() - timedelta(days=60), recruitment_deadline=timezone.localdate() + timedelta(days=30))
        cls.s4 = make_study('Mood and Movement', mental_category, 21, 70, published_at=timezone.now() - timedelta(days=5), recruitment_deadline=timezone.localdate() + timedelta(days=15))
        cls.s5 = make_study('Midlife Heart Study', heart_category, 40, 65, published_at=timezone.now() - timedelta(days=15), recruitment_deadline=timezone.localdate() + timedelta(days=20))
        cls.draft = make_study('Draft Study', sleep_category, 21, 70, status=Study.Status.DRAFT, published_at=timezone.now() - timedelta(days=1))

        Application.objects.create(
            participant=cls.aisyah,
            study=cls.s4,
            status=Application.Status.SUBMITTED,
            preferred_site=site,
            availability=Application.Availability.WEEKDAY_EVENINGS,
            consent_given_at=timezone.now(),
            submitted_at=timezone.now(),
        )

        def create_participant(prefix):
            user = User.objects.create_user(
                username=f'{prefix}@example.com',
                email=f'{prefix}@example.com',
                first_name=prefix.title(),
                last_name='Participant',
                password='Password123!',
            )
            user.groups.add(participant_group)
            profile = ParticipantProfile.objects.create(
                user=user,
                mobile=f'+659{1000000 + len(User.objects.filter(username__icontains="@example.com"))}',
                terms_accepted_at=timezone.now(),
                onboarding_completed_at=timezone.now(),
                date_of_birth=timezone.localdate().replace(year=timezone.localdate().year - 30),
                sex=ParticipantProfile.Sex.FEMALE,
                region=region,
                employment=ParticipantProfile.Employment.FULL_TIME,
                education=ParticipantProfile.Education.DEGREE,
                height_cm='165.0',
                weight_kg='60.0',
                smoker=False,
                activity_level=ParticipantProfile.ActivityLevel.MODERATE,
                availability=ParticipantProfile.Availability.WEEKDAY_DAYTIME,
                max_travel_minutes=ParticipantProfile.TravelMinutes.THIRTY,
                consent_matching=True,
                consent_insights=True,
                consent_contact=True,
            )
            return profile

        cls.applicant_1 = create_participant('popular1')
        cls.applicant_2 = create_participant('popular2')
        cls.applicant_3 = create_participant('popular3')
        cls.applicant_4 = create_participant('older')

        for participant, study, age_days in [
            (cls.applicant_1, cls.s3, 3),
            (cls.applicant_2, cls.s3, 5),
            (cls.applicant_3, cls.s3, 9),
            (cls.applicant_4, cls.s1, 40),
        ]:
            Application.objects.create(
                participant=participant,
                study=study,
                status=Application.Status.SUBMITTED,
                preferred_site=site,
                availability=Application.Availability.WEEKDAY_EVENINGS,
                consent_given_at=timezone.now(),
                submitted_at=timezone.now() - timedelta(days=age_days),
            )

        Application.objects.create(
            participant=cls.applicant_1,
            study=cls.draft,
            status=Application.Status.SUBMITTED,
            preferred_site=site,
            availability=Application.Availability.WEEKDAY_EVENINGS,
            consent_given_at=timezone.now(),
            submitted_at=timezone.now() - timedelta(days=11),
        )

    def test_01_alternatives_for_excludes_applied_and_ineligible(self):
        results = [study.title for study in alternatives_for(self.aisyah, self.s1)]
        self.assertEqual(results, ['Night Owls Study', 'Calm Minds Trial'])

    def test_02_alternatives_for_uses_ml1_then_deadline(self):
        results = [study.title for study in alternatives_for(self.aisyah, self.s3)]
        self.assertEqual(results, ['Night Owls Study', 'Sleep Habits Study'])

    def test_03_alternatives_for_limit_1_returns_single_study(self):
        results = [study.title for study in alternatives_for(self.aisyah, self.s1, limit=1)]
        self.assertEqual(results, ['Night Owls Study'])

    def test_04_popular_studies_ranks_recent_applications_before_old_and_newer_zero_activity(self):
        newer_zero = Study.objects.create(
            organisation=self.s1.organisation,
            category=self.s1.category,
            title='Newly Published No Activity Study',
            description='A newly published study with no recent applications.',
            study_type=Study.StudyType.OBSERVATIONAL,
            phase=Study.Phase.NOT_APPLICABLE,
            accepts_healthy_volunteers=True,
            sex_eligibility=Study.SexEligibility.ALL,
            min_age=21,
            max_age=70,
            smoker_rule=Study.SmokerRule.ANY,
            target_enrolment=40,
            total_visits=1,
            duration_weeks=4,
            visit_times=Study.VisitTimes.WEEKDAY_EVENINGS,
            compensation_amount='0.00',
            show_compensation=False,
            start_date=timezone.localdate(),
            recruitment_deadline=timezone.localdate() + timedelta(days=30),
            status=Study.Status.PUBLISHED,
            published_at=timezone.now() - timedelta(days=2),
        )
        newer_zero.sites.add(self.s1.sites.first())

        titles = list(popular_studies(limit=10).values_list('title', flat=True))
        self.assertEqual(titles[0], 'Calm Minds Trial')
        self.assertLess(titles.index('Newly Published No Activity Study'), titles.index('Sleep Habits Study'))

    def test_05_popular_studies_excludes_drafts(self):
        titles = list(popular_studies(limit=10).values_list('title', flat=True))
        self.assertNotIn('Draft Study', titles)
