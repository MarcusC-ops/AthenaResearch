import re

from django.core.management import call_command
from django.test import TestCase

from core.models import Condition, Organisation, PreScreenQuestion, Region, Site, Study, StudyCategory
from core.services import public_studies


class SeedDemoTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

    def test_01_seed_creates_expected_counts(self):
        call_command('seed_demo')
        self.assertEqual(Region.objects.count(), 5)
        self.assertEqual(Condition.objects.count(), 20)
        self.assertEqual(StudyCategory.objects.count(), 9)
        self.assertEqual(Organisation.objects.count(), 5)
        self.assertEqual(Site.objects.count(), 10)
        self.assertEqual(Study.objects.count(), 20)

    def test_02_second_seed_keeps_counts(self):
        call_command('seed_demo')
        call_command('seed_demo')
        self.assertEqual(Region.objects.count(), 5)
        self.assertEqual(Condition.objects.count(), 20)
        self.assertEqual(StudyCategory.objects.count(), 9)
        self.assertEqual(Organisation.objects.count(), 5)
        self.assertEqual(Site.objects.count(), 10)
        self.assertEqual(Study.objects.count(), 20)

    def test_03_public_studies_count_is_fifteen(self):
        call_command('seed_demo')
        self.assertEqual(public_studies().count(), 15)

    def test_04_studies_have_questions_and_visit_plan(self):
        call_command('seed_demo')
        for study in Study.objects.all():
            self.assertGreaterEqual(
                PreScreenQuestion.objects.filter(study=study).count(),
                2,
            )
            self.assertTrue(study.visit_plan)

    def test_05_study_text_has_no_payment_led_words(self):
        call_command('seed_demo')
        banned = re.compile(r'\b(?:earn|free|cash|easy money|guaranteed)\b', re.IGNORECASE)
        for study in Study.objects.all():
            self.assertIsNone(banned.search(study.title))
            self.assertIsNone(banned.search(study.description))

    def test_06_postal_codes_are_six_digits(self):
        call_command('seed_demo')
        for site in Site.objects.all():
            self.assertRegex(site.postal_code, r'^\d{6}$')
