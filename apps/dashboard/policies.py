from django.conf import settings
from .models import LIMIT_RANGES, SystemSetting


def borrowing_limits():
    policy = SystemSetting.objects.filter(pk=1).first()
    if policy:
        limits = policy.as_limits()
    else:
        # Preserve configuration defaults, subject to the fixed item ceiling.
        limits = {
            "max_items": getattr(settings, "BORROWING_MAX_ITEMS", 3),
            "max_quantity": getattr(settings, "BORROWING_MAX_QUANTITY", 3),
            "max_days": getattr(settings, "BORROWING_MAX_DAYS", 7),
        }
    # Also protect deployments with legacy policy rows before migration runs.
    limits["max_items"] = min(limits["max_items"], LIMIT_RANGES["max_items"][1])
    return limits
