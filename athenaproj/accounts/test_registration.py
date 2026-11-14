from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError
from django.test import TestCase

from core.models import Organisation, ParticipantProfile, StaffProfile
from core.services import (
    mark_all_read,
    notify_users,
    register_participant,
    register_researcher,
    unread_count,
    user_role,
)
from core.validators import normalise_sg_mobile


class RegistrationTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.organisation = Organisation.objects.create(
            name='Kent Ridge Clinical Research Centre',
            org_type=Organisation.OrganisationType.UNIVERSITY,
            contact_person='Daniel Lim',
            contact_email='drlim@kentridge-crc.sg',
        )
        cls.priya = User.objects.create_user(
            username='priya@athena.sg',
            email='priya@athena.sg',
            password='Kopi-Teh-2026!',
            is_active=True,
        )
        cls.priya.groups.add(Group.objects.get(name='Staff'))
        cls.admin = User.objects.create_user(
            username='admin@athena.sg',
            email='admin@athena.sg',
            password='Kopi-Teh-2026!',
            is_active=True,
        )
        cls.admin.groups.add(Group.objects.get(name='Admin'))

    def test_01_register_participant(self):
        user = register_participant(
            'Aisyah', 'Rahman', 'aisyah@example.com', '9123 4567',
            'Kopi-Teh-2026!',
        )
        user.refresh_from_db()
        profile = user.participant_profile
        self.assertTrue(user.is_active)
        self.assertTrue(user.groups.filter(name='Participant').exists())
        self.assertEqual(profile.mobile, '+6591234567')
        self.assertIsNotNone(profile.terms_accepted_at)

    def test_02_normalise_mobile_with_country_code(self):
        self.assertEqual(normalise_sg_mobile('+65 8123 4567'), '+6581234567')

    def test_03_reject_non_singapore_mobile(self):
        with self.assertRaises(ValidationError):
            normalise_sg_mobile('6123 4567')

    def test_04_reject_seven_digit_mobile(self):
        with self.assertRaises(ValidationError):
            normalise_sg_mobile('9123 456')

    def test_05_reject_duplicate_email_case_insensitively(self):
        register_participant(
            'Aisyah', 'Rahman', 'aisyah@example.com', '9123 4567',
            'Kopi-Teh-2026!',
        )
        with self.assertRaises(ValidationError):
            register_participant(
                'Aisyah', 'Rahman', 'AISYAH@example.com', '9123 4567',
                'Kopi-Teh-2026!',
            )
        self.assertEqual(
            User.objects.filter(username='aisyah@example.com').count(), 1
        )

    def test_06_reject_common_password_without_creating_user(self):
        with self.assertRaises(ValidationError):
            register_participant(
                'Aisyah', 'Rahman', 'aisyah@example.com', '9123 4567',
                'password',
            )
        self.assertFalse(User.objects.filter(username='aisyah@example.com').exists())

    def test_07_register_researcher(self):
        user = register_researcher(
            'Daniel', 'Lim', 'drlim@kentridge-crc.sg', self.organisation.id,
            'Clinical research coordinator', '9123 4567', 'Kopi-Teh-2026!',
        )
        user.refresh_from_db()
        profile = user.staff_profile
        self.assertFalse(user.is_active)
        self.assertTrue(user.groups.filter(name='Coordinator').exists())
        self.assertEqual(profile.organisation, self.organisation)

    def test_08_researcher_registration_notifies_staff_and_admin(self):
        register_researcher(
            'Daniel', 'Lim', 'drlim@kentridge-crc.sg', self.organisation.id,
            'Clinical research coordinator', '9123 4567', 'Kopi-Teh-2026!',
        )
        for user in (self.priya, self.admin):
            user.refresh_from_db()
            notifications = user.notifications.filter(is_read=False)
            self.assertEqual(notifications.count(), 1)
            self.assertIn('Daniel Lim', notifications.first().message)

    def test_09_mark_all_read_only_affects_selected_user(self):
        register_researcher(
            'Daniel', 'Lim', 'drlim@kentridge-crc.sg', self.organisation.id,
            'Clinical research coordinator', '9123 4567', 'Kopi-Teh-2026!',
        )
        mark_all_read(self.priya)
        self.assertEqual(unread_count(self.priya), 0)
        self.assertEqual(unread_count(self.admin), 1)

    def test_10_user_role_returns_each_role(self):
        participant = User.objects.create_user(
            username='participant@example.com', password='Kopi-Teh-2026!'
        )
        participant.groups.add(Group.objects.get(name='Participant'))
        coordinator = User.objects.create_user(
            username='coordinator@example.com', password='Kopi-Teh-2026!'
        )
        coordinator.groups.add(Group.objects.get(name='Coordinator'))
        self.assertEqual(user_role(participant), 'participant')
        self.assertEqual(user_role(coordinator), 'coordinator')
        self.assertEqual(user_role(self.priya), 'staff')
        self.assertEqual(user_role(self.admin), 'admin')
