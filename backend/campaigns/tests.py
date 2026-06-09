from datetime import timedelta
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from campaigns.models import Campaign, CampaignLead, ConnectedEmailAccount, SequenceStep
from campaigns.tasks import (
    _get_campaign_steps,
    poll_gmail_for_replies,
    process_active_leads,
    process_active_leads_once,
    send_email_step,
)
from campaigns.utils import generate_unsubscribe_token
from leads.models import Lead
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
