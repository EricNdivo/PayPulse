from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework_jwt.authentication import JSONWebTokenAuthentication
from .models import Transaction, PaymentGateway
from .serializers import TransactionSerializer
from .load_balancer import select_gateway
from .fraud_detection import FraudDetector
import stripe
import paypalrestsdk
from django.conf import settings

class TransactionViewSet(viewsets.ModelViewSet):
    queryset = Transaction.objects.all()
    serializer_class = TransactionSerializer
    permission_classes = [IsAuthenticated]
    authentication_classes = [JSONWebTokenAuthentication]

    def create(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        gateway = select_gateway()

        try:
            if gateway.name == "Stripe":
                stripe.api_key = gateway.api_key
                charge = stripe.Charge.create(
                    amount=int(request.data['amount'] * 100),  
                    currency=request.data.get('currency', 'usd'),
                    source=request.data['stripe_token'],  
                    description=f"Payment by {request.user.username}"
                )
            elif gateway.name == "PayPal":
                paypalrestsdk.configure({
                    "mode": settings.PAYPAL_MODE,
                    "client_id": gateway.api_key,
                    "client_secret": settings.PAYPAL_SECRET
                })
                payment = paypalrestsdk.Payment({
                    "intent": "sale",
                    "payer": {"payment_method": "paypal"},
                    "transactions": [{"amount": {"total": str(request.data['amount']), "currency": request.data.get('currency', 'USD')}}]
                })
                if not payment.create():
                    raise Exception(payment.error)
            else:
                raise ValueError("Unsupported gateway")
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        transaction = serializer.save(
            user=request.user,
            gateway=gateway,
            status='pending',
            ip_address=request.META.get('REMOTE_ADDR'),
            merchant=request.data['merchant']
        )

        detector = FraudDetector()
        score, reason = detector.analyze_transaction(transaction)

        return Response({
            "transaction": serializer.data,
            "fraud_score": score,
            "fraud_reason": reason
        }, status=status.HTTP_201_CREATED)

