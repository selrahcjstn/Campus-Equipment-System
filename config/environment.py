"""Small local configuration loader; process environment always takes precedence."""
import os

from django.core.exceptions import ImproperlyConfigured


def load_environment(path):
    # Deliberately only KEY=value, optional matching quotes, and whole-line
    # comments. No shell execution, interpolation or third-party dependency.
    if path.exists():
        for number, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            key, separator, value = line.partition("=")
            key, value = key.strip(), value.strip()
            if not separator or not key.isidentifier():
                raise ImproperlyConfigured(f"Invalid environment entry on line {number}; use KEY=value.")
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            os.environ.setdefault(key, value)


def environment_bool(name, default):
    value = os.environ.get(name, str(default)).strip().lower()
    if value not in {"true", "false", "1", "0"}:
        raise ImproperlyConfigured(f"{name} must be true or false.")
    return value in {"true", "1"}
