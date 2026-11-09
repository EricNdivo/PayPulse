import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'PayPulse.settings')
django_asgi_app = get_asgi_application()

from channels.auth import AuthMiddlewareStack  # noqa: E402
from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from fraudshield.routing import websocket_urlpatterns  # noqa: E402
from fraudshield.ws_auth import JWTQueryAuthMiddleware  # noqa: E402

application = ProtocolTypeRouter({
    'http': django_asgi_app,
    'websocket': AuthMiddlewareStack(JWTQueryAuthMiddleware(URLRouter(websocket_urlpatterns))),
})
