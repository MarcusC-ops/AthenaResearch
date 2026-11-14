from datetime import timedelta

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from core.models import (
    Organisation,
    ParticipantProfile,
    Region,
    Shortlist,
    Site,
    Study,
    StudyCategory,
)
from core.services import (
    add_to_shortlist,
    compare_studies,
    remove_from_shortlist,
    shortlist_count,
)


class ShortlistORMTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        region = Region.objects.create(code='W', name='West', display_order=1)
        category = StudyCategory.objects.create(
            name='Sleep',
            slug='sleep',
            ml_label='sleep',
            description='Explore sleep research.',
            display_order=1,
        )
        organisation = Organisation.objects.create(
            name='Kent Ridge Clinical Research Centre',
            org_type=Organisation.OrganisationType.UNIVERSITY,
            contact_person='Daniel Lim',
            contact_email='drlim@example.sg',
        )
        site = Site.objects.create(
            organisation=organisation,
            name='Kent Ridge CRC',
            address='21 Lower Kent Ridge Road',
            postal_code='119077',
            region=region,
        )
        study_defaults = {
            'organisation': organisation,
            'category': category,
            'description': 'A plain-language study about health.',
            'study_type': Study.StudyType.OBSERVATIONAL,
            'accepts_healthy_volunteers': True,
            'min_age': 21,
            'max_age': 65,
            'target_enrolment': 30,
            'total_visits': 2,
            'duration_weeks': 8,
            'visit_times': Study.VisitTimes.FLEXIBLE,
            'compensation_amount': '100.00',
            'show_compensation': True,
            'start_date': timezone.localdate(),
            'recruitment_deadline': timezone.localdate() + timedelta(days=30),
            'status': Study.Status.PUBLISHED,
            'published_at': timezone.now(),
        }
        cls.studies = []
        for title in (
            'Sleep Habits Study',
            'Calm Minds Trial',
            'Midlife Heart Study',
            'Asthma Inhaler Trial',
        ):
            study = Study.objects.create(title=title, **study_defaults)
            study.sites.add(site)
            cls.studies.append(study)
        draft = Study.objects.create(
            title='Draft Diet Study',
            status=Study.Status.DRAFT,
            published_at=None,
            **{
                key: value
                for key, value in study_defaults.items()
                if key not in {'status', 'published_at'}
            },
        )
        draft.sites.add(site)
        cls.draft = draft

        cls.aisyah_user = User.objects.create_user(
            username='aisyah@example.com',
            email='aisyah@example.com',
            first_name='Aisyah',
            password='Kopi-Teh-2026!',
        )
        cls.aisyah_user.groups.add(
            cls.aisyah_user.groups.model.objects.get(name='Participant')
        )
        cls.aisyah = ParticipantProfile.objects.create(
            user=cls.aisyah_user,
            mobile='+6591234567',
            terms_accepted_at=timezone.now(),
            onboarding_completed_at=timezone.now(),
            date_of_birth=timezone.localdate().replace(
                year=timezone.localdate().year - 30
            ),
            sex=ParticipantProfile.Sex.FEMALE,
            region=region,
            height_cm='165.0',
            weight_kg='60.0',
        )
        cls.ben_user = User.objects.create_user(
            username='ben@example.com',
            email='ben@example.com',
            first_name='Ben',
            password='Kopi-Teh-2026!',
        )
        cls.ben_user.groups.add(
            cls.ben_user.groups.model.objects.get(name='Participant')
        )
        cls.ben = ParticipantProfile.objects.create(
            user=cls.ben_user,
            mobile='+6581234567',
            terms_accepted_at=timezone.now(),
            onboarding_completed_at=timezone.now(),
            date_of_birth=timezone.localdate().replace(
                year=timezone.localdate().year - 30
            ),
            sex=ParticipantProfile.Sex.MALE,
            region=region,
            height_cm='175.0',
            weight_kg='70.0',
        )
        Shortlist.objects.bulk_create([
            Shortlist(participant=cls.aisyah, study=cls.studies[1]),
            Shortlist(participant=cls.aisyah, study=cls.studies[2]),
            Shortlist(participant=cls.aisyah, study=cls.studies[3]),
        ])

    def test_01_adds_new_study(self):
        _, created = add_to_shortlist(self.aisyah, self.studies[0].id)
        self.assertTrue(created)
        self.assertEqual(shortlist_count(self.aisyah), 4)

    def test_02_adds_existing_study_without_duplication(self):
        _, created = add_to_shortlist(self.aisyah, self.studies[1].id)
        self.assertFalse(created)
        self.assertEqual(shortlist_count(self.aisyah), 3)

    def test_03_database_rejects_duplicate_shortlist(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Shortlist.objects.create(
                    participant=self.aisyah,
                    study=self.studies[1],
                )

    def test_04_does_not_add_draft_study(self):
        with self.assertRaises(Study.DoesNotExist):
            add_to_shortlist(self.aisyah, self.draft.id)

    def test_05_removes_study_and_is_idempotent(self):
        self.assertTrue(remove_from_shortlist(self.aisyah, self.studies[1].id))
        self.assertEqual(shortlist_count(self.aisyah), 2)
        self.assertFalse(remove_from_shortlist(self.aisyah, self.studies[1].id))

    def test_06_rejects_invalid_compare_sizes(self):
        with self.assertRaises(ValueError):
            compare_studies(self.aisyah, [self.studies[1].id])
        add_to_shortlist(self.aisyah, self.studies[0].id)
        with self.assertRaises(ValueError):
            compare_studies(
                self.aisyah,
                [study.id for study in self.studies],
            )

    def test_07_compares_studies_in_requested_order(self):
        compared = compare_studies(
            self.aisyah,
            [self.studies[2].id, self.studies[1].id],
        )
        self.assertEqual(
            [study.title for study in compared],
            ['Midlife Heart Study', 'Calm Minds Trial'],
        )

    def test_08_rejects_duplicate_compare_ids(self):
        with self.assertRaises(ValueError):
            compare_studies(self.aisyah, [self.studies[1].id, self.studies[1].id])

    def test_09_rejects_studies_not_on_participant_shortlist(self):
        with self.assertRaises(ValueError):
            compare_studies(
                self.ben,
                [self.studies[1].id, self.studies[2].id],
            )
