from django.db import connection
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings

from leads.models import Lead
from tenants.middleware import TenantMiddleware, _make_tenant_isolation_checker, _thread_locals
from tenants.models import Organization


class TenantIsolationCheckerTests(TestCase):
    """
    Verifies that _make_tenant_isolation_checker logs a WARNING when a
    TenantModel table is queried without an organization_id filter in the
    WHERE clause, and stays silent for properly scoped queries.
    """

    def setUp(self):
        self.org = Organization.objects.create(name='Test Org')
        Lead.objects.create(organization=self.org, email='seed@example.com')

    def _checker_wrapper(self, path='/test/'):
        return connection.execute_wrapper(_make_tenant_isolation_checker(path))

    @override_settings(DEBUG=True)
    def test_warns_on_unscoped_query(self):
        """Lead.objects.all() with no org filter should emit a WARNING."""
        with self.assertLogs('tenants.middleware', level='WARNING') as ctx:
            with self._checker_wrapper():
                list(Lead.objects.all())

        self.assertTrue(
            any('leads_lead' in msg and 'organization_id' in msg for msg in ctx.output),
            msg=f"Expected tenant isolation warning. Got: {ctx.output}",
        )

    @override_settings(DEBUG=True)
    def test_no_warning_for_scoped_query(self):
        """A query filtered by organization should produce no WARNING."""
        with self._checker_wrapper():
            with self.assertNoLogs('tenants.middleware', level='WARNING'):
                list(Lead.objects.filter(organization=self.org))

    @override_settings(DEBUG=True)
    def test_warning_includes_request_path(self):
        """WARNING message should include the triggering request path for easy tracing."""
        path = '/api/v1/leads/'
        with self.assertLogs('tenants.middleware', level='WARNING') as ctx:
            with connection.execute_wrapper(_make_tenant_isolation_checker(path)):
                list(Lead.objects.all())

        self.assertTrue(
            any(path in msg for msg in ctx.output),
            msg=f"Expected path '{path}' in warning. Got: {ctx.output}",
        )

    @override_settings(DEBUG=True)
    def test_checker_ignores_insert_queries(self):
        """INSERT queries have no WHERE clause and should not trigger a WARNING."""
        with self._checker_wrapper():
            with self.assertNoLogs('tenants.middleware', level='WARNING'):
                Lead.objects.create(organization=self.org, email='new@example.com')

    @override_settings(DEBUG=True)
    def test_warns_on_unscoped_update(self):
        """An UPDATE without an organization_id filter should emit a WARNING."""
        with self.assertLogs('tenants.middleware', level='WARNING') as ctx:
            with self._checker_wrapper():
                Lead.objects.filter(email='seed@example.com').update(email='changed@example.com')

        self.assertTrue(
            any('leads_lead' in msg and 'organization_id' in msg for msg in ctx.output),
            msg=f"Expected tenant isolation warning for UPDATE. Got: {ctx.output}",
        )

    @override_settings(DEBUG=True)
    def test_warns_on_unscoped_delete(self):
        """A DELETE without an organization_id filter should emit a WARNING."""
        with self.assertLogs('tenants.middleware', level='WARNING') as ctx:
            with self._checker_wrapper():
                Lead.objects.filter(email='seed@example.com').delete()

        self.assertTrue(
            any('leads_lead' in msg and 'organization_id' in msg for msg in ctx.output),
            msg=f"Expected tenant isolation warning for DELETE. Got: {ctx.output}",
        )


class TenantMiddlewareWiringTests(TestCase):
    """
    Verifies that TenantMiddleware correctly installs the isolation checker
    onto connection.execute_wrappers in DEBUG mode and fully cleans up after
    process_response, guarding against wrapper accumulation across requests.
    """

    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = TenantMiddleware(get_response=lambda r: HttpResponse())

    def tearDown(self):
        # Directly clear any leaked checker without going through process_response,
        # which guards on settings.DEBUG and may be False by the time tearDown runs.
        checker = getattr(_thread_locals, 'isolation_checker', None)
        if checker is not None:
            try:
                connection.execute_wrappers.remove(checker)
            except ValueError:
                pass
            del _thread_locals.isolation_checker

    @override_settings(DEBUG=True)
    def test_process_request_installs_checker_in_debug(self):
        """Checker should be appended to execute_wrappers during a DEBUG request."""
        request = self.factory.get('/api/v1/leads/')
        count_before = len(connection.execute_wrappers)

        self.middleware.process_request(request)

        self.assertEqual(len(connection.execute_wrappers), count_before + 1)
        self.assertIsNotNone(getattr(_thread_locals, 'isolation_checker', None))

    @override_settings(DEBUG=True)
    def test_process_response_removes_checker_and_clears_thread_local(self):
        """Checker must be removed from execute_wrappers after the response is sent."""
        request = self.factory.get('/api/v1/leads/')
        self.middleware.process_request(request)
        wrappers_after_request = len(connection.execute_wrappers)

        self.middleware.process_response(request, HttpResponse())

        self.assertEqual(len(connection.execute_wrappers), wrappers_after_request - 1)
        self.assertIsNone(getattr(_thread_locals, 'isolation_checker', None))

    @override_settings(DEBUG=False)
    def test_process_request_skips_checker_when_not_debug(self):
        """No checker should be installed when DEBUG is False."""
        request = self.factory.get('/api/v1/leads/')
        count_before = len(connection.execute_wrappers)

        self.middleware.process_request(request)

        self.assertEqual(len(connection.execute_wrappers), count_before)
        self.assertIsNone(getattr(_thread_locals, 'isolation_checker', None))