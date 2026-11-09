import random
import time
from collections import Counter
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from rest_framework.test import APIClient

from fraudshield.models import PaymentGateway
from fraudshield.management.commands.seed import MERCHANTS, USERS


class Command(BaseCommand):
    help = ("Generate traffic through the real API path (in-process): normal purchases plus injected "
            "fraud (velocity bursts, huge amounts, circular payment rings). Run `seed` first.")

    def add_arguments(self, parser):
        parser.add_argument("--count", type=int, default=100, help="Number of scenarios to run")
        parser.add_argument("--fraud-rate", type=float, default=0.2, help="Share of fraud scenarios (0-1)")
        parser.add_argument("--delay", type=float, default=0.0, help="Seconds between scenarios (for live demos)")
        parser.add_argument("--down", action="append", default=[], metavar="GATEWAY",
                            help="Take this gateway offline for the whole run (repeatable)")
        parser.add_argument("--rng-seed", type=int, help="Make the run reproducible")

    def handle(self, *args, **o):
        if o["rng_seed"] is not None:
            random.seed(o["rng_seed"])
        users = list(User.objects.filter(username__in=USERS))
        if len(users) < 2 or not PaymentGateway.objects.filter(name__startswith="Sim").exists():
            raise CommandError("No demo data. Run `python manage.py seed` first.")

        downed = []
        for name in o["down"]:
            n = PaymentGateway.objects.filter(name=name, is_active=True).update(is_active=False)
            if not n:
                raise CommandError(f"Unknown or already inactive gateway: {name}")
            downed.append(name)

        self.stats = Counter()
        self.gateway_use = Counter()
        try:
            for i in range(o["count"]):
                if random.random() < o["fraud_rate"]:
                    random.choice([self.velocity_burst, self.huge_amount, self.ring])(users)
                else:
                    self.pay(random.choice(users), random.choice(MERCHANTS), random.randint(5, 90))
                if o["delay"]:
                    time.sleep(o["delay"])
        finally:
            PaymentGateway.objects.filter(name__in=downed).update(is_active=True)
        self.report()

    # --- scenarios -------------------------------------------------------
    def pay(self, user, merchant, amount, label="normal"):
        client = APIClient(HTTP_HOST="localhost")
        client.force_authenticate(user)
        r = client.post("/api/transactions/", {
            "amount": str(Decimal(amount).quantize(Decimal("0.01"))), "currency": "USD",
            "merchant": merchant, "stripe_token": "tok_sim"}, format="json")
        outcome = {201: "completed", 202: "flagged", 402: "failed", 503: "no_gateway"}.get(r.status_code, f"http_{r.status_code}")
        self.stats[(label, outcome)] += 1
        if outcome in ("completed", "failed"):
            from fraudshield.models import Transaction
            tx = Transaction.objects.get(pk=r.data["transaction"]["id"] if outcome == "completed" else r.data["transaction"])
            self.gateway_use[(tx.gateway.name, outcome)] += 1
        return outcome

    def velocity_burst(self, users):
        user = random.choice(users)
        for _ in range(random.randint(6, 9)):
            self.pay(user, random.choice(MERCHANTS), random.randint(5, 30), "velocity")

    def huge_amount(self, users):
        self.pay(random.choice(users), random.choice(MERCHANTS), random.randint(1500, 5000), "huge_amount")

    def ring(self, users):
        a, b = random.sample(users, 2)  # A pays B, B pays A: a cycle in the payment graph
        self.pay(a, b.username, random.randint(20, 60), "ring")
        self.pay(b, a.username, random.randint(20, 60), "ring")

    # --- output ----------------------------------------------------------
    def report(self):
        w = self.stdout.write
        w(self.style.MIGRATE_HEADING("\nScenario results"))
        for label in sorted({k[0] for k in self.stats}):
            parts = ", ".join(f"{out}={n}" for (l, out), n in sorted(self.stats.items()) if l == label)
            w(f"  {label:<14} {parts}")
        w(self.style.MIGRATE_HEADING("Gateway usage"))
        for name in sorted({k[0] for k in self.gateway_use}):
            ok, bad = self.gateway_use[(name, "completed")], self.gateway_use[(name, "failed")]
            w(f"  {name:<14} ok={ok} failed={bad}")
        fraud = sum(n for (l, out), n in self.stats.items() if l != "normal")
        caught = sum(n for (l, out), n in self.stats.items() if l != "normal" and out == "flagged")
        w(f"\nFraud attempts: {fraud}, flagged: {caught}")
