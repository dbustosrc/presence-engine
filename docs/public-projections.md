# Public projections

Version 0.4.1 keeps the validated projections as stable public entities.
Every projection is derived from the same canonical snapshot revision. An
entity does not publish MQTT, call a Home Assistant service or replace another
entity automatically.

## General presence

The sensor reports `on` when the snapshot maximum is greater than zero and
`off` otherwise. Its attributes expose the exact count interval, classified
presences, active areas, conservative confidence, coverage, conflicts,
snapshot identifier and revision.

## Coverage

The canonical diagnostic binary sensor mirrors degraded coverage and exposes both
`unavailable_sources` and `unavailable_source_ids` for compatibility. Missing
coverage never asserts an empty home.

## Identity records

Each configured canonical identity receives an atomic record. It
exposes location, identity, timing, source and image metadata from one
revision. The compatibility `confidence` attribute describes the resolved
presence hypothesis; identity and location keep their own confidence fields.

Room names are intentionally not projected as `device_tracker` state. Home
Assistant deprecated free-form tracker locations; consumers should read the
identity record and its explicit location fields instead.

- No current hypothesis produces `unknown`, not `not_home`.
- Identity confidence never substitutes for location confidence.
- The last image remains available when a newer non-visual source changes the
  location.
- Las referencias de eventos de Frigate se publican como `entity_picture`
  mediante su proxy autenticado de Home Assistant. Las rutas y URL ya
  navegables se conservan; otras referencias opacas permanecen únicamente
  como metadatos.

## Cutover rule

Validate public entity contracts before disabling an existing writer. A
public entity identifier is transferred only after the old writer is stopped;
two writers must never own the same contract at once.
