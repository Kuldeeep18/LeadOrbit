from io import StringIO

from django.test import SimpleTestCase, override_settings

from .startup import warn_missing_critical_settings


class StartupSettingsValidationTests(SimpleTestCase):
    @override_settings(
        GEMINI_API_KEY='',
        GOOGLE_CLIENT_ID='',
        GOOGLE_CLIENT_SECRET='',
    )
    def test_warns_when_critical_settings_are_missing(self):
        buffer = StringIO()

        missing = warn_missing_critical_settings(stream=buffer)

        self.assertEqual(
            missing,
            ['GEMINI_API_KEY', 'GOOGLE_CLIENT_ID', 'GOOGLE_CLIENT_SECRET'],
        )
        self.assertIn('Missing LeadOrbit startup settings', buffer.getvalue())

    @override_settings(
        GEMINI_API_KEY='gemini-key',
        GOOGLE_CLIENT_ID='client-id',
        GOOGLE_CLIENT_SECRET='client-secret',
    )
    def test_returns_quietly_when_all_settings_exist(self):
        buffer = StringIO()

        missing = warn_missing_critical_settings(stream=buffer)

        self.assertEqual(missing, [])
        self.assertEqual(buffer.getvalue(), '')
