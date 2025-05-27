
from .models import Transaction, FraudAlert
from sklearn.ensemble import IsolationForest
import joblib
import networkx as nx
from django.utils import timezone

class FraudDetector:
    def __init__(self):
        self.model = joblib.load('fraud_model.pkl') 
        self.graph = nx.DiGraph()  
    def update_graph(self, transaction):
        self.graph.add_node(transaction.user.username)
        self.graph.add_node(transaction.merchant)
        self.graph.add_edge(transaction.user.username, transaction.merchant, amount=transaction.amount)

    def detect_circular_payments(self, transaction):
        try:
            cycles = nx.find_cycle(self.graph, source=transaction.user.username)
            return True, "Suspicious circular payment pattern detected"
        except nx.NetworkXNoCycle:
            return False, ""

    def detect_anomaly(self, transaction):
        features = [
            transaction.amount,
            (timezone.now() - transaction.created_at).total_seconds() / 3600,  
            float(transaction.ip_address.split('.')[-1]) if transaction.ip_address else 0  
        ]
        score = self.model.predict_proba([features])[0][1] if hasattr(self.model, 'predict_proba') else 0.5
        return score, "High anomaly score" if score > 0.7 else ""

    def analyze_transaction(self, transaction):
        self.update_graph(transaction)
        ml_score, ml_reason = self.detect_anomaly(transaction)
        graph_detected, graph_reason = self.detect_circular_payments(transaction)

        final_score = max(ml_score, 0.8 if graph_detected else 0)
        final_reason = ml_reason or graph_reason

        if final_score > 0.7:
            FraudAlert.objects.create(transaction=transaction, score=final_score, reason=final_reason)
            transaction.status = 'flagged'
        else:
            transaction.status = 'completed'
        transaction.save()

        return final_score, final_reason
