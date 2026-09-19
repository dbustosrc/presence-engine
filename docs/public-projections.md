# Public candidate projections

Version 0.3.0 adds candidate entities for controlled migration. Every candidate
is disabled by default and is derived from the same canonical snapshot
revision. Enabling an entity does not publish MQTT, call a Home Assistant
service or replace another entity.

## General presence candidate

The sensor reports `on` when the snapshot maximum is greater than zero and
`off` otherwise. Its attributes expose the exact count interval, classified
presences, active areas, conservative confidence, coverage, conflicts,
snapshot identifier and revision.

## Coverage candidate

The binary sensor mirrors degraded coverage and exposes both
`unavailable_sources` and `unavailable_source_ids` for compatibility. Missing
coverage never asserts an empty home.

## Identity candidates

Each configured canonical identity receives a tracker candidate and an atomic
record candidate. Both expose the same location, identity, timing, source and
image metadata from one revision. The compatibility `confidence` attribute
describes the resolved presence hypothesis; identity and location keep their
own confidence fields.

- No current hypothesis produces `unknown`, not `not_home`.
- Identity confidence never substitutes for location confidence.
- The last image remains available when a newer non-visual source changes the
  location.
- An image reference becomes `entity_picture` only when it is already a
  browser-usable path or URL. Opaque references remain available as metadata
  until an image-serving adapter resolves them.

## Cutover rule

Validate candidate entity contracts before disabling an existing writer. A
public entity identifier is transferred only after the old writer is stopped;
two writers must never own the same contract at once.
