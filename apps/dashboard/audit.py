"""Explicit service hooks: no request globals, model signals or private notes."""
from .models import AuditLog


def record_event(*, actor, action, entity_type, entity_id, description):
    # Callers enforce permissions and invoke this inside the operation's atomic
    # transaction. Audit failure must roll back the business operation too.
    entry = AuditLog(actor=actor, actor_username=actor.username, action=action, entity_type=entity_type, entity_id=entity_id, description=description)
    entry.full_clean()
    entry.save()
    return entry
