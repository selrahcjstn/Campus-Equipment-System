from django.conf import settings
from .models import SystemSetting


def borrowing_limits():
    policy = SystemSetting.objects.filter(pk=1).first()
    if policy:
        return policy.as_limits()
    # Preserve the pre-existing configuration until an Admin saves the policy.
    return {
        "max_items": getattr(settings, "BORROWING_MAX_ITEMS", 3),
        "max_quantity": getattr(settings, "BORROWING_MAX_QUANTITY", 3),
        "max_days": getattr(settings, "BORROWING_MAX_DAYS", 7),
    }
