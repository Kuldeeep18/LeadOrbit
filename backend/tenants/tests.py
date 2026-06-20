from django.test import TestCase

from backend.settings import _allow_all_cors_origins


class CorsSettingsTests(TestCase):
    def test_allow_all_cors_origins_matches_debug_mode(self):
        self.assertTrue(_allow_all_cors_origins(True))
        self.assertFalse(_allow_all_cors_origins(False))
