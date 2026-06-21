from django.test import TestCase

from backend.settings import _allow_all_cors_origins
from backend.settings import _parse_allowed_hosts


class AllowedHostsSettingsTests(TestCase):
    def test_parse_allowed_hosts_defaults_to_local_hosts_outside_debug(self):
        self.assertEqual(
            _parse_allowed_hosts('', debug=False),
            ['localhost', '127.0.0.1'],
        )

    def test_parse_allowed_hosts_allows_wildcard_only_in_debug(self):
        self.assertEqual(_parse_allowed_hosts('*', debug=True), ['*'])
        self.assertEqual(
            _parse_allowed_hosts('*', debug=False),
            ['localhost', '127.0.0.1'],
        )

    def test_parse_allowed_hosts_trims_and_preserves_comma_separated_hosts(self):
        self.assertEqual(
            _parse_allowed_hosts(' example.com , api.example.com ', debug=False),
            ['example.com', 'api.example.com'],
        )


class CorsSettingsTests(TestCase):
    def test_allow_all_cors_origins_only_in_debug(self):
        self.assertTrue(_allow_all_cors_origins(True))
        self.assertFalse(_allow_all_cors_origins(False))
