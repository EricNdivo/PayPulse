import asyncio
import json

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from .dashboard_data import fingerprint, snapshot
from .models import FraudAlert, Transaction


@database_sync_to_async
def _snapshot(user):
    txs = Transaction.objects.filter(user=user).order_by('-created_at')[:10]
    alerts = (FraudAlert.objects.filter(transaction__user=user)
              .select_related('transaction').order_by('-created_at')[:10])
    return {
        'transactions': [
            {'id': str(t.id), 'amount': float(t.amount), 'status': t.status, 'merchant': t.merchant}
            for t in txs
        ],
        'fraud_alerts': [
            {'transaction_id': str(a.transaction_id), 'score': a.score, 'reason': a.reason}
            for a in alerts
        ],
    }


class TransactionConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        user = self.scope.get('user')
        if not user or not user.is_authenticated:
            await self.close(code=4401)
            return
        await self.accept()
        await self.send(text_data=json.dumps({'message': 'Connected to PayPulse'}))

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            return
        if data.get('action') == 'subscribe_transactions':
            await self.send(text_data=json.dumps(await _snapshot(self.scope['user'])))


class DashboardConsumer(AsyncWebsocketConsumer):
    """Staff-only live feed. Polls a cheap fingerprint each second and pushes a fresh snapshot on change.

    Polling (rather than channel-layer group sends) means traffic from *other processes*
    (e.g. `manage.py simulate`) shows up even with the in-memory channel layer.
    """
    POLL_SECONDS = 1.0

    async def connect(self):
        user = self.scope.get('user')
        if not user or not user.is_authenticated or not user.is_staff:
            await self.close(code=4403)
            return
        await self.accept()
        self._task = asyncio.create_task(self._pump())

    async def disconnect(self, code):
        task = getattr(self, '_task', None)
        if task:
            task.cancel()

    async def _pump(self):
        last = None
        while True:
            fp = await database_sync_to_async(fingerprint)()
            if fp != last:
                last = fp
                await self.send(text_data=json.dumps(await database_sync_to_async(snapshot)()))
            await asyncio.sleep(self.POLL_SECONDS)
