from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.utils import timezone

from core.models import (
    Application,
    Organisation,
    ParticipantProfile,
    Region,
    Site,
    StaffProfile,
    Study,
    StudyCategory,
)
from core.services import (
    age_band,
    applicant_queue,
    change_status,
    identity_unlocked,
    shortlist_applicant,
)


class ApplicantQueueTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.region = Region.objects.create(code='W', name='West', display_order=5)
        cls.category = StudyCategory.objects.create(
            name='Healthy Volunteer Phase I',
            slug='healthy-volunteer-phase-1',
            ml_label='healthy_phase1',
            description='Explore healthy volunteer studies.',
            display_order=2,
        )
        cls.kent_ridge = Organisation.objects.create(
            name='Kent Ridge Clinical Research Centre',
            org_type=Organisation.OrganisationType.UNIVERSITY,
            contact_person='Daniel Lim',
            contact_email='drlim@kentridge-crc.sg',
        )
        cls.harbourfront = Organisation.objects.create(
            name='Harbourfront General Hospital',
            org_type=Organisation.OrganisationType.HOSPITAL,
            contact_person='Nurul Huda',
            contact_email='nurul@harbourfront.sg',
        )
        cls.site = Site.objects.create(
            organisation=cls.kent_ridge,
            name='K1',
            address='21 Lower Kent Ridge Road',
            postal_code='119077',
            region=cls.region,
        )
        coordinator_group = Group.objects.get(name='Coordinator')
        cls.drlim = User.objects.create_user(
            username='drlim@kentridge-crc.sg',
            email='drlim@kentridge-crc.sg',
            first_name='Daniel',
            last_name='Lim',
            password='Kopi-Teh-2026!',
        )
        cls.drlim.groups.add(coordinator_group)
        StaffProfile.objects.create(
            user=cls.drlim,
            organisation=cls.kent_ridge,
            mobile='+6591234567',
        )
        cls.nurul = User.objects.create_user(
            username='nurul@harbourfront.sg',
            email='nurul@harbourfront.sg',
            first_name='Nurul',
            last_name='Huda',
            password='Kopi-Teh-2026!',
            is_active=True,
        )
        cls.nurul.groups.add(coordinator_group)
        StaffProfile.objects.create(
            user=cls.nurul,
            organisation=cls.harbourfront,
            mobile='+6591234568',
        )
        today = timezone.localdate()
        cls.study = Study.objects.create(
            organisation=cls.kent_ridge,
            category=cls.category,
            title='Flu Vaccine Exercise Study',
            description='A study about exercise and flu vaccines.',
            study_type=Study.StudyType.INTERVENTIONAL,
            accepts_healthy_volunteers=True,
            min_age=21,
            max_age=65,
            target_enrolment=40,
            total_visits=1,
            duration_weeks=4,
            visit_times=Study.VisitTimes.FLEXIBLE,
            compensation_amount=Decimal('100.00'),
            show_compensation=True,
            start_date=today,
            recruitment_deadline=today + timedelta(days=30),
            status=Study.Status.PUBLISHED,
        )
        cls.study.sites.add(cls.site)

        people = (
            ('alice', 'Alice', 'Tan', 34, 0.55, Application.Band.MEDIUM),
            ('ben', 'Ben', 'Lee', 52, 0.82, Application.Band.HIGH),
            ('chloe', 'Chloe', 'Ng', 27, 0.20, Application.Band.LOW),
            ('dan', 'Dan', 'Koh', 40, None, Application.Band.UNSCORED),
            ('eve', 'Eve', 'Lim', 31, None, Application.Band.UNSCORED),
        )
        submitted_at = timezone.now() - timedelta(days=5)
        participant_group = Group.objects.get(name='Participant')
        cls.participant_emails = []
        for index, (key, first_name, last_name, age, probability, band) in enumerate(people):
            email = f'{key}@example.com'
            cls.participant_emails.append(email)
            user = User.objects.create_user(
                username=email,
                email=email,
                first_name=first_name,
                last_name=last_name,
                password='Kopi-Teh-2026!',
            )
            user.groups.add(participant_group)
            profile = ParticipantProfile.objects.create(
                user=user,
                mobile='+6591234569',
                terms_accepted_at=submitted_at,
                date_of_birth=date(today.year - age, 1, 1),
                sex=(
                    ParticipantProfile.Sex.MALE
                    if key in ('ben', 'dan') else ParticipantProfile.Sex.FEMALE
                ),
                region=cls.region,
            )
            application = Application.objects.create(
                participant=profile,
                study=cls.study,
                preferred_site=cls.site,
                availability=Application.Availability.FLEXIBLE,
                consent_given_at=submitted_at,
                submitted_at=submitted_at + timedelta(minutes=index),
                ml2_probability=probability,
                ml2_band=band,
            )
            change_status(
                application,
                Application.Status.AUTO_DECLINED
                if key == 'eve' else Application.Status.UNDER_REVIEW,
            )
            setattr(cls, key, application)

    def setUp(self):
        self.study.refresh_from_db()
        self.drlim.refresh_from_db()
        self.nurul.refresh_from_db()
        for application in (self.alice, self.ben, self.chloe, self.dan, self.eve):
            application.refresh_from_db()
        self.client.force_login(self.drlim)
        self.url = f'/panel/studies/{self.study.pk}/applicants/'

    def test_01_queue_ranks_bands_and_excludes_auto_declined(self):
        self.assertEqual(
            list(applicant_queue(self.study)),
            [self.ben, self.alice, self.chloe, self.dan],
        )
        self.assertNotIn(self.eve, applicant_queue(self.study))

    def test_02_equal_high_probabilities_order_by_submission_date(self):
        self.alice.ml2_band = Application.Band.HIGH
        self.alice.ml2_probability = 0.82
        self.alice.save(update_fields=['ml2_band', 'ml2_probability'])
        self.alice.refresh_from_db()
        self.ben.refresh_from_db()
        self.assertLess(self.alice.submitted_at, self.ben.submitted_at)
        self.assertEqual(
            list(applicant_queue(self.study))[:2],
            [self.alice, self.ben],
        )

    def test_03_age_band_boundaries(self):
        self.assertEqual(age_band(29), '21 to 29')
        self.assertEqual(age_band(30), '30 to 39')
        self.assertEqual(age_band(60), '60 and over')

    def test_04_page_displays_priorities_in_ranked_order(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        labels = ('High · 82%', 'Medium · 55%', 'Low · 20%', 'Unscored')
        for label in labels:
            self.assertContains(response, label)
        table = content.split('<tbody>', 1)[1]
        positions = [table.index(label) for label in labels]
        self.assertEqual(positions, sorted(positions))

    def test_05_unshortlisted_identities_are_hidden(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        for application in (self.alice, self.ben, self.chloe, self.dan):
            self.assertContains(response, application.reference)
        self.assertContains(response, '30 to 39')
        self.assertNotContains(response, 'Alice')
        self.assertNotContains(response, 'Ben Lee')
        for email in self.participant_emails:
            self.assertNotContains(response, email)

    def test_06_shortlisting_unlocks_identity(self):
        self.ben.refresh_from_db()
        self.assertFalse(identity_unlocked(self.ben))
        shortlist_applicant(self.ben, self.drlim)
        self.ben.refresh_from_db()
        self.assertTrue(identity_unlocked(self.ben))
        response = self.client.get(self.url)
        self.assertContains(response, 'Ben Lee')

    def test_07_low_band_filter_lists_only_chloe(self):
        response = self.client.get(self.url, {'band': 'low'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.chloe.reference)
        for application in (self.alice, self.ben, self.dan, self.eve):
            self.assertNotContains(response, application.reference)
        self.assertEqual(
            [application.pk for application in response.context['applications']],
            [self.chloe.pk],
        )

    def test_08_other_organisation_coordinator_receives_404(self):
        self.client.force_login(self.nurul)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 404)

    def test_09_page_says_model_never_declines_anyone(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'It never declines anyone.')
