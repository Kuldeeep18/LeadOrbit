from unittest.mock import patch

from rest_framework import status
from rest_framework.test import APITestCase
from django.contrib.auth.tokens import default_token_generator
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

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


class PasswordResetFlowTests(APITestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name='Reset Org')
        self.user = User.objects.create_user(
            email='forgot@example.com',
            password='StrongPass123!',
            organization=self.organization,
            role=User.ROLE_ADMIN,
        )

    @patch('users.views.send_mail')
    def test_password_reset_request_sends_email_for_existing_user(self, mocked_send_mail):
        response = self.client.post(
            '/api/v1/auth/password-reset/',
            {'email': 'forgot@example.com'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mocked_send_mail.assert_called_once()
        sent_args, sent_kwargs = mocked_send_mail.call_args
        self.assertIn('LeadOrbit password reset', sent_kwargs['subject'])
        self.assertEqual(sent_kwargs['recipient_list'], ['forgot@example.com'])
        self.assertIn('/password-reset.html?uid=', sent_kwargs['message'])

    def test_password_reset_confirm_updates_password(self):
        uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        token = default_token_generator.make_token(self.user)

        response = self.client.post(
            '/api/v1/auth/password-reset/confirm/',
            {
                'uid': uid,
                'token': token,
                'new_password': 'NewStrongPass123!',
                'confirm_password': 'NewStrongPass123!',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('NewStrongPass123!'))

    def test_password_reset_confirm_rejects_mismatched_passwords(self):
        uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        token = default_token_generator.make_token(self.user)

        response = self.client.post(
            '/api/v1/auth/password-reset/confirm/',
            {
                'uid': uid,
                'token': token,
                'new_password': 'NewStrongPass123!',
                'confirm_password': 'DifferentPass123!',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('confirm_password', response.data)
