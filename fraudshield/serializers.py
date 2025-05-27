from rest_framework import serializers
from .models import Transaction

class TransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Transaction
        fields = ['id', 'amount', 'currency', 'merchant', 'gateway', 'status', 'created_at']
        read_only_fields = ['id', 'gateway', 'status', 'created_at']