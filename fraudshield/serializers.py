from decimal import Decimal

from rest_framework import serializers

from .models import Transaction


class TransactionSerializer(serializers.ModelSerializer):
    amount = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal('0.01'))
    currency = serializers.RegexField(r'^[A-Za-z]{3}$', default='USD')

    class Meta:
        model = Transaction
        fields = ['id', 'amount', 'currency', 'merchant', 'gateway', 'status', 'created_at']
        read_only_fields = ['id', 'gateway', 'status', 'created_at']

    def validate_currency(self, value):
        return value.upper()
