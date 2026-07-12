from rest_framework import status
from rest_framework.test import APITestCase
from django.core import mail
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.contrib.auth.tokens import default_token_generator

from tenants.models import Organization
from users.models import User


class RegisterViewTests(APITestCase):
    def test_register_rejects_duplicate_email_case_insensitive(self):
        organization = Organization.objects.create(name='Existing Org')
        User.objects.create_user(
            email='Admin@Example.com',
            password='StrongPass123!',
            organization=organization,
            role=User.ROLE_ADMIN,
        )

        response = self.client.post(
            '/api/v1/auth/register/',
            {
                'email': 'admin@example.com',
                'password': 'StrongPass123!',
                'organization_name': 'New Org',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('email', response.data)


class AuthMeViewTests(APITestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name='Org Before')
        self.user = User.objects.create_user(
            email='admin@example.com',
            password='StrongPass123!',
            organization=self.organization,
            role=User.ROLE_ADMIN,
        )
        self.client.force_authenticate(self.user)

    def test_patch_me_updates_password_and_organization(self):
        response = self.client.patch(
            '/api/v1/auth/me/',
            {
                'organization_name': 'Org After',
                'new_password': 'EvenStronger123!',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.organization.refresh_from_db()
        self.user.refresh_from_db()
        self.assertEqual(self.organization.name, 'Org After')
        self.assertTrue(self.user.check_password('EvenStronger123!'))

    def test_patch_me_rejects_empty_payload(self):
        response = self.client.patch('/api/v1/auth/me/', {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_delete_organization_removes_current_organization(self):
        response = self.client.delete('/api/v1/auth/delete-organization/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(Organization.objects.filter(id=self.organization.id).exists())
        self.assertFalse(User.objects.filter(id=self.user.id).exists())

    def test_member_can_update_own_password(self):
        self.user.role = User.ROLE_MEMBER
        self.user.save(update_fields=['role'])

        response = self.client.patch(
            '/api/v1/auth/me/',
            {'new_password': 'MemberStrong123!'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('MemberStrong123!'))

    def test_member_cannot_update_organization_settings(self):
        self.user.role = User.ROLE_MEMBER
        self.user.save(update_fields=['role'])

        response = self.client.patch(
            '/api/v1/auth/me/',
            {'organization_name': 'Member Rename Attempt'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.organization.refresh_from_db()
        self.assertEqual(self.organization.name, 'Org Before')

    def test_member_cannot_delete_organization(self):
        self.user.role = User.ROLE_MEMBER
        self.user.save(update_fields=['role'])

        response = self.client.delete('/api/v1/auth/delete-organization/')

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(Organization.objects.filter(id=self.organization.id).exists())
        self.assertTrue(User.objects.filter(id=self.user.id).exists())


class SecurityHardeningTests(APITestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name='Security Org')

    def test_password_complexity_validator(self):
        # Register with simple password (missing special char and digit)
        response = self.client.post(
            '/api/v1/auth/register/',
            {
                'email': 'test_weak@example.com',
                'password': 'password',
                'organization_name': 'New Org',
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('password', response.data)

    def test_email_verification_flow(self):
        # 1. Register user
        response = self.client.post(
            '/api/v1/auth/register/',
            {
                'email': 'unverified@example.com',
                'password': 'StrongPass123!',
                'organization_name': 'New Org',
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('user', response.data)
        user = User.objects.get(email='unverified@example.com')
        self.assertFalse(user.is_email_verified)

        # Ensure verification email was sent to outbox
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Verify Your LeadOrbit Email', mail.outbox[0].subject)

        # 2. Try logging in (should fail since email is unverified)
        login_response = self.client.post(
            '/api/v1/token/',
            {
                'email': 'unverified@example.com',
                'password': 'StrongPass123!',
            },
            format='json',
        )
        self.assertEqual(login_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('non_field_errors', login_response.data)

        # 3. Get verification token/uid
        uidb64 = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)

        # 4. Verify email
        verify_response = self.client.post(
            '/api/v1/auth/verify-email/',
            {
                'uid': uidb64,
                'token': token,
            },
            format='json',
        )
        self.assertEqual(verify_response.status_code, status.HTTP_200_OK)
        user.refresh_from_db()
        self.assertTrue(user.is_email_verified)

        # 5. Log in after verification (should succeed)
        login_response2 = self.client.post(
            '/api/v1/token/',
            {
                'email': 'unverified@example.com',
                'password': 'StrongPass123!',
            },
            format='json',
        )
        self.assertEqual(login_response2.status_code, status.HTTP_200_OK)
        self.assertIn('access', login_response2.data)

    def test_mfa_flow(self):
        import pyotp
        # Create a verified user
        user = User.objects.create_user(
            email='mfa_user@example.com',
            password='StrongPass123!',
            organization=self.organization,
            role=User.ROLE_ADMIN,
        )
        user.is_email_verified = True
        user.save()

        # 1. Enable MFA setup
        self.client.force_authenticate(user)
        enable_response = self.client.post('/api/v1/auth/enable-mfa/', format='json')
        self.assertEqual(enable_response.status_code, status.HTTP_200_OK)
        self.assertIn('secret', enable_response.data)
        secret = enable_response.data['secret']

        # 2. Confirm MFA setup with valid TOTP code
        totp = pyotp.TOTP(secret)
        confirm_response = self.client.post(
            '/api/v1/auth/confirm-mfa/',
            {'code': totp.now()},
            format='json',
        )
        self.assertEqual(confirm_response.status_code, status.HTTP_200_OK)
        user.refresh_from_db()
        self.assertTrue(user.mfa_enabled)

        # 3. Log in (should return MFA challenge/token)
        self.client.logout()
        login_response = self.client.post(
            '/api/v1/token/',
            {
                'email': 'mfa_user@example.com',
                'password': 'StrongPass123!',
            },
            format='json',
        )
        self.assertEqual(login_response.status_code, status.HTTP_200_OK)
        self.assertTrue(login_response.data.get('mfa_required'))
        mfa_token = login_response.data.get('mfa_token')
        self.assertIsNotNone(mfa_token)

        # 4. Verify MFA with invalid code (should fail)
        verify_response_fail = self.client.post(
            '/api/v1/auth/verify-mfa/',
            {
                'mfa_token': mfa_token,
                'code': '000000',
            },
            format='json',
        )
        self.assertEqual(verify_response_fail.status_code, status.HTTP_400_BAD_REQUEST)

        # 5. Verify MFA with valid code (should succeed and return JWT tokens)
        verify_response_success = self.client.post(
            '/api/v1/auth/verify-mfa/',
            {
                'mfa_token': mfa_token,
                'code': totp.now(),
            },
            format='json',
        )
        self.assertEqual(verify_response_success.status_code, status.HTTP_200_OK)
        self.assertIn('access', verify_response_success.data)

