from datetime import timedelta
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from django.core import signing
from django.core.exceptions import ImproperlyConfigured
from django.db import connection
from django.http import HttpResponseBadRequest
from django.test import RequestFactory, override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from campaigns.models import Campaign, CampaignLead, ConnectedEmailAccount, SequenceStep
from campaigns.fields import decrypt_mailbox_credential, encrypt_mailbox_credential
from campaigns.ai import personalize_email
from campaigns.tasks import (
    _execute_condition_event_step,
    check_imap_bounces,
    _get_campaign_steps,
    poll_gmail_for_replies,
    process_active_leads,
    process_active_leads_once,
    send_email_step,
)
from campaigns.utils import generate_unsubscribe_token
from leads.models import BlockedDomain, Lead
from tenants.middleware import TenantMiddleware
from tenants.models import Organization
from users.models import User


@override_settings(GEMINI_API_KEY='')
class CampaignWorkflowTests(APITestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name='Acme')
        self.user = User.objects.create_user(
            email='owner@acme.test',
            password='StrongPass123!',
            organization=self.organization,
            role='ADMIN',
        )
        self.client.force_authenticate(self.user)

    def test_custom_domain_middleware_routes_tracking_requests_to_click_endpoint(self):
        organization = Organization.objects.create(name='BrandCo', custom_tracking_domain='track.brandco.test')
        self.user.organization = organization
        self.user.save(update_fields=['organization'])

        request = RequestFactory().get('/track/click', HTTP_HOST='track.brandco.test')
        request.user = self.user
        request.session = {}

        middleware = TenantMiddleware(lambda request: None)
        response = middleware.process_request(request)
        self.assertIsNone(response)

        from tenants.middleware import get_current_tenant
        self.assertEqual(get_current_tenant(), organization)

    @override_settings(CUSTOM_TRACKING_DOMAIN_VALIDATION=True, CUSTOM_TRACKING_DOMAIN_SKIP_DNS_CHECK=False)
    def test_custom_domain_middleware_rejects_invalid_tracking_domain(self):
        organization = Organization.objects.create(name='BrandCo 2', custom_tracking_domain='track.brandco.test')
        self.user.organization = organization
        self.user.save(update_fields=['organization'])

        request = RequestFactory().get('/track/click', HTTP_HOST='track.brandco.test')
        request.user = self.user
        request.session = {}

        from tenants.middleware import get_current_tenant
        from tenants.middleware import CustomDomainMiddleware

        _thread_locals = __import__('tenants.middleware', fromlist=['_thread_locals'])._thread_locals
        _thread_locals.tenant = organization

        middleware = CustomDomainMiddleware(lambda request: None)
        response = middleware.process_request(request)

        self.assertIsInstance(response, HttpResponseBadRequest)

    def test_create_campaign_syncs_sequence_steps_from_builder_payload(self):
        account = ConnectedEmailAccount.objects.create(
            organization=self.organization,
            connected_by=self.user,
            email_address='sender@acme.test',
            provider='GOOGLE',
            access_token='token',
            refresh_token='refresh',
        )

        payload = {
            'name': 'Onboarding',
            'status': 'ACTIVE',
            'settings': {
                'timezone': 'UTC',
                'steps': [
                    {'type': 'EMAIL', 'subject': 'Hello {{firstName}}', 'body': 'Hi {{firstName}}'},
                    {'type': 'WAIT', 'delay_value': 2, 'delay_unit': 'days'},
                ],
            },
            'connected_account_id': str(account.id),
        }

        response = self.client.post('/api/v1/campaigns/', payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        campaign = Campaign.objects.get(id=response.data['id'])
        self.assertEqual(campaign.connected_account_id, account.id)

        steps = list(campaign.steps.order_by('step_order'))
        self.assertEqual(len(steps), 2)
        self.assertEqual(steps[0].channel_type, 'EMAIL')
        self.assertEqual(steps[0].template_subject, 'Hello {{firstName}}')
        self.assertEqual(steps[1].channel_type, 'WAIT')
        self.assertEqual(steps[1].delay_minutes, 2880)

    def test_create_custom_connected_account_from_settings(self):
        payload = {
            'email_address': 'custom-sender@acme.test',
            'smtp_host': 'smtp.acme.test',
            'smtp_port': 587,
            'smtp_username': 'smtp-user',
            'smtp_password': 'smtp-pass',
            'smtp_use_tls': True,
            'smtp_use_ssl': False,
            'imap_host': 'imap.acme.test',
            'imap_port': 993,
            'imap_username': 'imap-user',
            'imap_password': 'imap-pass',
            'imap_use_ssl': True,
        }

        response = self.client.post('/api/v1/connected-accounts/', payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['provider'], 'CUSTOM')
        self.assertTrue(response.data['supports_smtp'])
        self.assertTrue(response.data['supports_imap'])

        account = ConnectedEmailAccount.objects.get(email_address='custom-sender@acme.test')
        self.assertEqual(account.provider, 'CUSTOM')
        self.assertEqual(account.smtp_host, 'smtp.acme.test')
        self.assertEqual(account.imap_host, 'imap.acme.test')
        self.assertEqual(account.connected_by, self.user)

    def test_create_custom_connected_account_requires_secure_smtp_transport(self):
        payload = {
            'email_address': 'insecure-sender@acme.test',
            'smtp_host': 'smtp.acme.test',
            'smtp_port': 25,
            'smtp_username': 'smtp-user',
            'smtp_password': 'smtp-pass',
            'smtp_use_tls': False,
            'smtp_use_ssl': False,
            'imap_host': 'imap.acme.test',
            'imap_port': 993,
            'imap_username': 'imap-user',
            'imap_password': 'imap-pass',
            'imap_use_ssl': True,
        }

        response = self.client.post('/api/v1/connected-accounts/', payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('smtp_use_tls', response.data)

    def test_custom_connected_account_passwords_are_encrypted_at_rest(self):
        payload = {
            'email_address': 'encrypted-sender@acme.test',
            'smtp_host': 'smtp.acme.test',
            'smtp_port': 587,
            'smtp_username': 'smtp-user',
            'smtp_password': 'smtp-pass',
            'smtp_use_tls': True,
            'smtp_use_ssl': False,
            'imap_host': 'imap.acme.test',
            'imap_port': 993,
            'imap_username': 'imap-user',
            'imap_password': 'imap-pass',
            'imap_use_ssl': True,
        }

        response = self.client.post('/api/v1/connected-accounts/', payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        account = ConnectedEmailAccount.objects.get(email_address='encrypted-sender@acme.test')
        self.assertEqual(account.smtp_password, 'smtp-pass')
        self.assertEqual(account.imap_password, 'imap-pass')

        with connection.cursor() as cursor:
            param = account.id.hex if connection.vendor == 'sqlite' else str(account.id)
            cursor.execute(
                "SELECT smtp_password, imap_password FROM campaigns_connectedemailaccount WHERE id = %s",
                [param],
            )
            stored_smtp_password, stored_imap_password = cursor.fetchone()

        self.assertNotEqual(stored_smtp_password, 'smtp-pass')
        self.assertNotEqual(stored_imap_password, 'imap-pass')
        self.assertTrue(stored_smtp_password.startswith('enc::'))
        self.assertTrue(stored_imap_password.startswith('enc::'))

    def test_encrypt_mailbox_credential_encrypts_plaintext_with_prefix(self):
        raw_password = 'enc::not-actually-encrypted'
        encrypted_password = encrypt_mailbox_credential(raw_password)

        self.assertNotEqual(encrypted_password, raw_password)
        self.assertTrue(encrypted_password.startswith('enc::'))
        self.assertEqual(decrypt_mailbox_credential(encrypted_password), raw_password)

    @override_settings(DEBUG=False, MAILBOX_CREDENTIALS_ENCRYPTION_KEY='')
    def test_encrypt_mailbox_credential_requires_dedicated_key_outside_debug(self):
        with self.assertRaises(ImproperlyConfigured):
            encrypt_mailbox_credential('smtp-pass')

    def test_create_campaign_supports_all_step_and_condition_types(self):
        payload = {
            'name': 'All step types',
            'status': 'DRAFT',
            'settings': {
                'steps': [
                    {'type': 'EMAIL', 'subject': 'Email subject', 'body': 'Email body'},
                    {'type': 'SMS', 'body': 'SMS body', 'delay_value': 5, 'delay_unit': 'minutes'},
                    {'type': 'WHATSAPP', 'body': 'WhatsApp body', 'delay_value': 2, 'delay_unit': 'hours'},
                    {'type': 'LINKEDIN', 'description': 'Send LinkedIn connection'},
                    {'type': 'WAIT', 'delay_value': 1, 'delay_unit': 'days'},
                    {'type': 'MANUAL', 'description': 'Review lead manually'},
                    {'type': 'CONDITION_OPEN', 'condition_time': '3 days'},
                    {'type': 'CONDITION_REPLY', 'condition_time': '1 week'},
                    {'type': 'CONDITION_CLICK', 'condition_time': 'not-a-valid-value'},
                ],
            },
        }

        response = self.client.post('/api/v1/campaigns/', payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        campaign = Campaign.objects.get(id=response.data['id'])
        steps = list(campaign.steps.order_by('step_order'))
        self.assertEqual(len(steps), 9)

        expected = [
            ('EMAIL', 0, 'Email subject', 'Email body'),
            ('SMS', 5, '', 'SMS body'),
            ('WHATSAPP', 120, '', 'WhatsApp body'),
            ('LINKEDIN', 0, '', 'Send LinkedIn connection'),
            ('WAIT', 1440, '', ''),
            ('MANUAL', 0, '', 'Review lead manually'),
            ('CONDITION_OPEN', 4320, '', ''),
            ('CONDITION_REPLY', 10080, '', ''),
            ('CONDITION_CLICK', 1440, '', ''),
        ]
        for index, (channel_type, delay_minutes, subject, body) in enumerate(expected):
            with self.subTest(step_order=index + 1, channel_type=channel_type):
                self.assertEqual(steps[index].channel_type, channel_type)
                self.assertEqual(steps[index].delay_minutes, delay_minutes)
                self.assertEqual(steps[index].template_subject or '', subject)
                self.assertEqual(steps[index].template_body or '', body)

    def test_personalize_email_replaces_custom_variables(self):
        lead = Lead.objects.create(
            organization=self.organization,
            email='custom-vars@acme.test',
            first_name='Casey',
            custom_variables={
                'industry': 'SaaS',
                'meeting_time': '10:30 AM',
            },
        )

        subject, body = personalize_email(
            'Hello {{firstName}} from {{industry}}',
            'Can we talk at {{meeting_time}}?',
            lead,
        )

        self.assertEqual(subject, 'Hello Casey from SaaS')
        self.assertEqual(body, 'Can we talk at 10:30 AM?')

    def test_process_active_leads_advances_all_non_email_step_types(self):
        campaign = Campaign.objects.create(
            organization=self.organization,
            name='All non-email step flow',
            status='ACTIVE',
        )
        sms_step = SequenceStep.objects.create(
            organization=self.organization,
            campaign=campaign,
            step_order=1,
            channel_type='SMS',
            delay_minutes=0,
            template_body='SMS',
        )
        SequenceStep.objects.create(
            organization=self.organization,
            campaign=campaign,
            step_order=2,
            channel_type='WHATSAPP',
            delay_minutes=0,
            template_body='WhatsApp',
        )
        SequenceStep.objects.create(
            organization=self.organization,
            campaign=campaign,
            step_order=3,
            channel_type='LINKEDIN',
            delay_minutes=0,
            template_body='LinkedIn',
        )
        SequenceStep.objects.create(
            organization=self.organization,
            campaign=campaign,
            step_order=4,
            channel_type='WAIT',
            delay_minutes=0,
        )
        SequenceStep.objects.create(
            organization=self.organization,
            campaign=campaign,
            step_order=5,
            channel_type='MANUAL',
            delay_minutes=0,
            template_body='Manual task',
        )
        SequenceStep.objects.create(
            organization=self.organization,
            campaign=campaign,
            step_order=6,
            channel_type='CONDITION_OPEN',
            delay_minutes=0,
        )
        SequenceStep.objects.create(
            organization=self.organization,
            campaign=campaign,
            step_order=7,
            channel_type='CONDITION_CLICK',
            delay_minutes=0,
        )
        email_step = SequenceStep.objects.create(
            organization=self.organization,
            campaign=campaign,
            step_order=8,
            channel_type='EMAIL',
            delay_minutes=5,
            template_subject='Final step',
            template_body='Email',
        )
        lead = Lead.objects.create(
            organization=self.organization,
            email='all-types@acme.test',
        )
        campaign_lead = CampaignLead.objects.create(
            organization=self.organization,
            campaign=campaign,
            lead=lead,
            current_step=sms_step,
            status='ACTIVE',
            next_execution_time=timezone.now() - timedelta(minutes=1),
            last_opened_at=timezone.now(),
            last_clicked_at=timezone.now(),
        )

        now = timezone.now()
        with patch('campaigns.tasks.send_email_step.delay') as mocked_delay:
            processed = process_active_leads_once(now=now)

        self.assertEqual(processed, 1)
        campaign_lead.refresh_from_db()
        self.assertEqual(campaign_lead.current_step_id, email_step.id)
        self.assertEqual(campaign_lead.status, 'ACTIVE')
        self.assertGreaterEqual(campaign_lead.next_execution_time, now + timedelta(minutes=5))
        mocked_delay.assert_not_called()

    def test_launch_processing_uses_fresh_steps_after_sequence_resync(self):
        campaign = Campaign.objects.create(
            organization=self.organization,
            name='Fresh step cache flow',
            status='ACTIVE',
            settings={'steps': [{'type': 'WAIT'}]},
        )
        SequenceStep.objects.create(
            organization=self.organization,
            campaign=campaign,
            step_order=1,
            channel_type='EMAIL',
            delay_minutes=0,
            template_subject='Old',
            template_body='Old',
        )

        # Warm step lookup first, then resync sequence to mimic builder save flow.
        _get_campaign_steps(campaign)
        SequenceStep.objects.filter(campaign=campaign).delete()
        SequenceStep.objects.create(
            organization=self.organization,
            campaign=campaign,
            step_order=1,
            channel_type='WAIT',
            delay_minutes=0,
        )

        lead = Lead.objects.create(
            organization=self.organization,
            email='fresh-steps@acme.test',
        )
        campaign_lead = CampaignLead.objects.create(
            organization=self.organization,
            campaign=campaign,
            lead=lead,
            status='ENROLLED',
        )

        processed = process_active_leads_once(now=timezone.now())
        self.assertEqual(processed, 1)

        campaign_lead.refresh_from_db()
        self.assertEqual(campaign_lead.status, 'FINISHED')
        self.assertIsNone(campaign_lead.current_step)

    def test_process_active_leads_advances_non_email_steps(self):
        campaign = Campaign.objects.create(
            organization=self.organization,
            name='Non-email flow',
            status='ACTIVE',
        )
        wait_step = SequenceStep.objects.create(
            organization=self.organization,
            campaign=campaign,
            step_order=1,
            channel_type='WAIT',
            delay_minutes=0,
        )
        email_step = SequenceStep.objects.create(
            organization=self.organization,
            campaign=campaign,
            step_order=2,
            channel_type='EMAIL',
            delay_minutes=30,
            template_subject='Hello',
            template_body='Hi there',
        )
        lead = Lead.objects.create(
            organization=self.organization,
            email='lead@acme.test',
        )
        campaign_lead = CampaignLead.objects.create(
            organization=self.organization,
            campaign=campaign,
            lead=lead,
            current_step=wait_step,
            status='ACTIVE',
            next_execution_time=timezone.now() - timedelta(minutes=1),
        )

        process_active_leads()
        campaign_lead.refresh_from_db()

        self.assertEqual(campaign_lead.current_step_id, email_step.id)
        self.assertEqual(campaign_lead.status, 'ACTIVE')
        self.assertGreaterEqual(campaign_lead.next_execution_time, timezone.now() + timedelta(minutes=29))

    def test_delayed_wait_step_progresses_to_next_email_when_due(self):
        campaign = Campaign.objects.create(
            organization=self.organization,
            name='Email wait email',
            status='ACTIVE',
        )
        account = ConnectedEmailAccount.objects.create(
            organization=self.organization,
            connected_by=self.user,
            email_address='delay-sender@acme.test',
            provider='GOOGLE',
            access_token='token',
            refresh_token='refresh',
        )
        campaign.connected_account = account
        campaign.save(update_fields=['connected_account'])
        first_email = SequenceStep.objects.create(
            organization=self.organization,
            campaign=campaign,
            step_order=1,
            channel_type='EMAIL',
            delay_minutes=0,
            template_subject='First',
            template_body='First body',
        )
        wait_step = SequenceStep.objects.create(
            organization=self.organization,
            campaign=campaign,
            step_order=2,
            channel_type='WAIT',
            delay_minutes=2,
        )
        second_email = SequenceStep.objects.create(
            organization=self.organization,
            campaign=campaign,
            step_order=3,
            channel_type='EMAIL',
            delay_minutes=0,
            template_subject='Second',
            template_body='Second body',
        )
        lead = Lead.objects.create(
            organization=self.organization,
            email='delay-flow@acme.test',
        )
        campaign_lead = CampaignLead.objects.create(
            organization=self.organization,
            campaign=campaign,
            lead=lead,
            current_step=first_email,
            status='ACTIVE',
            next_execution_time=timezone.now() - timedelta(seconds=1),
        )

        with patch('campaigns.tasks.send_email_step.delay', side_effect=lambda cid, sid: send_email_step(cid, sid)):
            with patch('campaigns.tasks.send_gmail', side_effect=['msg-1', 'msg-2']):
                now = timezone.now()
                process_active_leads_once(now=now)
                campaign_lead.refresh_from_db()
                self.assertEqual(campaign_lead.current_step_id, wait_step.id)
                self.assertEqual(campaign_lead.status, 'ACTIVE')
                self.assertEqual(campaign_lead.last_sent_message_id, 'msg-1')

                process_active_leads_once(now=now + timedelta(minutes=1))
                campaign_lead.refresh_from_db()
                self.assertEqual(campaign_lead.current_step_id, wait_step.id)
                self.assertEqual(campaign_lead.last_sent_message_id, 'msg-1')

                process_active_leads_once(now=now + timedelta(minutes=2, seconds=1))
                campaign_lead.refresh_from_db()
                if campaign_lead.status != 'FINISHED':
                    self.assertEqual(campaign_lead.current_step_id, second_email.id)
                    process_active_leads_once(now=now + timedelta(minutes=2, seconds=1))
                    campaign_lead.refresh_from_db()
                self.assertEqual(campaign_lead.status, 'FINISHED')
                self.assertEqual(campaign_lead.last_sent_message_id, 'msg-2')

    def test_campaign_auto_completes_when_all_enrolled_leads_finish(self):
        campaign = Campaign.objects.create(
            organization=self.organization,
            name='Auto-complete flow',
            status='ACTIVE',
        )
        SequenceStep.objects.create(
            organization=self.organization,
            campaign=campaign,
            step_order=1,
            channel_type='MANUAL',
            delay_minutes=0,
            template_body='Do a manual task',
        )

        lead_one = Lead.objects.create(
            organization=self.organization,
            email='auto1@acme.test',
        )
        lead_two = Lead.objects.create(
            organization=self.organization,
            email='auto2@acme.test',
        )
        CampaignLead.objects.create(
            organization=self.organization,
            campaign=campaign,
            lead=lead_one,
            status='ENROLLED',
        )
        CampaignLead.objects.create(
            organization=self.organization,
            campaign=campaign,
            lead=lead_two,
            status='ENROLLED',
        )

        processed = process_active_leads_once(now=timezone.now())
        self.assertEqual(processed, 2)

        campaign.refresh_from_db()
        self.assertEqual(campaign.status, 'COMPLETED')
        self.assertFalse(
            CampaignLead.objects.filter(campaign=campaign).exclude(status='FINISHED').exists()
        )

    def test_process_active_leads_queues_email_steps(self):
        campaign = Campaign.objects.create(
            organization=self.organization,
            name='Email flow',
            status='ACTIVE',
        )
        email_step = SequenceStep.objects.create(
            organization=self.organization,
            campaign=campaign,
            step_order=1,
            channel_type='EMAIL',
            delay_minutes=0,
            template_subject='Hello',
            template_body='Hi there',
        )
        lead = Lead.objects.create(
            organization=self.organization,
            email='lead2@acme.test',
        )
        campaign_lead = CampaignLead.objects.create(
            organization=self.organization,
            campaign=campaign,
            lead=lead,
            current_step=email_step,
            status='ACTIVE',
            next_execution_time=timezone.now() - timedelta(minutes=1),
        )

        with patch('campaigns.tasks.send_email_step.delay') as mocked_delay:
            process_active_leads()
            mocked_delay.assert_called_once_with(campaign_lead.id, email_step.id)

    def test_create_campaign_rejects_connected_account_not_owned_by_current_user(self):
        teammate = User.objects.create_user(
            email='teammate@acme.test',
            password='StrongPass123!',
            organization=self.organization,
            role='USER',
        )
        teammate_account = ConnectedEmailAccount.objects.create(
            organization=self.organization,
            connected_by=teammate,
            email_address='teammate@acme.test',
            provider='GOOGLE',
            access_token='token',
            refresh_token='refresh',
        )

        payload = {
            'name': 'Unauthorized sender',
            'status': 'DRAFT',
            'settings': {'steps': []},
            'connected_account_id': str(teammate_account.id),
        }
        response = self.client.post('/api/v1/campaigns/', payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('connected_account_id', response.data)

    def test_connected_accounts_endpoint_returns_only_current_user_accounts(self):
        teammate = User.objects.create_user(
            email='teammate2@acme.test',
            password='StrongPass123!',
            organization=self.organization,
            role='USER',
        )
        mine = ConnectedEmailAccount.objects.create(
            organization=self.organization,
            connected_by=self.user,
            email_address='owner@acme.test',
            provider='GOOGLE',
            access_token='token1',
            refresh_token='refresh1',
        )
        ConnectedEmailAccount.objects.create(
            organization=self.organization,
            connected_by=teammate,
            email_address='teammate2@acme.test',
            provider='GOOGLE',
            access_token='token2',
            refresh_token='refresh2',
        )

        response = self.client.get('/api/v1/connected-accounts/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['id'], str(mine.id))

    def test_send_email_step_does_not_advance_when_gmail_send_fails(self):
        campaign = Campaign.objects.create(
            organization=self.organization,
            name='Send failure flow',
            status='ACTIVE',
        )
        account = ConnectedEmailAccount.objects.create(
            organization=self.organization,
            connected_by=self.user,
            email_address='sender@acme.test',
            provider='GOOGLE',
            access_token='token',
            refresh_token='refresh',
        )
        campaign.connected_account = account
        campaign.save(update_fields=['connected_account'])

        email_step = SequenceStep.objects.create(
            organization=self.organization,
            campaign=campaign,
            step_order=1,
            channel_type='EMAIL',
            delay_minutes=0,
            template_subject='Hello',
            template_body='Hi there',
        )
        second_step = SequenceStep.objects.create(
            organization=self.organization,
            campaign=campaign,
            step_order=2,
            channel_type='WAIT',
            delay_minutes=10,
        )
        lead = Lead.objects.create(
            organization=self.organization,
            email='lead3@acme.test',
        )
        campaign_lead = CampaignLead.objects.create(
            organization=self.organization,
            campaign=campaign,
            lead=lead,
            current_step=email_step,
            status='ACTIVE',
            next_execution_time=timezone.now() - timedelta(minutes=1),
        )

        with patch('campaigns.tasks.send_gmail', side_effect=Exception('gmail disabled')):
            send_email_step(campaign_lead.id, email_step.id)

        campaign_lead.refresh_from_db()
        self.assertEqual(campaign_lead.current_step_id, email_step.id)
        self.assertNotEqual(campaign_lead.current_step_id, second_step.id)
        self.assertEqual(campaign_lead.status, 'ACTIVE')
        self.assertIsNone(campaign_lead.last_sent_message_id)
        self.assertGreater(campaign_lead.next_execution_time, timezone.now())

    def test_condition_reply_step_stops_sequence_when_reply_detected(self):
        campaign = Campaign.objects.create(
            organization=self.organization,
            name='Condition reply flow',
            status='ACTIVE',
        )
        account = ConnectedEmailAccount.objects.create(
            organization=self.organization,
            connected_by=self.user,
            email_address='sender-condition@acme.test',
            provider='GOOGLE',
            access_token='token',
            refresh_token='refresh',
        )
        campaign.connected_account = account
        campaign.save(update_fields=['connected_account'])

        condition_step = SequenceStep.objects.create(
            organization=self.organization,
            campaign=campaign,
            step_order=1,
            channel_type='CONDITION_REPLY',
            delay_minutes=0,
        )
        SequenceStep.objects.create(
            organization=self.organization,
            campaign=campaign,
            step_order=2,
            channel_type='EMAIL',
            delay_minutes=0,
            template_subject='Should not send',
            template_body='x',
        )
        lead = Lead.objects.create(
            organization=self.organization,
            email='condition-lead@acme.test',
        )
        campaign_lead = CampaignLead.objects.create(
            organization=self.organization,
            campaign=campaign,
            lead=lead,
            current_step=condition_step,
            status='ACTIVE',
            next_execution_time=timezone.now() - timedelta(minutes=1),
            last_sent_message_id='mid-123',
        )

        with patch('campaigns.tasks.check_for_replies', return_value={'mid-123': 'thanks'}):
            process_active_leads_once(now=timezone.now())

        campaign_lead.refresh_from_db()
        self.assertEqual(campaign_lead.status, 'REPLIED')
        self.assertIsNone(campaign_lead.current_step)
        self.assertIsNone(campaign_lead.next_execution_time)

    def test_condition_reply_routes_to_yes_branch_when_configured(self):
        campaign = Campaign.objects.create(
            organization=self.organization,
            name='Condition reply yes branch',
            status='ACTIVE',
            settings={
                'steps': [
                    {'type': 'CONDITION_REPLY', 'condition_time': '1 day'},
                    {'type': 'EMAIL', 'subject': 'No path', 'body': 'no', 'condition_branch': 'no', 'condition_parent_index': 0},
                    {'type': 'EMAIL', 'subject': 'Yes path', 'body': 'yes', 'condition_branch': 'yes', 'condition_parent_index': 0},
                ]
            },
        )
        account = ConnectedEmailAccount.objects.create(
            organization=self.organization,
            connected_by=self.user,
            email_address='sender-condition-yes@acme.test',
            provider='GOOGLE',
            access_token='token',
            refresh_token='refresh',
        )
        campaign.connected_account = account
        campaign.save(update_fields=['connected_account'])

        condition_step = SequenceStep.objects.create(
            organization=self.organization,
            campaign=campaign,
            step_order=1,
            channel_type='CONDITION_REPLY',
            delay_minutes=0,
        )
        no_step = SequenceStep.objects.create(
            organization=self.organization,
            campaign=campaign,
            step_order=2,
            channel_type='EMAIL',
            delay_minutes=0,
            template_subject='No path',
            template_body='no',
        )
        yes_step = SequenceStep.objects.create(
            organization=self.organization,
            campaign=campaign,
            step_order=3,
            channel_type='EMAIL',
            delay_minutes=1,
            template_subject='Yes path',
            template_body='yes',
        )
        lead = Lead.objects.create(
            organization=self.organization,
            email='condition-yes@acme.test',
        )
        campaign_lead = CampaignLead.objects.create(
            organization=self.organization,
            campaign=campaign,
            lead=lead,
            current_step=condition_step,
            status='ACTIVE',
            next_execution_time=timezone.now() - timedelta(minutes=1),
            last_sent_message_id='yes-mid-123',
        )

        with patch('campaigns.tasks.check_for_replies', return_value={'yes-mid-123': 'thanks'}):
            process_active_leads_once(now=timezone.now())

        campaign_lead.refresh_from_db()
        self.assertEqual(campaign_lead.status, 'ACTIVE')
        self.assertEqual(campaign_lead.current_step_id, yes_step.id)
        self.assertNotEqual(campaign_lead.current_step_id, no_step.id)
        self.assertGreaterEqual(campaign_lead.next_execution_time, timezone.now())

    def test_condition_reply_routes_to_no_branch_and_skips_yes_branch(self):
        campaign = Campaign.objects.create(
            organization=self.organization,
            name='Condition reply no branch',
            status='ACTIVE',
            settings={
                'steps': [
                    {'type': 'CONDITION_REPLY', 'condition_time': '1 day'},
                    {'type': 'EMAIL', 'subject': 'No path', 'body': 'no', 'condition_branch': 'no', 'condition_parent_index': 0},
                    {'type': 'EMAIL', 'subject': 'Yes path', 'body': 'yes', 'condition_branch': 'yes', 'condition_parent_index': 0},
                ]
            },
        )
        account = ConnectedEmailAccount.objects.create(
            organization=self.organization,
            connected_by=self.user,
            email_address='sender-condition-no@acme.test',
            provider='GOOGLE',
            access_token='token',
            refresh_token='refresh',
        )
        campaign.connected_account = account
        campaign.save(update_fields=['connected_account'])

        condition_step = SequenceStep.objects.create(
            organization=self.organization,
            campaign=campaign,
            step_order=1,
            channel_type='CONDITION_REPLY',
            delay_minutes=0,
        )
        SequenceStep.objects.create(
            organization=self.organization,
            campaign=campaign,
            step_order=2,
            channel_type='EMAIL',
            delay_minutes=0,
            template_subject='No path',
            template_body='no',
        )
        SequenceStep.objects.create(
            organization=self.organization,
            campaign=campaign,
            step_order=3,
            channel_type='EMAIL',
            delay_minutes=0,
            template_subject='Yes path',
            template_body='yes',
        )
        lead = Lead.objects.create(
            organization=self.organization,
            email='condition-no@acme.test',
        )
        campaign_lead = CampaignLead.objects.create(
            organization=self.organization,
            campaign=campaign,
            lead=lead,
            current_step=condition_step,
            status='ACTIVE',
            next_execution_time=timezone.now() - timedelta(minutes=1),
            last_sent_message_id='no-mid-123',
        )

        with patch('campaigns.tasks.send_email_step.delay', side_effect=lambda cid, sid: send_email_step(cid, sid)):
            with patch('campaigns.tasks.check_for_replies', return_value={}):
                with patch('campaigns.tasks.send_gmail', return_value='no-path-msg') as mocked_send:
                    process_active_leads_once(now=timezone.now())

        campaign_lead.refresh_from_db()
        self.assertEqual(campaign_lead.status, 'FINISHED')
        self.assertEqual(campaign_lead.last_sent_message_id, 'no-path-msg')
        self.assertEqual(mocked_send.call_count, 1)
        self.assertEqual(mocked_send.call_args[0][2], 'No path')

    def test_condition_reply_finishes_when_no_reply_and_no_no_branch(self):
        campaign = Campaign.objects.create(
            organization=self.organization,
            name='Condition reply no-no-branch',
            status='ACTIVE',
            settings={
                'steps': [
                    {'type': 'CONDITION_REPLY', 'condition_time': '1 day'},
                    {'type': 'EMAIL', 'subject': 'Yes path', 'body': 'yes', 'condition_branch': 'yes', 'condition_parent_index': 0},
                ]
            },
        )
        account = ConnectedEmailAccount.objects.create(
            organization=self.organization,
            connected_by=self.user,
            email_address='sender-condition-nobranch@acme.test',
            provider='GOOGLE',
            access_token='token',
            refresh_token='refresh',
        )
        campaign.connected_account = account
        campaign.save(update_fields=['connected_account'])

        condition_step = SequenceStep.objects.create(
            organization=self.organization,
            campaign=campaign,
            step_order=1,
            channel_type='CONDITION_REPLY',
            delay_minutes=0,
        )
        SequenceStep.objects.create(
            organization=self.organization,
            campaign=campaign,
            step_order=2,
            channel_type='EMAIL',
            delay_minutes=0,
            template_subject='Yes path',
            template_body='yes',
        )
        lead = Lead.objects.create(
            organization=self.organization,
            email='condition-nobranch@acme.test',
        )
        campaign_lead = CampaignLead.objects.create(
            organization=self.organization,
            campaign=campaign,
            lead=lead,
            current_step=condition_step,
            status='ACTIVE',
            next_execution_time=timezone.now() - timedelta(minutes=1),
            last_sent_message_id='nobranch-mid-123',
        )

        with patch('campaigns.tasks.check_for_replies', return_value={}):
            process_active_leads_once(now=timezone.now())

        campaign_lead.refresh_from_db()
        self.assertEqual(campaign_lead.status, 'FINISHED')
        self.assertIsNone(campaign_lead.current_step_id)

    def test_condition_open_waits_for_window_before_routing_to_no_branch(self):
        campaign = Campaign.objects.create(
            organization=self.organization,
            name='Condition open wait flow',
            status='ACTIVE',
            settings={
                'steps': [
                    {'type': 'CONDITION_OPEN', 'condition_time': '1 day'},
                    {'type': 'EMAIL', 'subject': 'No path', 'body': 'no', 'condition_branch': 'no', 'condition_parent_index': 0},
                ]
            },
        )
        condition_step = SequenceStep.objects.create(
            organization=self.organization,
            campaign=campaign,
            step_order=1,
            channel_type='CONDITION_OPEN',
            delay_minutes=1440,
        )
        SequenceStep.objects.create(
            organization=self.organization,
            campaign=campaign,
            step_order=2,
            channel_type='EMAIL',
            delay_minutes=0,
            template_subject='No path',
            template_body='no',
        )
        lead = Lead.objects.create(
            organization=self.organization,
            email='condition-open@acme.test',
        )
        next_check = timezone.now() + timedelta(hours=1)
        campaign_lead = CampaignLead.objects.create(
            organization=self.organization,
            campaign=campaign,
            lead=lead,
            current_step=condition_step,
            status='ACTIVE',
            next_execution_time=next_check,
        )

        _execute_condition_event_step(campaign_lead, condition_step, event_detected=False, now=timezone.now())

        campaign_lead.refresh_from_db()
        self.assertEqual(campaign_lead.current_step_id, condition_step.id)
        self.assertEqual(campaign_lead.status, 'ACTIVE')
        self.assertEqual(campaign_lead.next_execution_time, next_check)

    def test_condition_click_waits_for_window_before_routing_to_no_branch(self):
        campaign = Campaign.objects.create(
            organization=self.organization,
            name='Condition click wait flow',
            status='ACTIVE',
            settings={
                'steps': [
                    {'type': 'CONDITION_CLICK', 'condition_time': '1 day'},
                    {'type': 'EMAIL', 'subject': 'No path', 'body': 'no', 'condition_branch': 'no', 'condition_parent_index': 0},
                ]
            },
        )
        condition_step = SequenceStep.objects.create(
            organization=self.organization,
            campaign=campaign,
            step_order=1,
            channel_type='CONDITION_CLICK',
            delay_minutes=1440,
        )
        SequenceStep.objects.create(
            organization=self.organization,
            campaign=campaign,
            step_order=2,
            channel_type='EMAIL',
            delay_minutes=0,
            template_subject='No path',
            template_body='no',
        )
        lead = Lead.objects.create(
            organization=self.organization,
            email='condition-click@acme.test',
        )
        next_check = timezone.now() + timedelta(hours=1)
        campaign_lead = CampaignLead.objects.create(
            organization=self.organization,
            campaign=campaign,
            lead=lead,
            current_step=condition_step,
            status='ACTIVE',
            next_execution_time=next_check,
        )

        _execute_condition_event_step(campaign_lead, condition_step, event_detected=False, now=timezone.now())

        campaign_lead.refresh_from_db()
        self.assertEqual(campaign_lead.current_step_id, condition_step.id)
        self.assertEqual(campaign_lead.status, 'ACTIVE')
        self.assertEqual(campaign_lead.next_execution_time, next_check)

    @override_settings(ENABLE_AUTO_REPLY_DETECTION=True)
    def test_poll_replies_defers_terminal_status_when_reply_yes_branch_exists(self):
        campaign = Campaign.objects.create(
            organization=self.organization,
            name='Reply polling defer branch',
            status='ACTIVE',
            settings={
                'steps': [
                    {'type': 'EMAIL', 'subject': 'First', 'body': 'x'},
                    {'type': 'CONDITION_REPLY', 'condition_time': '1 day'},
                    {'type': 'EMAIL', 'subject': 'Yes path', 'body': 'yes', 'condition_branch': 'yes', 'condition_parent_index': 1},
                ]
            },
        )
        account = ConnectedEmailAccount.objects.create(
            organization=self.organization,
            connected_by=self.user,
            email_address='sender-poll-branch@acme.test',
            provider='GOOGLE',
            access_token='token',
            refresh_token='refresh',
        )
        campaign.connected_account = account
        campaign.save(update_fields=['connected_account'])

        condition_step = SequenceStep.objects.create(
            organization=self.organization,
            campaign=campaign,
            step_order=2,
            channel_type='CONDITION_REPLY',
            delay_minutes=0,
        )
        lead = Lead.objects.create(
            organization=self.organization,
            email='poll-branch@acme.test',
        )
        campaign_lead = CampaignLead.objects.create(
            organization=self.organization,
            campaign=campaign,
            lead=lead,
            current_step=condition_step,
            status='ACTIVE',
            next_execution_time=timezone.now() + timedelta(hours=1),
            last_sent_message_id='poll-mid-123',
        )

        with patch('campaigns.tasks.check_for_replies', return_value={'poll-mid-123': 'replied'}):
            poll_gmail_for_replies()

        campaign_lead.refresh_from_db()
        self.assertEqual(campaign_lead.status, 'ACTIVE')

    @override_settings(ENABLE_AUTO_REPLY_DETECTION=True)
    def test_poll_replies_handles_finished_leads(self):
        campaign = Campaign.objects.create(
            organization=self.organization,
            name='Reply polling finished',
            status='COMPLETED',
        )
        account = ConnectedEmailAccount.objects.create(
            organization=self.organization,
            connected_by=self.user,
            email_address='sender-finished@acme.test',
            provider='GOOGLE',
            access_token='token',
            refresh_token='refresh',
        )
        campaign.connected_account = account
        campaign.save(update_fields=['connected_account'])
        lead = Lead.objects.create(
            organization=self.organization,
            email='finished-lead@acme.test',
        )
        campaign_lead = CampaignLead.objects.create(
            organization=self.organization,
            campaign=campaign,
            lead=lead,
            status='FINISHED',
            last_sent_message_id='finished-mid',
        )

        with patch('campaigns.tasks.check_for_replies', return_value={'finished-mid': 'replied'}):
            poll_gmail_for_replies()

        campaign_lead.refresh_from_db()
        self.assertEqual(campaign_lead.status, 'REPLIED')

    @override_settings(ENABLE_AUTO_BOUNCE_DETECTION=True)
    def test_check_imap_bounces_marks_matching_campaign_lead_bounced(self):
        account = ConnectedEmailAccount.objects.create(
            organization=self.organization,
            connected_by=self.user,
            email_address='sender-bounce@acme.test',
            provider='GOOGLE',
            access_token='token',
            refresh_token='refresh',
        )
        campaign = Campaign.objects.create(
            organization=self.organization,
            name='Bounce polling flow',
            status='ACTIVE',
            connected_account=account,
        )
        step = SequenceStep.objects.create(
            organization=self.organization,
            campaign=campaign,
            step_order=1,
            channel_type='EMAIL',
            delay_minutes=0,
            template_subject='Hello',
            template_body='World',
        )
        lead = Lead.objects.create(
            organization=self.organization,
            email='bounced-lead@acme.test',
        )
        campaign_lead = CampaignLead.objects.create(
            organization=self.organization,
            campaign=campaign,
            lead=lead,
            current_step=step,
            status='ACTIVE',
            next_execution_time=timezone.now() + timedelta(minutes=10),
            last_sent_message_id='sent-mid-1',
        )

        with patch(
            'campaigns.tasks.find_gmail_bounce_candidates',
            return_value=[{'message_id': 'bounce-1', 'failed_recipients': ['bounced-lead@acme.test']}],
        ) as mocked_find:
            with patch('campaigns.tasks.mark_gmail_message_as_read') as mocked_mark_read:
                with patch('campaigns.tasks.notify_email_bounced') as mocked_notify:
                    result = check_imap_bounces()

        campaign_lead.refresh_from_db()
        self.assertEqual(campaign_lead.status, 'BOUNCED')
        self.assertIsNone(campaign_lead.current_step)
        self.assertIsNone(campaign_lead.next_execution_time)
        self.assertIn('marked 1 campaign leads as BOUNCED', result)
        mocked_find.assert_called_once_with(account)
        mocked_mark_read.assert_called_once_with(account, 'bounce-1')
        mocked_notify.assert_called_once_with(self.organization.id, 'bounced-lead@acme.test')

    @override_settings(ENABLE_AUTO_BOUNCE_DETECTION=True)
    def test_check_imap_bounces_marks_unmatched_message_as_read(self):
        account = ConnectedEmailAccount.objects.create(
            organization=self.organization,
            connected_by=self.user,
            email_address='sender-unmatched@acme.test',
            provider='GOOGLE',
            access_token='token',
            refresh_token='refresh',
        )
        campaign = Campaign.objects.create(
            organization=self.organization,
            name='Bounce unmatched flow',
            status='ACTIVE',
            connected_account=account,
        )
        SequenceStep.objects.create(
            organization=self.organization,
            campaign=campaign,
            step_order=1,
            channel_type='EMAIL',
            delay_minutes=0,
            template_subject='Hello',
            template_body='World',
        )
        lead = Lead.objects.create(
            organization=self.organization,
            email='safe-lead@acme.test',
        )
        campaign_lead = CampaignLead.objects.create(
            organization=self.organization,
            campaign=campaign,
            lead=lead,
            status='ACTIVE',
            last_sent_message_id='sent-mid-2',
        )

        with patch(
            'campaigns.tasks.find_gmail_bounce_candidates',
            return_value=[{'message_id': 'bounce-404', 'failed_recipients': ['missing@acme.test']}],
        ):
            with patch('campaigns.tasks.mark_gmail_message_as_read') as mocked_mark_read:
                with patch('campaigns.tasks.notify_email_bounced') as mocked_notify:
                    result = check_imap_bounces()

        campaign_lead.refresh_from_db()
        self.assertEqual(campaign_lead.status, 'ACTIVE')
        self.assertIn('marked 0 campaign leads as BOUNCED', result)
        mocked_mark_read.assert_called_once_with(account, 'bounce-404')
        mocked_notify.assert_not_called()

    @override_settings(ENABLE_AUTO_BOUNCE_DETECTION=True)
    def test_check_imap_bounces_supports_custom_imap_accounts(self):
        account = ConnectedEmailAccount.objects.create(
            organization=self.organization,
            connected_by=self.user,
            email_address='custom-bounce@acme.test',
            provider='CUSTOM',
            smtp_host='smtp.acme.test',
            smtp_port=587,
            smtp_username='smtp-user',
            smtp_password='smtp-pass',
            smtp_use_tls=True,
            smtp_use_ssl=False,
            imap_host='imap.acme.test',
            imap_port=993,
            imap_username='imap-user',
            imap_password='imap-pass',
            imap_use_ssl=True,
        )
        campaign = Campaign.objects.create(
            organization=self.organization,
            name='Custom bounce polling flow',
            status='ACTIVE',
            connected_account=account,
        )
        step = SequenceStep.objects.create(
            organization=self.organization,
            campaign=campaign,
            step_order=1,
            channel_type='EMAIL',
            delay_minutes=0,
            template_subject='Hello',
            template_body='World',
        )
        lead = Lead.objects.create(
            organization=self.organization,
            email='custom-bounced@acme.test',
        )
        campaign_lead = CampaignLead.objects.create(
            organization=self.organization,
            campaign=campaign,
            lead=lead,
            current_step=step,
            status='ACTIVE',
            next_execution_time=timezone.now() + timedelta(minutes=10),
            last_sent_message_id='custom-mid-1',
        )

        with patch(
            'campaigns.tasks.find_imap_bounce_candidates',
            return_value=[{'message_id': 'imap-bounce-1', 'failed_recipients': ['custom-bounced@acme.test']}],
        ) as mocked_find:
            with patch('campaigns.tasks.mark_imap_message_as_read') as mocked_mark_read:
                result = check_imap_bounces()

        campaign_lead.refresh_from_db()
        self.assertEqual(campaign_lead.status, 'BOUNCED')
        self.assertIsNone(campaign_lead.current_step)
        self.assertIn('marked 1 campaign leads as BOUNCED', result)
        mocked_find.assert_called_once_with(account)
        mocked_mark_read.assert_called_once_with(account, 'imap-bounce-1')

    @override_settings(ENABLE_AUTO_BOUNCE_DETECTION=True)
    def test_check_imap_bounces_keeps_message_unread_when_processing_fails(self):
        account = ConnectedEmailAccount.objects.create(
            organization=self.organization,
            connected_by=self.user,
            email_address='sender-processing-error@acme.test',
            provider='GOOGLE',
            access_token='token',
            refresh_token='refresh',
        )
        campaign = Campaign.objects.create(
            organization=self.organization,
            name='Bounce processing error flow',
            status='ACTIVE',
            connected_account=account,
        )
        SequenceStep.objects.create(
            organization=self.organization,
            campaign=campaign,
            step_order=1,
            channel_type='EMAIL',
            delay_minutes=0,
            template_subject='Hello',
            template_body='World',
        )
        lead = Lead.objects.create(
            organization=self.organization,
            email='error-lead@acme.test',
        )
        CampaignLead.objects.create(
            organization=self.organization,
            campaign=campaign,
            lead=lead,
            status='ACTIVE',
            last_sent_message_id='sent-mid-error',
        )

        with patch(
            'campaigns.tasks.find_gmail_bounce_candidates',
            return_value=[{'message_id': 'bounce-error', 'failed_recipients': ['error-lead@acme.test']}],
        ):
            with patch(
                'campaigns.tasks._mark_matching_account_leads_bounced',
                side_effect=RuntimeError('db unavailable'),
            ):
                with patch('campaigns.tasks.mark_gmail_message_as_read') as mocked_mark_read:
                    result = check_imap_bounces()

        self.assertIn('marked 0 campaign leads as BOUNCED', result)
        mocked_mark_read.assert_not_called()

    @override_settings(CELERY_TASK_ALWAYS_EAGER=False)
    def test_launch_action_activates_campaign_and_triggers_processing(self):
        campaign = Campaign.objects.create(
            organization=self.organization,
            name='Launch flow',
            status='DRAFT',
        )
        lead = Lead.objects.create(
            organization=self.organization,
            email='launchlead@acme.test',
        )
        CampaignLead.objects.create(
            organization=self.organization,
            campaign=campaign,
            lead=lead,
            status='ENROLLED',
        )

        with patch('campaigns.tasks.process_active_leads.delay') as mocked_delay:
            response = self.client.post(f'/api/v1/campaigns/{campaign.id}/launch/', {}, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, 'ACTIVE')
        mocked_delay.assert_called_once()

    def test_launch_requires_enrolled_leads(self):
        campaign = Campaign.objects.create(
            organization=self.organization,
            name='Launch flow empty',
            status='DRAFT',
        )
        response = self.client.post(f'/api/v1/campaigns/{campaign.id}/launch/', {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_pause_action_pauses_active_campaign(self):
        campaign = Campaign.objects.create(
            organization=self.organization,
            name='Pause active campaign',
            status='ACTIVE',
        )

        response = self.client.post(f'/api/v1/campaigns/{campaign.id}/pause/', {}, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, 'PAUSED')
        self.assertEqual(response.data['status'], 'PAUSED')

    def test_pause_rejects_non_active_campaign(self):
        campaign = Campaign.objects.create(
            organization=self.organization,
            name='Pause draft campaign',
            status='DRAFT',
        )

        response = self.client.post(f'/api/v1/campaigns/{campaign.id}/pause/', {}, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, 'DRAFT')

    @override_settings(CELERY_TASK_ALWAYS_EAGER=False)
    def test_resume_action_activates_paused_campaign_and_triggers_processing(self):
        campaign = Campaign.objects.create(
            organization=self.organization,
            name='Resume paused campaign',
            status='PAUSED',
        )

        with patch('campaigns.tasks.process_active_leads.delay') as mocked_delay:
            response = self.client.post(f'/api/v1/campaigns/{campaign.id}/resume/', {}, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, 'ACTIVE')
        self.assertEqual(response.data['status'], 'ACTIVE')
        mocked_delay.assert_called_once()

    def test_resume_rejects_non_paused_campaign(self):
        campaign = Campaign.objects.create(
            organization=self.organization,
            name='Resume active campaign',
            status='ACTIVE',
        )

        response = self.client.post(f'/api/v1/campaigns/{campaign.id}/resume/', {}, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, 'ACTIVE')

    def test_condition_time_is_mapped_to_delay_minutes(self):
        payload = {
            'name': 'Condition delay mapping',
            'status': 'DRAFT',
            'settings': {
                'steps': [
                    {'type': 'CONDITION_REPLY', 'condition_time': '2 days'},
                ],
            },
            'steps': [
                {'type': 'CONDITION_REPLY', 'condition_time': '2 days'},
            ],
        }
        response = self.client.post('/api/v1/campaigns/', payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        campaign = Campaign.objects.get(id=response.data['id'])
        step = campaign.steps.first()
        self.assertIsNotNone(step)
        self.assertEqual(step.delay_minutes, 2880)

    def test_launch_rejects_sender_account_owned_by_another_user(self):
        teammate = User.objects.create_user(
            email='teammate3@acme.test',
            password='StrongPass123!',
            organization=self.organization,
            role='USER',
        )
        teammate_account = ConnectedEmailAccount.objects.create(
            organization=self.organization,
            connected_by=teammate,
            email_address='teammate3@acme.test',
            provider='GOOGLE',
            access_token='token',
            refresh_token='refresh',
        )
        campaign = Campaign.objects.create(
            organization=self.organization,
            name='Launch with foreign sender',
            status='DRAFT',
            connected_account=teammate_account,
        )
        lead = Lead.objects.create(
            organization=self.organization,
            email='launch-owner-check@acme.test',
        )
        CampaignLead.objects.create(
            organization=self.organization,
            campaign=campaign,
            lead=lead,
            status='ENROLLED',
        )

        response = self.client.post(f'/api/v1/campaigns/{campaign.id}/launch/', {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, 'DRAFT')

    @override_settings(GEMINI_API_KEY='')
    def test_ai_generate_returns_fallback_when_key_missing(self):
        response = self.client.post(
            '/api/v1/campaigns/ai-generate/',
            {'prompt': 'Write an outreach email'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data.get('fallback'))
        self.assertIn('SUBJECT:', response.data.get('generated', ''))

    @override_settings(GEMINI_API_KEY='')
    def test_ai_generate_requires_authentication(self):
        self.client.force_authenticate(user=None)

        response = self.client.post(
            '/api/v1/campaigns/ai-generate/',
            {'prompt': 'Write an outreach email'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_email_webhook_logs_processing_errors(self):
        with patch('campaigns.views.CampaignLead.objects.filter', side_effect=RuntimeError('boom')):
            with self.assertLogs('campaigns.views', level='ERROR') as logs:
                response = self.client.post(
                    '/api/v1/webhooks/email/',
                    {'event': 'open', 'email': 'lead@acme.test'},
                    format='json',
                )

        self.assertEqual(
            response.status_code, 
            status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        self.assertTrue(
            any('Webhook processing error for event=open email=lead@acme.test' in entry for entry in logs.output)
        )

    def test_email_webhook_bounce_marks_lead_bounced_and_stops_sequence(self):
        campaign = Campaign.objects.create(
            organization=self.organization,
            name='Webhook bounce flow',
            status='ACTIVE',
        )
        step = SequenceStep.objects.create(
            organization=self.organization,
            campaign=campaign,
            step_order=1,
            channel_type='EMAIL',
            delay_minutes=0,
            template_subject='Hi',
            template_body='Body',
        )
        lead = Lead.objects.create(
            organization=self.organization,
            email='webhook-bounce@acme.test',
        )
        campaign_lead = CampaignLead.objects.create(
            organization=self.organization,
            campaign=campaign,
            lead=lead,
            current_step=step,
            status='ACTIVE',
            next_execution_time=timezone.now() + timedelta(minutes=5),
        )

        with patch('campaigns.tasks.notify_email_bounced') as mocked_notify:
            response = self.client.post(
                '/api/v1/webhooks/email/',
                {'event': 'bounce', 'email': 'webhook-bounce@acme.test'},
                format='json',
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        campaign_lead.refresh_from_db()
        self.assertEqual(campaign_lead.status, 'BOUNCED')
        self.assertIsNone(campaign_lead.current_step)
        self.assertIsNone(campaign_lead.next_execution_time)
        mocked_notify.assert_called_once_with(self.organization.id, 'webhook-bounce@acme.test')

    def test_email_webhook_persists_bounce_metadata(self):
        campaign = Campaign.objects.create(
            organization=self.organization,
            name='Bounce metadata flow',
            status='ACTIVE',
        )
        lead = Lead.objects.create(
            organization=self.organization,
            email='bounce@acme.test',
        )
        campaign_lead = CampaignLead.objects.create(
            organization=self.organization,
            campaign=campaign,
            lead=lead,
            status='ACTIVE',
            last_sent_message_id='msg-123',
        )

        response = self.client.post(
            '/api/v1/webhooks/email/',
            {
                'event': 'bounce',
                'email': 'bounce@acme.test',
                'message_id': 'msg-123',
                'bounce': {
                    'type': 'soft',
                    'code': 'mailbox_full',
                    'reason': 'Mailbox full',
                },
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        campaign_lead.refresh_from_db()
        self.assertEqual(campaign_lead.status, 'BOUNCED')
        self.assertEqual(campaign_lead.bounce_type, 'soft')
        self.assertEqual(campaign_lead.bounce_code, 'mailbox_full')
        self.assertEqual(campaign_lead.bounce_reason, 'Mailbox full')

    def test_email_webhook_does_not_bounce_finished_lead_without_message_id(self):
        campaign = Campaign.objects.create(
            organization=self.organization,
            name='Finished lead webhook safety',
            status='ACTIVE',
        )
        lead = Lead.objects.create(
            organization=self.organization,
            email='finished-webhook@acme.test',
        )
        campaign_lead = CampaignLead.objects.create(
            organization=self.organization,
            campaign=campaign,
            lead=lead,
            status='FINISHED',
            last_sent_message_id='finished-mid-2',
        )

        response = self.client.post(
            '/api/v1/webhooks/email/',
            {'event': 'bounce', 'email': 'finished-webhook@acme.test'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        campaign_lead.refresh_from_db()
        self.assertEqual(campaign_lead.status, 'FINISHED')

    def test_dashboard_analytics_isolates_data_by_tenant(self):
        org2 = Organization.objects.create(name='Other Corp')
        other_user = User.objects.create_user(
            email='other@othercorp.test',
            password='StrongPass123!',
            organization=org2,
            role='ADMIN',
        )
        other_campaign = Campaign.objects.create(
            organization=org2,
            name='Other Corp Campaign',
            status='ACTIVE',
        )
        other_lead = Lead.objects.create(
            organization=org2,
            email='otherlead@othercorp.test',
        )
        CampaignLead.objects.create(
            organization=org2,
            campaign=other_campaign,
            lead=other_lead,
            status='REPLIED',
        )

        # Acme user should see zero data (org2's data must not leak)
        response = self.client.get('/api/v1/analytics/dashboard/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['total_leads'], 0)
        self.assertEqual(response.data['active_campaigns'], 0)
        self.assertEqual(response.data['emails_sent'], 0)
        self.assertEqual(response.data['replied'], 0)
        self.assertEqual(response.data['campaign_stats'], [])

        # org2 user should only see their own data
        self.client.force_authenticate(other_user)
        response = self.client.get('/api/v1/analytics/dashboard/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['total_leads'], 1)
        self.assertEqual(response.data['active_campaigns'], 1)
        self.assertEqual(response.data['replied'], 1)

    def test_dashboard_analytics_requires_authentication(self):
        self.client.force_authenticate(user=None)
        response = self.client.get('/api/v1/analytics/dashboard/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_unsubscribe_get_shows_confirmation_without_updating_lead(self):
        lead = Lead.objects.create(
            organization=self.organization,
            email='unsubscribe@acme.test',
        )
        token = generate_unsubscribe_token(lead.id)

        response = self.client.get(f'/api/v1/unsubscribe/{lead.id}/{token}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('Confirm unsubscribe', response.content.decode('utf-8'))
        self.assertIn('method="post"', response.content.decode('utf-8'))

        lead.refresh_from_db()
        self.assertFalse(lead.global_unsubscribe)

    def test_unsubscribe_post_marks_lead_unsubscribed(self):
        lead = Lead.objects.create(
            organization=self.organization,
            email='unsubscribe@acme.test',
        )
        token = generate_unsubscribe_token(lead.id)

        response = self.client.post(f'/api/v1/unsubscribe/{lead.id}/{token}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('You have been unsubscribed', response.content.decode('utf-8'))

        lead.refresh_from_db()
        self.assertTrue(lead.global_unsubscribe)

    def test_unsubscribe_view_rejects_invalid_token(self):
        lead = Lead.objects.create(
            organization=self.organization,
            email='badtoken@acme.test',
        )
        response = self.client.get(f'/api/v1/unsubscribe/{lead.id}/invalidtoken/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        lead.refresh_from_db()
        self.assertFalse(lead.global_unsubscribe)

    def test_send_email_step_skips_unsubscribed_leads(self):
        campaign = Campaign.objects.create(
            organization=self.organization,
            name='Unsubscribe skip test',
            status='ACTIVE',
        )
        email_step = SequenceStep.objects.create(
            organization=self.organization,
            campaign=campaign,
            step_order=1,
            channel_type='EMAIL',
            delay_minutes=0,
            template_subject='Hello',
            template_body='Hi there',
        )
        lead = Lead.objects.create(
            organization=self.organization,
            email='blocked@acme.test',
            global_unsubscribe=True,
        )
        campaign_lead = CampaignLead.objects.create(
            organization=self.organization,
            campaign=campaign,
            lead=lead,
            current_step=email_step,
            status='ACTIVE',
            next_execution_time=timezone.now() - timedelta(minutes=1),
        )

        send_email_step(campaign_lead.id, email_step.id)

        campaign_lead.refresh_from_db()
        self.assertEqual(campaign_lead.status, 'FINISHED')
        self.assertIsNone(campaign_lead.current_step)
        self.assertIsNone(campaign_lead.next_execution_time)

    def test_send_email_step_uses_custom_smtp_account(self):
        account = ConnectedEmailAccount.objects.create(
            organization=self.organization,
            connected_by=self.user,
            email_address='custom-mailbox@acme.test',
            provider='CUSTOM',
            smtp_host='smtp.acme.test',
            smtp_port=587,
            smtp_username='smtp-user',
            smtp_password='smtp-pass',
            smtp_use_tls=True,
            smtp_use_ssl=False,
            imap_host='imap.acme.test',
            imap_port=993,
            imap_username='imap-user',
            imap_password='imap-pass',
            imap_use_ssl=True,
        )
        campaign = Campaign.objects.create(
            organization=self.organization,
            name='Custom SMTP flow',
            status='ACTIVE',
            connected_account=account,
        )
        email_step = SequenceStep.objects.create(
            organization=self.organization,
            campaign=campaign,
            step_order=1,
            channel_type='EMAIL',
            delay_minutes=0,
            template_subject='Hello',
            template_body='Hi there',
        )
        lead = Lead.objects.create(
            organization=self.organization,
            email='custom-recipient@acme.test',
        )
        campaign_lead = CampaignLead.objects.create(
            organization=self.organization,
            campaign=campaign,
            lead=lead,
            current_step=email_step,
            status='ACTIVE',
            next_execution_time=timezone.now() - timedelta(minutes=1),
        )

        with patch('campaigns.tasks.send_smtp_email', return_value='smtp-msg-1') as mocked_send:
            send_email_step(campaign_lead.id, email_step.id)

        campaign_lead.refresh_from_db()
        self.assertEqual(campaign_lead.last_sent_message_id, 'smtp-msg-1')
        self.assertEqual(campaign_lead.status, 'FINISHED')
        mocked_send.assert_called_once()

    def test_send_email_step_skips_blocked_domain_leads(self):
        BlockedDomain.objects.create(
            organization=self.organization,
            domain='blocked.test',
        )
        account = ConnectedEmailAccount.objects.create(
            organization=self.organization,
            connected_by=self.user,
            email_address='sender@acme.test',
            provider='GOOGLE',
            access_token='token',
            refresh_token='refresh',
        )
        campaign = Campaign.objects.create(
            organization=self.organization,
            name='Blocked domain skip test',
            status='ACTIVE',
            connected_account=account,
        )
        email_step = SequenceStep.objects.create(
            organization=self.organization,
            campaign=campaign,
            step_order=1,
            channel_type='EMAIL',
            delay_minutes=0,
            template_subject='Hello',
            template_body='Hi there',
        )
        lead = Lead.objects.create(
            organization=self.organization,
            email='lead@sub.blocked.test',
        )
        campaign_lead = CampaignLead.objects.create(
            organization=self.organization,
            campaign=campaign,
            lead=lead,
            current_step=email_step,
            status='ACTIVE',
            next_execution_time=timezone.now() - timedelta(minutes=1),
        )

        with patch('campaigns.tasks.send_gmail') as mocked_send:
            send_email_step(campaign_lead.id, email_step.id)

        campaign_lead.refresh_from_db()
        campaign.refresh_from_db()
        self.assertEqual(campaign_lead.status, 'SKIPPED')
        self.assertIsNone(campaign_lead.current_step)
        self.assertIsNone(campaign_lead.next_execution_time)
        self.assertEqual(campaign.status, 'COMPLETED')
        mocked_send.assert_not_called()


@override_settings(
    GOOGLE_CLIENT_ID='test-google-client-id',
    GOOGLE_CLIENT_SECRET='test-google-client-secret',
    GOOGLE_REDIRECT_URI='https://example.test/api/v1/auth/google/callback',
    GOOGLE_SCOPES=['https://www.googleapis.com/auth/gmail.send'],
)
class GoogleOAuthStateTests(APITestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name='OAuth Org')
        self.user = User.objects.create_user(
            email='oauth-owner@acme.test',
            password='StrongPass123!',
            organization=self.organization,
            role='ADMIN',
        )
        self.client.force_authenticate(self.user)

    def test_login_view_signs_oauth_state(self):
        response = self.client.get(
            '/api/v1/auth/google/login',
            {'frontend_origin': 'https://app.example.test'},
        )

        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        redirect_url = response['Location']
        parsed = urlparse(redirect_url)
        params = parse_qs(parsed.query)
        state = params['state'][0]

        state_data = signing.loads(
            state,
            salt='leadorbit-google-oauth-state',
            max_age=600,
        )
        self.assertEqual(state_data['user_id'], str(self.user.id))
        self.assertEqual(state_data['org_id'], str(self.organization.id))
        self.assertEqual(state_data['frontend_origin'], 'https://app.example.test')

    def test_callback_rejects_tampered_state_and_accepts_signed_state(self):
        with patch('campaigns.google_auth_views.requests.post') as mock_post, patch(
            'campaigns.google_auth_views.requests.get'
        ) as mock_get:
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {
                'access_token': 'access-token',
                'refresh_token': 'refresh-token',
                'expires_in': 3600,
            }
            mock_get.return_value.json.return_value = {'email': 'sender@example.test'}

            signed_state = signing.dumps(
                {
                    'user_id': str(self.user.id),
                    'org_id': str(self.organization.id),
                    'frontend_origin': 'https://app.example.test',
                },
                salt='leadorbit-google-oauth-state',
            )
            response = self.client.get(
                '/api/v1/auth/google/callback',
                {'code': 'authorization-code', 'state': signed_state},
            )

        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        self.assertIn('google_auth=connected', response['Location'])
        self.assertTrue(
            ConnectedEmailAccount.objects.filter(
                organization=self.organization,
                connected_by=self.user,
                provider='GOOGLE',
                email_address='sender@example.test',
            ).exists()
        )

        tampered_state = signed_state[:-1] + ('x' if signed_state[-1] != 'x' else 'y')
        response = self.client.get(
            '/api/v1/auth/google/callback',
            {'code': 'authorization-code', 'state': tampered_state},
        )

        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        self.assertIn('google_auth=error', response['Location'])
        self.assertIn('reason=no_user', response['Location'])
