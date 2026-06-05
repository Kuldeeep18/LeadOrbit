from rest_framework import status
from rest_framework.test import APITestCase

from tenants.models import Organization
from users.models import User


class AuthMeViewTests(APITestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name='Org Before')
        self.user = User.objects.create_user(
            email='admin@example.com',
            password='StrongPass123!',
            organization=self.organization,
            role='ADMIN',
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

    def test_patch_me_updates_avatar_url(self):
        response = self.client.patch(
            '/api/v1/auth/me/',
            {'avatar_url': 'https://example.com/avatar.png'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertEqual(self.user.avatar_url, 'https://example.com/avatar.png')
        self.assertEqual(response.data['avatar_url'], 'https://example.com/avatar.png')

    def test_patch_me_updates_first_and_last_name(self):
        response = self.client.patch(
            '/api/v1/auth/me/',
            {'first_name': 'Jane', 'last_name': 'Doe'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, 'Jane')
        self.assertEqual(self.user.last_name, 'Doe')
        self.assertEqual(response.data['first_name'], 'Jane')
        self.assertEqual(response.data['last_name'], 'Doe')

    def test_get_me_returns_avatar_url(self):
        self.user.avatar_url = 'https://example.com/avatar.png'
        self.user.save(update_fields=['avatar_url'])

        response = self.client.get('/api/v1/auth/me/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['avatar_url'], 'https://example.com/avatar.png')

    def test_register_accepts_avatar_url(self):
        response = self.client.post(
            '/api/v1/auth/register/',
            {
                'email': 'newuser@example.com',
                'password': 'StrongPass123!',
                'organization_name': 'New Org',
                'first_name': 'Jane',
                'last_name': 'Doe',
                'avatar_url': 'https://example.com/avatar.png',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['user']['avatar_url'], 'https://example.com/avatar.png')
        self.assertEqual(response.data['user']['first_name'], 'Jane')
        self.assertEqual(response.data['user']['last_name'], 'Doe')

    def test_delete_organization_removes_current_organization(self):
        response = self.client.delete('/api/v1/auth/delete-organization/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(Organization.objects.filter(id=self.organization.id).exists())
        self.assertFalse(User.objects.filter(id=self.user.id).exists())
