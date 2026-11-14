from django.contrib.auth.models import Group, User
from django.test import TestCase

from core.models import Organisation, ParticipantProfile, StaffProfile


class SignInViewTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        organisation = Organisation.objects.create(
            name='Kent Ridge Clinical Research Centre',
            org_type=Organisation.OrganisationType.UNIVERSITY,
            contact_person='Daniel Lim',
            contact_email='drlim@kentridge-crc.sg',
        )
        cls.aisyah = User.objects.create_user(
            username='aisyah@example.com',
            email='aisyah@example.com',
            first_name='Aisyah',
            last_name='Rahman',
            password='Kopi-Teh-2026!',
            is_active=True,
        )
        cls.aisyah.groups.add(Group.objects.get(name='Participant'))
        ParticipantProfile.objects.create(
            user=cls.aisyah,
            mobile='+6591234567',
            terms_accepted_at=cls.aisyah.date_joined,
        )
        cls.nurul = User.objects.create_user(
            username='nurul@harbourfront.sg',
            email='nurul@harbourfront.sg',
            first_name='Nurul',
            last_name='Huda',
            password='Kopi-Teh-2026!',
            is_active=False,
        )
        cls.nurul.groups.add(Group.objects.get(name='Coordinator'))
        StaffProfile.objects.create(
            user=cls.nurul,
            mobile='+6591234567',
        )
        cls.daniel = User.objects.create_user(
            username='drlim@kentridge-crc.sg',
            email='drlim@kentridge-crc.sg',
            first_name='Daniel',
            last_name='Lim',
            password='Kopi-Teh-2026!',
            is_active=True,
        )
        cls.daniel.groups.add(Group.objects.get(name='Coordinator'))
        StaffProfile.objects.create(
            user=cls.daniel,
            organisation=organisation,
            job_title='Clinical research coordinator',
            mobile='+6591234567',
        )
        cls.priya = User.objects.create_user(
            username='priya@athena.sg',
            email='priya@athena.sg',
            first_name='Priya',
            last_name='Nair',
            password='Kopi-Teh-2026!',
            is_active=True,
        )
        cls.priya.groups.add(Group.objects.get(name='Staff'))

    def test_01_participant_sign_in_redirects_to_profile(self):
        response = self.client.post(
            '/accounts/login/',
            {'email': 'aisyah@example.com', 'password': 'Kopi-Teh-2026!'},
        )
        self.assertRedirects(response, '/account/')

    def test_02_wrong_password_shows_error(self):
        response = self.client.post(
            '/accounts/login/',
            {'email': 'aisyah@example.com', 'password': 'wrong'},
        )
        self.assertContains(response, 'Email or password is incorrect.')

    def test_03_inactive_researcher_shows_waiting_message(self):
        response = self.client.post(
            '/accounts/login/',
            {'email': 'nurul@harbourfront.sg', 'password': 'Kopi-Teh-2026!'},
        )
        self.assertContains(response, 'waiting for approval')

    def test_04_signed_out_panel_redirects_to_panel_login(self):
        response = self.client.get('/panel/')
        self.assertRedirects(response, '/panel/login/?next=/panel/')

    def test_05_participant_cannot_open_panel_notifications(self):
        self.client.force_login(self.aisyah)
        response = self.client.get('/panel/notifications/')
        self.assertEqual(response.status_code, 403)

    def test_06_coordinator_panel_sign_in_and_header(self):
        response = self.client.post(
            '/panel/login/',
            {'email': 'drlim@kentridge-crc.sg', 'password': 'Kopi-Teh-2026!'},
        )
        self.assertRedirects(response, '/panel/')
        response = self.client.get('/panel/')
        self.assertContains(response, 'Daniel Lim')

    def test_07_participant_is_refused_panel_sign_in(self):
        response = self.client.post(
            '/panel/login/',
            {'email': 'aisyah@example.com', 'password': 'Kopi-Teh-2026!'},
        )
        self.assertContains(
            response, 'This sign-in is for research teams and Athena staff.'
        )
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_08_panel_login_is_open_signed_out(self):
        response = self.client.get('/panel/login/')
        self.assertEqual(response.status_code, 200)

    def test_09_sign_out_is_post_only(self):
        self.client.force_login(self.aisyah)
        response = self.client.get('/accounts/logout/')
        self.assertEqual(response.status_code, 405)
        response = self.client.post('/accounts/logout/')
        self.assertRedirects(response, '/')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_10_django_admin_is_not_installed(self):
        response = self.client.get('/admin/')
        self.assertEqual(response.status_code, 404)
