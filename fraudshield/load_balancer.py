import random

from .models import PaymentGateway


def select_gateway(exclude=()):
    """Pick an active gateway, weighted by success_rate / (cost * latency)."""
    gateways = list(PaymentGateway.objects.filter(is_active=True).exclude(pk__in=[g.pk for g in exclude]))
    if not gateways:
        raise ValueError("No active payment gateways available")

    weights = [
        g.success_rate / (max(float(g.cost_per_transaction), 0.01) * max(g.latency, 0.001))
        for g in gateways
    ]
    return random.choices(gateways, weights=weights, k=1)[0]
