import random
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.utils import timezone

from fraudshield.models import PaymentGateway, Transaction

GATEWAYS = [
    # name, cost, latency (s), success_rate
    ("Sim-Fast", "0.45", 0.15, 0.97),
    ("Sim-Cheap", "0.10", 0.80, 0.90),
    ("Sim-Balanced", "0.25", 0.40, 0.95),
]
USERS = ["alice", "bob", "carol", "dave", "erin", "frank"] + [f"user{i:02d}" for i in range(1, 25)]
MERCHANTS = ["Naivas", "Java House", "Uber", "Jumia", "Safaricom", "KPLC", "Netflix"]


class Command(BaseCommand):
    help = "Create demo gateways, users and some completed transaction history (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument("--password", default="paypulse123", help="Password for demo users")
        parser.add_argument("--history", type=int, default=8, help="Past transactions per user")
        parser.add_argument("--reset", action="store_true", help="Delete existing demo data first")

    def handle(self, *args, **o):
        if o["reset"]:
            Transaction.objects.filter(user__username__in=USERS).delete()
            PaymentGateway.objects.filter(name__startswith="Sim").delete()

        for name, cost, latency, rate in GATEWAYS:
            PaymentGateway.objects.update_or_create(
                name=name,
                defaults=dict(api_key="simulated", cost_per_transaction=Decimal(cost),
                              latency=latency, success_rate=rate, is_active=True),
            )

        gw = list(PaymentGateway.objects.filter(name__startswith="Sim"))
        now = timezone.now()
        for username in USERS:
            user, created = User.objects.get_or_create(username=username)
            if created:
                user.set_password(o["password"])
                user.save()
                for i in range(o["history"]):
                    tx = Transaction.objects.create(
                        user=user, amount=Decimal(random.randint(5, 80)) + Decimal("0.50"),
                        merchant=random.choice(MERCHANTS), gateway=random.choice(gw),
                        status="completed", ip_address="127.0.0.1",
                    )
                    # backdate (auto_now_add ignores values passed at create)
                    Transaction.objects.filter(pk=tx.pk).update(
                        created_at=now - timedelta(days=random.randint(1, 30), hours=random.randint(1, 12)))

        self.stdout.write(self.style.SUCCESS(
            f"Seeded {len(GATEWAYS)} gateways and users {', '.join(USERS)} "
            f"(password: {o['password']}). Superuser not created; use createsuperuser."))
