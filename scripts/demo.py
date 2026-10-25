"""Prepare, verify, or run the fictional course demo using private .env.demo."""
import json
import os
from pathlib import Path
import secrets
import sys

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / ".env.demo"
DATABASE = ROOT / "demo.sqlite3"
sys.path.insert(0, str(ROOT))


def configure(create=False):
    if not CONFIG.exists():
        if not create:
            raise SystemExit("Run python scripts/demo.py setup first.")
        if DATABASE.exists():
            raise SystemExit("demo.sqlite3 exists without .env.demo; inspect it before continuing.")
        with CONFIG.open("x", encoding="utf-8") as stream:
            stream.write(
                "# Private fictional demo credentials. Never commit or distribute this file.\n"
                f"DJANGO_SECRET_KEY={secrets.token_urlsafe(64)}\n"
                "DJANGO_DEBUG=true\nDJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,[::1]\n"
                f"DJANGO_DATABASE_PATH={DATABASE.as_posix()}\n"
                f"CAMPUS_DEMO_PASSWORD={secrets.token_urlsafe(24)}\n"
            )
    # This wrapper deliberately uses only the dedicated demo configuration,
    # regardless of the invoking terminal's normal application settings.
    for key in ("DJANGO_SECRET_KEY", "DJANGO_DEBUG", "DJANGO_ALLOWED_HOSTS", "DJANGO_DATABASE_PATH", "CAMPUS_DEMO_PASSWORD"):
        os.environ.pop(key, None)
    from config.environment import load_environment
    load_environment(CONFIG)
    configured = Path(os.environ.get("DJANGO_DATABASE_PATH", "")).resolve()
    if configured != DATABASE.resolve() or configured == (ROOT / "db.sqlite3").resolve():
        raise SystemExit("Demo configuration must use this project's separate demo.sqlite3.")
    if not os.environ.get("DJANGO_SECRET_KEY") or not os.environ.get("CAMPUS_DEMO_PASSWORD"):
        raise SystemExit("The private demo configuration is incomplete; no credentials were changed.")
    os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"


def verify():
    from django.contrib.auth import get_user_model
    from django.db import connection
    from django.db.models import Count
    from apps.borrowing.models import Allocation, BorrowingRequest
    from apps.inventory.models import Category, Equipment, EquipmentUnit
    from apps.loans.models import Loan, LoanUnit
    from apps.maintenance.models import MaintenanceRecord

    counts = {
        "categories": Category.objects.count(), "catalog_items": Equipment.objects.count(),
        "physical_units": EquipmentUnit.objects.count(),
        "admins": get_user_model().objects.filter(role="ADMIN").count(),
        "basic_users": get_user_model().objects.filter(role="BASIC_USER").count(),
        "requests": BorrowingRequest.objects.count(), "loans": Loan.objects.count(),
        "maintenance_records": MaintenanceRecord.objects.count(),
    }
    minimums = dict(zip(counts, [3, 6, 18, 1, 8, 20, 8, 4]))
    checks = {f"minimum_{key}": value >= minimums[key] for key, value in counts.items()}
    checks.update({
        "rejected_request": BorrowingRequest.objects.filter(status="REJECTED").exists(),
        "cancelled_request": BorrowingRequest.objects.filter(status="CANCELLED").exists(),
        "partial_return": any(0 < loan.outstanding_count < loan.quantity for loan in Loan.objects.all()),
        "damaged_return": LoanUnit.objects.filter(return_condition="DAMAGED", returned_at__isnull=False).exists(),
        "outstanding_overdue_loan": Loan.objects.overdue().exists(),
        "all_inventory_statuses": set(EquipmentUnit.objects.values_list("status", flat=True)) == set(EquipmentUnit.Status.values),
        "complete_unit_metadata": not EquipmentUnit.objects.filter(condition__isnull=True).exists() and not EquipmentUnit.objects.filter(acquisition_date__isnull=True).exists(),
        "categorized_equipment": not Equipment.objects.filter(category__isnull=True).exists(),
        "no_duplicate_reservation": not Allocation.objects.filter(active=True).values("unit_id").annotate(n=Count("pk")).filter(n__gt=1).exists(),
        "active_allocation_statuses": all(
            row.request_item.request.status in {"APPROVED", "ISSUED"}
            and row.unit.status == ("RESERVED" if row.request_item.request.status == "APPROVED" else "ON_LOAN")
            for row in Allocation.objects.filter(active=True).select_related("unit", "request_item__request")
        ),
    })
    with connection.cursor() as cursor:
        checks["foreign_keys"] = not cursor.execute("PRAGMA foreign_key_check").fetchall()
    result = {"database": "demo.sqlite3", "counts": counts, "checks": checks, "passed": all(checks.values())}
    print(json.dumps(result, indent=2))
    if not result["passed"]:
        raise SystemExit("Demo verification failed; inspect the reported checks. No data was repaired automatically.")


def main():
    args = sys.argv[1:]
    if not args:
        raise SystemExit("Usage: python scripts/demo.py setup | verify | <Django command and arguments>")
    configure(create=args[0] == "setup")
    import django
    django.setup()
    from django.core.management import call_command, execute_from_command_line
    if args[0] == "setup":
        call_command("migrate", interactive=False)
        call_command("seed_project_demo", confirm_isolated=True)
        verify()
        print("Private password: read CAMPUS_DEMO_PASSWORD in .env.demo. Accounts: demo_admin, demo_user01 through demo_user08.")
        print("Start with: python scripts/demo.py runserver 127.0.0.1:8786")
    elif args[0] == "verify":
        verify()
    else:
        execute_from_command_line([str(ROOT / "manage.py"), *args])


if __name__ == "__main__":
    main()
