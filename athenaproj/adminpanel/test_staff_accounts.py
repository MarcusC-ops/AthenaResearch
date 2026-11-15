from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase

from core.models import Organisation, Region, StaffProfile
from core.services import add_staff_account, set_staff_active, set_staff_role
from adminpanel.forms import StaffAccountForm


class StaffAccountTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.password = 'Kopi-Teh-2026!'
        cls.admin = cls.make_user('admin@athena.sg', 'Wei Ling', 'Tan', 'Admin')
        cls.staff = cls.make_user('priya@athena.sg', 'Priya', 'Nair', 'Staff')
        cls.region = Region.objects.create(code='W', name='West', display_order=5)

    @classmethod
    def make_user(cls, email, first_name, last_name, group_name):
        user = User.objects.create_user(
            username=email,
            email=email,
            first_name=first_name,
            last_name=last_name,
            password=cls.password,
        )
        user.groups.add(Group.objects.get(name=group_name))
        StaffProfile.objects.create(
            user=user,
            organisation=None,
            job_title='Platform staff',
            mobile='+6591234567',
        )
        return user

    def test_01_last_admin_cannot_be_demoted(self):
        with self.assertRaisesMessage(
            ValidationError,
            'There must always be at least one active admin.',
        ):
            set_staff_role(self.admin, 'staff', self.admin)
        self.assertTrue(self.admin.groups.filter(name='Admin').exists())

    def test_02_staff_can_be_promoted_to_admin(self):
        set_staff_role(self.staff, 'admin', self.admin)
        self.assertTrue(self.staff.groups.filter(name='Admin').exists())
        self.assertTrue(self.staff.has_perm('core.admin_access'))

    def test_03_original_admin_can_be_demoted_after_promotion(self):
        set_staff_role(self.staff, 'admin', self.admin)
        set_staff_role(self.admin, 'staff', self.staff)
        self.assertTrue(self.admin.groups.filter(name='Staff').exists())

    def test_04_admin_cannot_switch_off_own_account(self):
        with self.assertRaisesMessage(
            ValidationError,
            'You cannot switch off your own account.',
        ):
            set_staff_active(self.staff, False, self.staff)

    def test_05_add_staff_account_creates_sign_in_account(self):
        form = StaffAccountForm({
            'first_name': 'Operations',
            'last_name': 'Two',
            'email': 'ops2@athena.sg',
            'role': 'staff',
            'job_title': 'Operations executive',
            'mobile': '91234567',
            'temporary_password': self.password,
        })
        self.assertTrue(form.is_valid(), form.errors)
        user = add_staff_account(form, self.admin)
        self.assertTrue(user.is_active)
        self.assertTrue(user.groups.filter(name='Staff').exists())
        self.assertIsNone(user.staff_profile.organisation)
        self.assertTrue(self.client.login(
            username='ops2@athena.sg',
            password=self.password,
        ))

    def test_06_weak_password_creates_no_user(self):
        form = StaffAccountForm({
            'first_name': 'Operations',
            'last_name': 'Two',
            'email': 'ops2@athena.sg',
            'role': 'staff',
            'job_title': '',
            'mobile': '91234567',
            'temporary_password': '123',
        })
        self.assertTrue(form.is_valid(), form.errors)
        with self.assertRaises(ValidationError):
            add_staff_account(form, self.admin)
        self.assertFalse(User.objects.filter(username='ops2@athena.sg').exists())

    def test_07_staff_cannot_open_staff_accounts_page(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get('/panel/staff/').status_code, 403)

    def test_08_demo_data_post_loads_counts_but_get_does_not_run_it(self):
        self.client.force_login(self.admin)
        response = self.client.post('/panel/demo-data/', follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Regions: 5')
        region_count = Region.objects.count()
        self.assertEqual(region_count, 5)
        response = self.client.get('/panel/demo-data/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Region.objects.count(), region_count)
