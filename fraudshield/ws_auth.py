from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser, User
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken


@database_sync_to_async
def _get_user(token):
    try:
        return User.objects.get(id=AccessToken(token)['user_id'])
    except (TokenError, User.DoesNotExist, KeyError):
        return AnonymousUser()


class JWTQueryAuthMiddleware:
    """Authenticate websockets via ?token=<access JWT>, overriding any session user."""

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        token = parse_qs(scope.get('query_string', b'').decode()).get('token', [None])[0]
        if token:  # otherwise keep the session user set by AuthMiddlewareStack
            scope['user'] = await _get_user(token)
        return await self.inner(scope, receive, send)
