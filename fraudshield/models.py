import uuid

from django.contrib.auth.models import User
from django.db import models


class PaymentGateway(models.Model):
    name = models.CharField(max_length=50, unique=True)
    # TODO: move to env/secret manager; stored plain for now.
    api_key = models.CharField(max_length=200)
    cost_per_transaction = models.DecimalField(max_digits=5, decimal_places=2)
    latency = models.FloatField(default=0.5)
    success_rate = models.FloatField(default=0.95)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Transaction(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('flagged', 'Flagged'),
        ('failed', 'Failed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='transactions')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='USD')
    merchant = models.CharField(max_length=100)
    gateway = models.ForeignKey(PaymentGateway, on_delete=models.SET_NULL, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    ip_address = models.GenericIPAddressField(null=True)
    idempotency_key = models.CharField(max_length=100, null=True, blank=True)
    failure_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'idempotency_key'], name='unique_user_idempotency_key'
            )
        ]

    def __str__(self):
        return f"{self.user.username} - {self.amount} {self.currency} at {self.merchant}"


class FraudAlert(models.Model):
    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE, related_name='fraud_alerts')
    score = models.FloatField()
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Fraud Alert for Transaction {self.transaction_id} - Score: {self.score}"
