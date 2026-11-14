from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from core.models import Organisation, Region, Site, Study, StudyCategory
from core.services import (
    get_public_study,
    get_study,
    list_active_categories,
    public_studies,
)


class CatalogueORMTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        region = Region.objects.create(code='W', name='West', display_order=5)
        sleep = StudyCategory.objects.create(
            name='Sleep',
            slug='sleep',
            ml_label='sleep',
            description='Explore sleep research.',
            display_order=8,
        )
        StudyCategory.objects.create(
            name='Cognitive',
            slug='cognitive',
            ml_label='cognitive',
            description='Explore cognitive research.',
            display_order=1,
            is_active=False,
        )
        organisation = Organisation.objects.create(
            name='Kent Ridge Clinical Research Centre',
            org_type=Organisation.OrganisationType.UNIVERSITY,
            contact_person='Daniel Lim',
            contact_email='drlim@example.sg',
        )
        site = Site.objects.create(
            organisation=organisation,
            name='Kent Ridge CRC, Lower Kent Ridge Clinic',
            address='21 Lower Kent Ridge Road',
            postal_code='119077',
            region=region,
        )
        published = timezone.now() - timedelta(days=2)
        study_defaults = {
            'organisation': organisation,
            'category': sleep,
            'description': 'A study about sleep habits.',
            'study_type': Study.StudyType.OBSERVATIONAL,
            'accepts_healthy_volunteers': True,
            'min_age': 21,
            'max_age': 65,
            'target_enrolment': 40,
            'total_visits': 4,
            'duration_weeks': 8,
            'visit_times': Study.VisitTimes.WEEKDAY_EVENINGS,
            'compensation_amount': '120.00',
            'show_compensation': True,
            'start_date': timezone.localdate(),
            'recruitment_deadline': timezone.localdate() + timedelta(days=30),
            'status': Study.Status.PUBLISHED,
            'published_at': published,
        }
        cls.study_1 = Study.objects.create(title='Sleep Habits Study', **study_defaults)
        cls.study_1.sites.add(site)
        cls.study_2 = Study.objects.create(
            title='Night Shift Sleep Study',
            published_at=published + timedelta(days=1),
            status=Study.Status.FULL,
            **{key: value for key, value in study_defaults.items() if key not in {'published_at', 'status'}},
        )
        cls.study_2.sites.add(site)
        cls.study_3 = Study.objects.create(
            title='Draft Diet Study',
            status=Study.Status.DRAFT,
            **{key: value for key, value in study_defaults.items() if key not in {'published_at', 'status'}},
        )
        cls.study_3.sites.add(site)
        cls.study_4 = Study.objects.create(
            title='Paused Study',
            status=Study.Status.PAUSED,
            **{key: value for key, value in study_defaults.items() if key not in {'published_at', 'status'}},
        )
        cls.study_4.sites.add(site)

    def test_01_get_public_study_returns_published_study(self):
        self.assertEqual(get_public_study('sleep-habits-study').title, 'Sleep Habits Study')

    def test_02_get_public_study_unknown_slug_raises(self):
        with self.assertRaises(Study.DoesNotExist):
            get_public_study('does-not-exist')

    def test_03_get_public_study_draft_raises(self):
        with self.assertRaises(Study.DoesNotExist):
            get_public_study('draft-diet-study')

    def test_04_public_studies_are_newest_first(self):
        self.assertEqual(
            list(public_studies().values_list('title', flat=True)),
            ['Night Shift Sleep Study', 'Sleep Habits Study'],
        )

    def test_05_duplicate_title_gets_numbered_slug(self):
        duplicate = Study.objects.create(
            title='Sleep Habits Study',
            **{
                key: value
                for key, value in self.study_1.__dict__.items()
                if key in {
                    'organisation_id', 'category_id', 'description', 'study_type',
                    'phase', 'accepts_healthy_volunteers', 'sex_eligibility', 'min_age',
                    'max_age', 'min_bmi', 'max_bmi', 'smoker_rule', 'target_enrolment',
                    'total_visits', 'duration_weeks', 'visit_times', 'compensation_amount',
                    'show_compensation', 'start_date', 'recruitment_deadline', 'irb_name',
                    'irb_reference', 'irb_expiry', 'irb_approved_text', 'status',
                    'auto_shortlist_high', 'moderation_comments', 'paused_reason',
                    'submitted_at', 'published_at', 'created_by_id', 'last_edited_by_id',
                    'reviewed_by_id',
                }
            },
        )
        self.assertEqual(duplicate.slug, 'sleep-habits-study-2')

    def test_06_changing_title_does_not_change_slug(self):
        self.study_1.title = 'Changed Sleep Habits Study'
        self.study_1.save()
        self.study_1.refresh_from_db()
        self.assertEqual(self.study_1.slug, 'sleep-habits-study')

    def test_07_get_study_returns_draft(self):
        self.assertEqual(get_study(self.study_3.id).title, 'Draft Diet Study')

    def test_08_list_active_categories_returns_sleep_only(self):
        self.assertEqual(list(list_active_categories().values_list('name', flat=True)), ['Sleep'])
