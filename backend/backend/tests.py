from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from backend import settings as settings_module


class SecretKeyValidationTests(SimpleTestCase):
    def test_rejects_placeholder_secret_keys(self):
        for value in ('change-me', 'changeme', 'secret', ''):
            with self.subTest(value=value):
                with self.assertRaises(ImproperlyConfigured):
                    settings_module.resolve_secret_key(value, debug=False, testing=False)

    def test_allows_secure_secret_keys(self):
        secret = settings_module.resolve_secret_key(
            'a-secure-secret-key-for-tests',
            debug=False,
            testing=False,
        )
        self.assertEqual(secret, 'a-secure-secret-key-for-tests')

    def test_generates_secure_default_in_debug(self):
        secret = settings_module.resolve_secret_key('', debug=True, testing=False)
        self.assertTrue(secret)
        self.assertNotIn(secret.lower(), {'change-me', 'changeme', 'secret', ''})
