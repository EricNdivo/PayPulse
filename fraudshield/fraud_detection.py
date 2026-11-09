import logging
import math
from datetime import timedelta

import joblib
import networkx as nx
from django.conf import settings
from django.db.models import Avg

from .models import FraudAlert, Transaction

logger = logging.getLogger(__name__)

_model = None
_model_loaded = False


def _get_model():
    """Load the trained model once; None if absent (heuristics are used instead)."""
    global _model, _model_loaded
    if not _model_loaded:
        _model_loaded = True
        try:
            _model = joblib.load(settings.FRAUD_MODEL_PATH)
        except (FileNotFoundError, OSError):
            logger.warning("No fraud model at %s; using heuristic scoring", settings.FRAUD_MODEL_PATH)
    return _model


class FraudDetector:
    """Scores a transaction using an optional ML model, heuristics and payment-graph cycles.

    Model feature order: [amount, hour_of_day, transactions_in_last_hour, amount / user_avg].
    """

    def __init__(self):
        self.graph = nx.DiGraph()
        for u, m, a in Transaction.objects.filter(status='completed').values_list(
                'user__username', 'merchant', 'amount'):
            self.graph.add_edge(u, m, amount=float(a))

    def features(self, tx):
        since = tx.created_at - timedelta(hours=1)
        velocity = Transaction.objects.filter(user=tx.user, created_at__gte=since).exclude(pk=tx.pk).count()
        avg = (Transaction.objects.filter(user=tx.user, status='completed').exclude(pk=tx.pk)
               .aggregate(a=Avg('amount'))['a'])
        ratio = float(tx.amount / avg) if avg else 1.0
        return [float(tx.amount), tx.created_at.hour, velocity, ratio]

    def detect_anomaly(self, feats):
        model = _get_model()
        if model is not None:
            if hasattr(model, 'predict_proba'):
                score = float(model.predict_proba([feats])[0][1])
            else:  # e.g. IsolationForest: lower decision_function => more anomalous
                score = 1 / (1 + math.exp(10 * float(model.decision_function([feats])[0])))
        else:
            _, hour, velocity, ratio = feats
            score = min(1.0, 0.15 * max(velocity - 2, 0) + 0.1 * max(ratio - 1, 0) + (0.2 if hour < 5 else 0))
        reason = "High anomaly score (velocity/amount/time)" if score > settings.FRAUD_THRESHOLD else ""
        return score, reason

    def detect_circular_payments(self, tx):
        self.graph.add_edge(tx.user.username, tx.merchant, amount=float(tx.amount))
        try:
            nx.find_cycle(self.graph, source=tx.user.username)
            return True, "Suspicious circular payment pattern detected"
        except nx.NetworkXNoCycle:
            return False, ""

    def analyze_transaction(self, tx):
        ml_score, ml_reason = self.detect_anomaly(self.features(tx))
        graph_hit, graph_reason = self.detect_circular_payments(tx)

        score = max(ml_score, 0.8 if graph_hit else 0.0)
        reason = ml_reason or graph_reason

        if score > settings.FRAUD_THRESHOLD:
            FraudAlert.objects.create(transaction=tx, score=score, reason=reason)
            tx.status = 'flagged'
            tx.save(update_fields=['status'])
        return score, reason
