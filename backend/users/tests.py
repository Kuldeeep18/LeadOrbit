from datetime import timedelta
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

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
                'current_password': 'StrongPass123!',
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
            {'current_password': 'StrongPass123!', 'new_password': 'MemberStrong123!'},
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

    def test_password_change_requires_current_password_and_changes_nothing_without_it(self):
        for current_password in (None, 'WrongPass123!'):
            payload = {'organization_name': 'Should Not Stick', 'new_password': 'EvenStronger123!'}
            if current_password:
                payload['current_password'] = current_password

            response = self.client.patch('/api/v1/auth/me/', payload, format='json')

            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertIn('current_password', response.data)
            self.user.refresh_from_db()
            self.organization.refresh_from_db()
            self.assertTrue(self.user.check_password('StrongPass123!'))
            self.assertEqual(self.organization.name, 'Org Before')

    def test_me_reports_whether_a_gemini_key_is_saved_without_revealing_it(self):
        self.organization.gemini_api_key = 'AIza-secret-key'
        self.organization.save(update_fields=['gemini_api_key'])

        response = self.client.get('/api/v1/auth/me/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['organization']['has_gemini_api_key'])
        self.assertNotIn('gemini_api_key', response.data['organization'])
        self.assertNotIn('AIza-secret-key', response.content.decode('utf-8'))

    def test_admin_can_remove_saved_gemini_key_with_empty_string(self):
        self.organization.gemini_api_key = 'AIza-secret-key'
        self.organization.save(update_fields=['gemini_api_key'])

        response = self.client.patch('/api/v1/auth/me/', {'gemini_api_key': ''}, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data['organization']['has_gemini_api_key'])
        self.organization.refresh_from_db()
        self.assertIsNone(self.organization.gemini_api_key)


class RegistrationAndLoginTests(APITestCase):
    def test_register_rejects_weak_password_without_creating_an_organization(self):
        response = self.client.post(
            '/api/v1/auth/register/',
            {'email': 'new@example.com', 'password': '12345678', 'organization_name': 'Weak Org'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('password', response.data)
        self.assertFalse(Organization.objects.filter(name='Weak Org').exists())
        self.assertFalse(User.objects.filter(email='new@example.com').exists())

    def test_login_accepts_email_in_any_case(self):
        organization = Organization.objects.create(name='Case Org')
        User.objects.create_user(
            email='Founder@Example.com',
            password='StrongPass123!',
            organization=organization,
            role=User.ROLE_ADMIN,
        )

        response = self.client.post(
            '/api/v1/token/',
            {'email': 'founder@example.com', 'password': 'StrongPass123!'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.data)

    def test_login_still_rejects_wrong_password(self):
        organization = Organization.objects.create(name='Case Org')
        User.objects.create_user(
            email='founder@example.com',
            password='StrongPass123!',
            organization=organization,
            role=User.ROLE_ADMIN,
        )

        response = self.client.post(
            '/api/v1/token/',
            {'email': 'FOUNDER@example.com', 'password': 'WrongPass123!'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class AccountDeactivationTests(APITestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name='Test Org')
        self.user = User.objects.create_user(
            email='user@example.com',
            password='StrongPass123!',
            organization=self.organization,
            role=User.ROLE_MEMBER,
        )
        self.other_user = User.objects.create_user(
            email='other@example.com',
            password='StrongPass123!',
            organization=self.organization,
            role=User.ROLE_MEMBER,
        )

    def test_unauthenticated_request_is_rejected(self):
        response = self.client.delete(
            '/api/v1/auth/account/',
            {'email': 'user@example.com'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_authenticated_user_can_deactivate_own_account_with_correct_email(self):
        self.client.force_authenticate(self.user)
        before = timezone.now()
        response = self.client.delete(
            '/api/v1/auth/account/',
            {'email': 'user@example.com'},
            format='json',
        )
        after = timezone.now()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {'message': 'Account scheduled for deletion in 30 days.'})

        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)
        self.assertIsNotNone(self.user.deletion_scheduled_at)
        expected_scheduled_min = before + timedelta(days=30)
        expected_scheduled_max = after + timedelta(days=30)
        self.assertTrue(expected_scheduled_min <= self.user.deletion_scheduled_at <= expected_scheduled_max)

    def test_authenticated_user_can_deactivate_with_case_insensitive_email(self):
        self.client.force_authenticate(self.user)
        response = self.client.delete(
            '/api/v1/auth/account/',
            {'email': 'USER@EXAMPLE.COM'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)

    def test_incorrect_confirmation_email_is_rejected(self):
        self.client.force_authenticate(self.user)
        response = self.client.delete(
            '/api/v1/auth/account/',
            {'email': 'wrong@example.com'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('email', response.data)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)
        self.assertIsNone(self.user.deletion_scheduled_at)

    def test_missing_confirmation_email_is_rejected(self):
        self.client.force_authenticate(self.user)
        response = self.client.delete(
            '/api/v1/auth/account/',
            {},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('email', response.data)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)
        self.assertIsNone(self.user.deletion_scheduled_at)

    def test_cannot_deactivate_another_users_account(self):
        # Even if the authenticated user sends another user's email, it's rejected
        self.client.force_authenticate(self.user)
        response = self.client.delete(
            '/api/v1/auth/account/',
            {'email': self.other_user.email},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.other_user.refresh_from_db()
        self.assertTrue(self.other_user.is_active)
        self.assertIsNone(self.other_user.deletion_scheduled_at)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)

    def test_user_data_is_not_immediately_hard_deleted(self):
        self.client.force_authenticate(self.user)
        user_id = self.user.id
        org_id = self.organization.id

        response = self.client.delete(
            '/api/v1/auth/account/',
            {'email': self.user.email},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertTrue(User.objects.filter(id=user_id).exists())
        self.assertTrue(Organization.objects.filter(id=org_id).exists())

    def test_repeated_deactivation_requests_do_not_reset_original_schedule(self):
        fixed_schedule = timezone.now() + timedelta(days=20)
        self.user.is_active = False
        self.user.deletion_scheduled_at = fixed_schedule
        self.user.save(update_fields=['is_active', 'deletion_scheduled_at'])

        self.client.force_authenticate(self.user)
        response = self.client.delete(
            '/api/v1/auth/account/',
            {'email': self.user.email},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.user.refresh_from_db()
        self.assertEqual(self.user.deletion_scheduled_at, fixed_schedule)

    def test_deactivated_user_cannot_obtain_token(self):
        self.user.is_active = False
        self.user.save(update_fields=['is_active'])

        response = self.client.post(
            '/api/v1/token/',
            {'email': self.user.email, 'password': 'StrongPass123!'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_deactivated_user_cannot_access_protected_endpoints_with_existing_token(self):
        # Obtain token while active
        token_response = self.client.post(
            '/api/v1/token/',
            {'email': self.user.email, 'password': 'StrongPass123!'},
            format='json',
        )
        access_token = token_response.data['access']

        # Verify access works with token
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access_token}')
        res_before = self.client.get('/api/v1/auth/me/')
        self.assertEqual(res_before.status_code, status.HTTP_200_OK)

        # Deactivate account via the endpoint
        deact_res = self.client.delete(
            '/api/v1/auth/account/',
            {'email': self.user.email},
            format='json',
        )
        self.assertEqual(deact_res.status_code, status.HTTP_200_OK)

        # Immediate follow-up request with same token must be rejected because is_active is False
        res_after = self.client.get('/api/v1/auth/me/')
        self.assertEqual(res_after.status_code, status.HTTP_401_UNAUTHORIZED)
