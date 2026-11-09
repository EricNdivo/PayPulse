"""Builds the JSON snapshot that the live dashboard renders."""
from collections import defaultdict
from datetime import timedelta

from django.db.models import Count, Max, Sum
from django.utils import timezone

from .models import FraudAlert, PaymentGateway, Transaction

BUCKET_SECONDS = 5
BUCKETS = 60  # 5 minutes of throughput


def fingerprint():
    """Cheap change detector: shifts whenever a tx is created or changes status."""
    agg = Transaction.objects.aggregate(n=Count('id'), last=Max('created_at'))
    by_status = tuple(sorted(Transaction.objects.values_list('status').annotate(c=Count('id'))))
    return (agg['n'], agg['last'], by_status, FraudAlert.objects.count())


def _kpis():
    rows = dict(Transaction.objects.values_list('status').annotate(c=Count('id')))
    total = sum(rows.values())
    completed, flagged, failed = rows.get('completed', 0), rows.get('flagged', 0), rows.get('failed', 0)
    volume = Transaction.objects.filter(status='completed').aggregate(v=Sum('amount'))['v'] or 0
    return {
        'total': total, 'completed': completed, 'flagged': flagged, 'failed': failed,
        'pending': rows.get('pending', 0),
        'volume_completed': float(volume),
        'approval_rate': round(completed / total, 4) if total else None,
        'flag_rate': round(flagged / total, 4) if total else None,
    }


def _gateways():
    stats = defaultdict(lambda: {'completed': 0, 'failed': 0, 'flagged': 0})
    for gw_id, status, c in Transaction.objects.values_list('gateway_id', 'status').annotate(c=Count('id')):
        stats[gw_id][status] = c
    out = []
    for g in PaymentGateway.objects.order_by('name'):
        s = stats[g.id]
        settled = s['completed'] + s['failed']
        out.append({
            'name': g.name, 'active': g.is_active,
            'cost': float(g.cost_per_transaction), 'latency': g.latency,
            'configured_success': g.success_rate,
            'observed_success': round(s['completed'] / settled, 4) if settled else None,
            'completed': s['completed'], 'failed': s['failed'], 'flagged': s['flagged'],
        })
    return out


def _series(now):
    start = now - timedelta(seconds=BUCKET_SECONDS * BUCKETS)
    buckets = [[0, 0] for _ in range(BUCKETS)]  # [all, flagged]
    for created, status in Transaction.objects.filter(created_at__gte=start).values_list('created_at', 'status'):
        i = min(BUCKETS - 1, int((created - start).total_seconds() // BUCKET_SECONDS))
        buckets[i][0] += 1
        if status == 'flagged':
            buckets[i][1] += 1
    return {'bucket_seconds': BUCKET_SECONDS, 'buckets': buckets}


def _graph(limit=300):
    edges = {}
    qs = (Transaction.objects.order_by('-created_at')
          .values_list('user__username', 'merchant', 'status', 'amount')[:limit])
    for user, merchant, status, amount in qs:
        e = edges.setdefault((user, merchant), {'source': user, 'target': merchant, 'count': 0,
                                                'amount': 0.0, 'flagged': False})
        e['count'] += 1
        e['amount'] += float(amount)
        e['flagged'] = e['flagged'] or status == 'flagged'
    return list(edges.values())


def snapshot():
    now = timezone.now()
    txs = Transaction.objects.select_related('user', 'gateway').order_by('-created_at')[:40]
    alerts = FraudAlert.objects.select_related('transaction__user').order_by('-created_at')[:20]
    return {
        'type': 'snapshot',
        'server_time': now.isoformat(),
        'kpis': _kpis(),
        'gateways': _gateways(),
        'series': _series(now),
        'graph': _graph(),
        'transactions': [{
            'id': str(t.id), 'user': t.user.username, 'merchant': t.merchant,
            'amount': float(t.amount), 'currency': t.currency, 'status': t.status,
            'gateway': t.gateway.name if t.gateway else None,
            'created_at': t.created_at.isoformat(),
        } for t in txs],
        'alerts': [{
            'transaction_id': str(a.transaction_id), 'user': a.transaction.user.username,
            'merchant': a.transaction.merchant, 'amount': float(a.transaction.amount),
            'score': round(a.score, 3), 'reason': a.reason, 'created_at': a.created_at.isoformat(),
        } for a in alerts],
    }
