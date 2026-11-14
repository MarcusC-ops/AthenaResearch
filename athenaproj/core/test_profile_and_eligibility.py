from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.utils import timezone

from .models import (
    Condition,
    Organisation,
    ParticipantProfile,
    Region,
    Site,
    Study,
    StudyCategory,
)
from .services import check_eligibility, eligible_studies, is_eligible


class ProfileAndEligibilityTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.region_w = Region.objects.create(code='W', name='West', display_order=1)
        cls.region_c = Region.objects.create(code='C', name='Central', display_order=2)
        cls.asthma = Condition.objects.create(name='Asthma', ml_flag='respiratory')
        cls.insomnia = Condition.objects.create(name='Insomnia', ml_flag='sleep')
        cls.category = StudyCategory.objects.create(
            name='Sleep', slug='sleep', ml_label='sleep',
            description='Sleep research.', display_order=1,
        )
        cls.organisation = Organisation.objects.create(
            name='Test Organisation', org_type='university',
            contact_person='Test Contact', contact_email='test@example.com',
        )
        cls.site = Site.objects.create(
            organisation=cls.organisation, name='West Site',
            address='1 West Road', postal_code='123456', region=cls.region_w,
        )
        cls.user = User.objects.create_user(
            username='aisyah@example.com', email='aisyah@example.com',
            first_name='Aisyah', last_name='Rahman',
        )
        cls.user.groups.add(Group.objects.get(name='Participant'))
        cls.profile = ParticipantProfile.objects.create(
            user=cls.user, mobile='+6591234567',
            terms_accepted_at=timezone.now(),
            date_of_birth=date.today().replace(year=date.today().year - 30),
            sex='female', region=cls.region_w, employment='student',
            education='degree', height_cm='160.0', weight_kg='55.0',
            smoker=False, activity_level='low', motivation='help_research',
            availability='weekday_evenings', max_travel_minutes='30',
            onboarding_completed_at=timezone.now(),
        )
        cls.profile.conditions.add(cls.asthma)

        cls.studies = {}
        for key, title in (
            ('A', 'Sleep Habits Study'),
            ('B', 'Midlife Heart Study'),
            ('C', "Men's Health Study"),
            ('D', 'Asthma Inhaler Trial'),
            ('E', 'Calm Sleep Study'),
            ('F', 'Central Region Study'),
            ('G', 'Higher BMI Study'),
            ('H', 'Smokers Study'),
            ('I', 'Draft Study'),
        ):
            cls.studies[key] = Study.objects.create(
                organisation=cls.organisation, category=cls.category,
                title=title, description='A study.', study_type='observational',
                accepts_healthy_volunteers=True, min_age=21, max_age=65,
                target_enrolment=10, total_visits=1, duration_weeks=1,
                visit_times='flexible', compensation_amount='10.00',
                show_compensation=True, start_date=date.today(),
                recruitment_deadline=date.today() + timedelta(days=30),
                status='draft' if key == 'I' else 'published',
                published_at=timezone.now() if key != 'I' else None,
            )
        cls.studies['B'].min_age = 40
        cls.studies['B'].save()
        cls.studies['C'].sex_eligibility = 'male'
        cls.studies['C'].save()
        cls.studies['D'].accepts_healthy_volunteers = False
        cls.studies['D'].save()
        cls.studies['D'].required_conditions.add(cls.asthma)
        cls.studies['E'].excluded_conditions.add(cls.asthma)
        cls.studies['F'].regions.add(cls.region_c)
        cls.studies['G'].min_bmi = Decimal('25.0')
        cls.studies['G'].max_bmi = Decimal('35.0')
        cls.studies['G'].save()
        cls.studies['H'].smoker_rule = 'smokers'
        cls.studies['H'].save()
        cls.studies['I'].sites.add(cls.site)

    def test_01_profile_bmi_and_age(self):
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.bmi, Decimal('21.5'))
        self.assertEqual(self.profile.age, 30)

    def test_02_all_applicable_rules_for_a(self):
        results = check_eligibility(self.profile, self.studies['A'])
        self.assertEqual([result.code for result in results], ['age', 'sex', 'health', 'smoking'])
        self.assertTrue(all(result.met for result in results))

    def test_03_age_rule_for_b(self):
        results = check_eligibility(self.profile, self.studies['B'])
        age = next(result for result in results if result.code == 'age')
        self.assertFalse(age.met)
        self.assertIn('Ages 40 to 65', age.detail)
        self.assertIn('you are 30', age.detail)

    def test_04_sex_rule_for_c(self):
        sex = next(result for result in check_eligibility(self.profile, self.studies['C']) if result.code == 'sex')
        self.assertFalse(sex.met)

    def test_05_required_condition_and_health_for_d(self):
        self.assertTrue(is_eligible(self.profile, self.studies['D']))
        self.profile.conditions.remove(self.asthma)
        results = check_eligibility(self.profile, self.studies['D'])
        self.assertFalse(next(result for result in results if result.code == 'health').met)
        self.assertFalse(next(result for result in results if result.code == 'required_conditions').met)

    def test_06_excluded_condition_for_e(self):
        excluded = next(result for result in check_eligibility(self.profile, self.studies['E']) if result.code == 'excluded_conditions')
        self.assertFalse(excluded.met)

    def test_07_region_for_f(self):
        region = next(result for result in check_eligibility(self.profile, self.studies['F']) if result.code == 'region')
        self.assertFalse(region.met)

    def test_08_bmi_boundaries_for_g(self):
        bmi = next(result for result in check_eligibility(self.profile, self.studies['G']) if result.code == 'bmi')
        self.assertFalse(bmi.met)
        self.profile.weight_kg = Decimal('64.0')
        self.profile.save()
        self.profile.refresh_from_db()
        bmi = next(result for result in check_eligibility(self.profile, self.studies['G']) if result.code == 'bmi')
        self.assertTrue(bmi.met)

    def test_09_smoking_for_h(self):
        smoking = next(result for result in check_eligibility(self.profile, self.studies['H']) if result.code == 'smoking')
        self.assertFalse(smoking.met)

    def test_10_eligible_studies(self):
        self.profile.refresh_from_db()
        self.assertEqual(
            {study.title for study in eligible_studies(self.profile)},
            {'Sleep Habits Study', 'Asthma Inhaler Trial'},
        )
