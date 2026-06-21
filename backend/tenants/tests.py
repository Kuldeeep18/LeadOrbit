from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase

import backend.settings as project_settings


class SettingsTests(TestCase):
    def test_secret_key_falls_back_to_temporary_key_in_debug(self):
        with patch.object(project_settings, 'DEBUG', True):
            with patch.dict('backend.settings.os.environ', {}, clear=True):
                with patch('backend.settings._read_local_env_value', return_value=''):
                    with self.assertWarns(RuntimeWarning) as warning:
                        secret_key = project_settings._get_secret_key()

        self.assertTrue(secret_key)
        self.assertNotEqual(secret_key, 'change-me-in-local-env')
        self.assertIn('SECRET_KEY is not set', str(warning.warning))

    def test_secret_key_requires_configuration_outside_debug(self):
        with patch.object(project_settings, 'DEBUG', False):
            with patch.object(project_settings.sys, 'argv', ['manage.py', 'runserver']):
                with patch.dict('backend.settings.os.environ', {}, clear=True):
                    with patch('backend.settings._read_local_env_value', return_value=''):
                        with self.assertRaisesMessage(ImproperlyConfigured, 'SECRET_KEY must be set when DEBUG is False.'):
                            project_settings._get_secret_key()
