# PayPulse
A Django-based REST API that intelligently routes payment transactions across multiple gateways to optimize for cost, speed, and reliability. Each transaction is scored in real time by a fraud detection layer that combines graph analysis of links between accounts, devices, and payment methods with a machine learning model trained on transaction behaviour. The system balances load across gateways based on live health metrics, automatically fails over when a gateway degrades, and uses idempotent retries to prevent duplicate charges.

## Quick start (demo)
```bash
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt
python manage.py migrate
python manage.py seed                 # demo gateways + users (password: paypulse123)
python manage.py createsuperuser      # staff login for the dashboard
python -m daphne PayPulse.asgi:application   # serves HTTP + WebSockets on :8000
```
Open <http://localhost:8000/dashboard/> (sign in via /admin/ first), then in another terminal:
```bash
python manage.py simulate --count 200 --delay 0.2          # normal + fraud traffic
python manage.py simulate --down Sim-Cheap --count 100     # watch a gateway go offline
python manage.py test
```
