import logging

from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger(__name__)


def api_exception_handler(exc, context):
    """Normalise DRF errors to {"error": {"code", "message", "details"}}."""
    response = drf_exception_handler(exc, context)
    if response is None:
        return response
    code = getattr(exc, "default_code", "error")
    detail = response.data
    message = None
    if isinstance(detail, dict) and "detail" in detail and len(detail) == 1:
        message = str(detail["detail"])
    elif isinstance(detail, list):
        message = "; ".join(str(item) for item in detail)
    response.data = {
        "error": {
            "code": getattr(exc, "payplan_code", code),
            "message": message or "Request failed",
            "details": detail,
        }
    }
    return response
