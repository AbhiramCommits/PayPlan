"""Health endpoint used by the ALB / docker-compose healthcheck.

The Redis assertion is performed through the configured Django cache backend,
which is RedisCache in dev/prod and LocMem in tests.  That keeps the test suite
free of network access while still exercising the same code path.
"""

import logging

from django.core.cache import cache
from django.db import connection
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger(__name__)


def _db_ok() -> bool:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            return cursor.fetchone()[0] == 1
    except Exception:  # pragma: no cover - only on infrastructure failure
        logger.exception("database health check failed")
        return False


def _cache_ok() -> bool:
    try:
        cache.set("payplan:health", "ok", timeout=5)
        return cache.get("payplan:health") == "ok"
    except Exception:  # pragma: no cover - only on infrastructure failure
        logger.exception("cache/redis health check failed")
        return False


class HealthView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        db_ok = _db_ok()
        cache_ok = _cache_ok()
        healthy = db_ok and cache_ok
        return Response(
            {"status": "ok" if healthy else "degraded", "db": db_ok, "redis": cache_ok},
            status=200 if healthy else 503,
        )


health = HealthView.as_view()
