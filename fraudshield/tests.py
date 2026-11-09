from unittest.mock import patch

from django.contrib.auth.models import User
from rest_framework.test import APITestCase

from .models import FraudAlert, PaymentGateway, Transaction


class TransactionApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user('alice', password='pw12345!')
        self.other = User.objects.create_user('bob', password='pw12345!')
        PaymentGateway.objects.create(name='Stripe', api_key='sk_test', cost_per_transaction='0.30', latency=0.3)
        self.client.force_authenticate(self.user)

    def pay(self, amount='10.00', **headers):
        return self.client.post(
            '/api/transactions/',
            {'amount': amount, 'currency': 'usd', 'merchant': 'shop', 'stripe_token': 'tok'},
            format='json', **headers,
        )

    def test_requires_auth(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get('/api/transactions/').status_code, 401)

    @patch('fraudshield.views.stripe.Charge.create')
    def test_successful_payment(self, charge):
        r = self.pay()
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data['transaction']['status'], 'completed')
        charge.assert_called_once()

    @patch('fraudshield.views.stripe.Charge.create', side_effect=RuntimeError('declined'))
    def test_failed_charge_recorded(self, _):
        r = self.pay()
        self.assertEqual(r.status_code, 402)
        self.assertEqual(Transaction.objects.get().status, 'failed')

    @patch('fraudshield.views.stripe.Charge.create')
    def test_idempotency_prevents_double_charge(self, charge):
        self.pay(HTTP_IDEMPOTENCY_KEY='k1')
        r = self.pay(HTTP_IDEMPOTENCY_KEY='k1')
        self.assertTrue(r.data['replayed'])
        self.assertEqual(charge.call_count, 1)
        self.assertEqual(Transaction.objects.count(), 1)

    @patch('fraudshield.views.stripe.Charge.create')
    def test_flagged_payment_is_not_charged(self, charge):
        with patch('fraudshield.views.FraudDetector.detect_anomaly', return_value=(0.95, 'High anomaly score')):
            r = self.pay()
        self.assertEqual(r.status_code, 202)
        charge.assert_not_called()
        self.assertEqual(FraudAlert.objects.count(), 1)

    def test_cannot_see_other_users_transactions(self):
        Transaction.objects.create(user=self.other, amount='5', merchant='x', status='completed')
        self.assertEqual(len(self.client.get('/api/transactions/').data), 0)

    def test_rejects_bad_amount(self):
        self.assertEqual(self.pay('-5').status_code, 400)
        self.assertEqual(self.pay('abc').status_code, 400)


import json

from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.test import TestCase, TransactionTestCase

from .dashboard_data import snapshot
from .routing import websocket_urlpatterns


class DashboardTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('alice', password='pw12345!')
        self.gw = PaymentGateway.objects.create(name='Sim-A', api_key='x', cost_per_transaction='0.2')

    def test_snapshot_aggregates(self):
        Transaction.objects.create(user=self.user, amount='10', merchant='<b>shop</b>', gateway=self.gw, status='completed')
        t = Transaction.objects.create(user=self.user, amount='99', merchant='bob', gateway=self.gw, status='flagged')
        FraudAlert.objects.create(transaction=t, score=0.9, reason='x')
        s = snapshot()
        self.assertEqual(s['kpis']['total'], 2)
        self.assertEqual(s['kpis']['flagged'], 1)
        self.assertEqual(s['kpis']['approval_rate'], 0.5)
        self.assertEqual(s['gateways'][0]['completed'], 1)
        self.assertEqual(len(s['alerts']), 1)
        self.assertEqual(sum(b[0] for b in s['series']['buckets']), 2)
        self.assertEqual(len(s['graph']), 2)

    def test_page_requires_staff(self):
        self.assertEqual(self.client.get('/dashboard/').status_code, 302)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get('/dashboard/').status_code, 302)  # not staff
        self.user.is_staff = True
        self.user.save()
        self.assertEqual(self.client.get('/dashboard/').status_code, 200)


class DashboardSocketTests(TransactionTestCase):
    async def _connect(self, user):
        comm = WebsocketCommunicator(URLRouter(websocket_urlpatterns), '/ws/dashboard/')
        comm.scope['user'] = user
        ok, code = await comm.connect()
        return comm, ok, code

    async def test_rejects_non_staff(self):
        from django.contrib.auth.models import AnonymousUser
        comm, ok, _ = await self._connect(AnonymousUser())
        self.assertFalse(ok)

    async def test_staff_gets_snapshot(self):
        from channels.db import database_sync_to_async
        staff = await database_sync_to_async(User.objects.create_user)('boss', password='x', is_staff=True)
        comm, ok, _ = await self._connect(staff)
        self.assertTrue(ok)
        msg = json.loads(await comm.receive_from(timeout=5))
        self.assertEqual(msg['type'], 'snapshot')
        await comm.disconnect()
