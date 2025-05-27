from .models import PaymentGateway
import random

def select_gateway():
    gateways = PaymentGateway.objects.filter(is_active=True)
    if not gateways:
        raise ValueError("No active payment gateways available")

    weights = [(1 / g.cost_per_transaction * g.success_rate) / g.latency for g in gateways]
    total_weight = sum(weights)
    weights = [w / total_weight for w in weights]  
    selected_gateway = random.choices(gateways, weights=weights, k=1)[0]
    return selected_gateway
