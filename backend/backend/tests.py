from django.test import SimpleTestCase
from django.conf import settings as django_settings


class LoggingSettingsTests(SimpleTestCase):
    def test_logging_config_includes_console_file_and_backend_loggers(self):
        logging_config = django_settings.LOGGING

        self.assertIn('console', logging_config['handlers'])
        self.assertIn('file', logging_config['handlers'])
        self.assertIn('django.db.backends', logging_config['loggers'])
        self.assertIn('celery.app.trace', logging_config['loggers'])
        self.assertEqual(logging_config['root']['handlers'], ['console', 'file'])
