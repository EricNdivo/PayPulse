from channels.generic.websocket import AsyncWebsocketConsumer
import json
from .models import Transaction, FraudAlert

class TransactionConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        await self.accept()
        await self.send(text_data=json.dumps({"message": "Connected to PayPulse"}))

    async def receive(self, text_data):
        data = json.loads(text_data)
        if data.get('action') == 'subscribe_transactions':
            transactions = Transaction.objects.order_by('-created_at')[:10]
            alerts = FraudAlert.objects.order_by('-created_at')[:10]
            await self.send(text_data=json.dumps({
                "transactions": [
                    {"id": str(t.id), "amount": float(t.amount), "status": t.status, "merchant": t.merchant}
                    for t in transactions
                ],
                "fraud_alerts": [
                    {"transaction_id": str(a.transaction.id), "score": a.score, "reason": a.reason}
                    for a in alerts
                ]
            }))
