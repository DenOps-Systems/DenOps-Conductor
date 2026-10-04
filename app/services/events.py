# SPDX-License-Identifier: AGPL-3.0-only
"""Transactional event journal; consumers and their delivery cursors are future modules."""
import json
from app.models import DomainEvent

EVENT_FIELDS = {
    'repair.queued': frozenset({'project_id', 'state'}),
    'monitor.observed': frozenset({'resource_id', 'status'}),
    'release.verified': frozenset({'project_id', 'commit', 'migration_version'}),
    'release.published': frozenset({'project_id', 'commit', 'release_id'}),
    'builder.stopped': frozenset({'builder_id', 'vm_id'}),
}

def emit(db, event_type, entity_type, entity_id, payload, correlation_id=None):
    if event_type not in EVENT_FIELDS or not set(payload) <= EVENT_FIELDS[event_type]:
        raise ValueError('Unsupported event or payload fields')
    # Strict fields keep secrets and arbitrary logs out of the integration journal.
    encoded = json.dumps(payload, sort_keys=True)
    if len(encoded) > 4096:
        raise ValueError('Event payload too large')
    event = DomainEvent(event_type=event_type, entity_type=entity_type, entity_id=entity_id, correlation_id=correlation_id, payload=encoded)
    db.add(event)
    return event
