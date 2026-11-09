from django.contrib import admin

from .models import FraudAlert, PaymentGateway, Transaction

admin.site.register(PaymentGateway)
admin.site.register(Transaction)
admin.site.register(FraudAlert)
