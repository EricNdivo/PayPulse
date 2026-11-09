import logging
import random

import paypalrestsdk
import stripe
from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.db import IntegrityError
from django.shortcuts import render
from rest_framework import status, viewsets
from rest_framework.response import Response

from .fraud_detection import FraudDetector
from .load_balancer import select_gateway
from .models import Transaction
from .serializers import TransactionSerializer

logger = logging.getLogger(__name__)


def _client_ip(request):
    fwd = request.META.get('HTTP_X_FORWARDED_FOR')
    if fwd and settings.TRUST_PROXY_HEADERS:
        return fwd.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def charge(gateway, tx, request):
    """Charge via the selected gateway; raises on failure."""
    if gateway.name.startswith("Sim"):
        # Offline gateway for demos/load tests: succeeds with probability success_rate.
        if random.random() > gateway.success_rate:
            raise RuntimeError(f"{gateway.name}: simulated decline")
    elif gateway.name == "Stripe":
        stripe.api_key = gateway.api_key
        stripe.Charge.create(
            amount=int(tx.amount * 100),
            currency=tx.currency.lower(),
            source=request.data['stripe_token'],
            description=f"Payment by {request.user.username}",
            idempotency_key=str(tx.id),
        )
    elif gateway.name == "PayPal":
        paypalrestsdk.configure({
            "mode": settings.PAYPAL_MODE,
            "client_id": gateway.api_key,
            "client_secret": settings.PAYPAL_SECRET,
        })
        payment = paypalrestsdk.Payment({
            "intent": "sale",
            "payer": {"payment_method": "paypal"},
            "transactions": [{"amount": {"total": str(tx.amount), "currency": tx.currency}}],
        })
        if not payment.create():
            raise RuntimeError(payment.error)
    else:
        raise ValueError(f"Unsupported gateway: {gateway.name}")


class TransactionViewSet(viewsets.ReadOnlyModelViewSet):
    """List/retrieve own transactions; POST creates a payment (fraud check runs before charging)."""
    serializer_class = TransactionSerializer

    def get_queryset(self):
        return Transaction.objects.filter(user=self.request.user).order_by('-created_at')

    def create(self, request):
        serializer = TransactionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        key = request.headers.get('Idempotency-Key')
        if key:
            existing = self.get_queryset().filter(idempotency_key=key).first()
            if existing:
                return Response({"transaction": TransactionSerializer(existing).data, "replayed": True})

        try:
            gateway = select_gateway()
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        try:
            tx = serializer.save(
                user=request.user, gateway=gateway, status='pending',
                ip_address=_client_ip(request), idempotency_key=key or None,
            )
        except IntegrityError:  # concurrent request with the same key
            return Response({"error": "Duplicate Idempotency-Key"}, status=status.HTTP_409_CONFLICT)

        # Fraud check happens BEFORE any money moves.
        score, reason = FraudDetector().analyze_transaction(tx)
        if tx.status == 'flagged':
            return Response(
                {"transaction": TransactionSerializer(tx).data, "fraud_score": score, "fraud_reason": reason},
                status=status.HTTP_202_ACCEPTED,
            )

        try:
            charge(gateway, tx, request)
        except Exception as e:
            logger.exception("Charge failed for %s", tx.id)
            tx.status, tx.failure_reason = 'failed', str(e)
            tx.save(update_fields=['status', 'failure_reason'])
            return Response({"error": "Payment failed", "transaction": str(tx.id)},
                            status=status.HTTP_402_PAYMENT_REQUIRED)

        tx.status = 'completed'
        tx.save(update_fields=['status'])
        return Response(
            {"transaction": TransactionSerializer(tx).data, "fraud_score": score, "fraud_reason": reason},
            status=status.HTTP_201_CREATED,
        )


@staff_member_required
def dashboard(request):
    """Live ops dashboard (staff only; sign in via /admin/ first)."""
    return render(request, 'fraudshield/dashboard.html')
