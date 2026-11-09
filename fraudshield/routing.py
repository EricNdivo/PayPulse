from django.urls import path

from .consumers import DashboardConsumer, TransactionConsumer

websocket_urlpatterns = [
    path('ws/transactions/', TransactionConsumer.as_asgi()),
    path('ws/dashboard/', DashboardConsumer.as_asgi()),
]
