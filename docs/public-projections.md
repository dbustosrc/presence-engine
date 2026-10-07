# Public projections

The [evidence policy](evidence-policy.md) defines the agreed next behavior.
The versioned projection contracts below describe implemented behavior;
Weak AP proximity is implemented from 0.5.30. From 0.5.32, `devices` may include
`geographic_position` (device-only coordinates, accuracy, original clock and
native zone); coordinates are redacted in diagnostics. `area_activity` lists
light/media area context, source/dependency provenance and low/context-only
confidence, with no implied individual or body count. It is separate from
`active_areas` and physical occupancy so it cannot become a PTZ vote. Additional
confidence combinations and physical acceptance remain separate work.

Version 0.4.9 keeps the validated projections as stable public entities.
Every projection is derived from the same canonical snapshot revision. An
entity does not publish MQTT, call a Home Assistant service or replace another
entity automatically.

## General presence

The sensor reports `on` when the snapshot maximum is greater than zero and
`off` otherwise. Its attributes expose the exact count interval, classified
presences, active areas, conservative confidence, coverage, conflicts,
snapshot identifier and revision.

Each presence item carries its resolved identity method and observation time,
plus a presentation-ready authenticated image URL when visual evidence exists.
The image retains its own event, area and timestamp, so consumers do not infer
the current room from historical visual metadata or rescan source entities.

Current area occupancy additionally exposes `current_location_confidence`
(the configured ordinal spatial quality, not a calibrated probability) and
`current_source_families`. Only compatible measurements within the resolver's
trajectory window corroborate an area. Visual object/face channels and radar
partitions do not receive multiple votes; explicit dependency groups also
prevent correlated channels from multiplying support. Low-quality context
does not add a control vote. Device support requires an already associated
current owner, a device sample no older than the associated body location,
and physical area evidence; a phone alone never creates area
occupancy. None of these fields confirms identity or changes historical images.

### Shared visual coverage

From 0.5.16, local tracked-object IDs are not assumed to be globally independent
bodies across cameras. Current objects of the same class in the same precise
area may overlap: the lower bound retains the strongest per-camera population,
while the upper bound preserves all possible bodies. Distinct objects in one
camera and different species remain separate. Unknown camera provenance or
floor-only locations do not establish shared room coverage.

An identified object cannot consume another local object from the same camera.
Without an explicit object/identity link, a room correlation preserves visitor
uncertainty. Home-scope identities can overlap current anonymous bodies; they
do not establish an additional exact individual or acquire a room by elimination.
The reasons `cross_camera_population_overlap`, `anonymous_body_identity_overlap`
and `home_identity_may_overlap_current_body` explain these bounds. Object images,
identity confidence, event timestamps and existing continuity limits are unchanged.

An ACTIVE stationary object can have an old frame. Frame age alone is not a new
individual or proof of absence; lifecycle, source availability and configured
expiry remain authoritative. This is conservative population fusion, not visual
appearance re-identification or a calibrated probability of identity.

### Wi-Fi attachment facts

From 0.5.17, `devices` may expose `network_attachment`,
`network_attachment_area` and `network_attachment_observed_at`. These describe
the current endpoint/AP connection, not a physical room measurement. The device
raw observation remains home scope with no room; `linked_identity` is an optional
owner association, not face recognition or proof that the owner carries it.
AP changes while the tracker remains connected are supported, and unknown or
disconnected endpoints lose active attachment facts even when old router
attributes remain. Downloadable diagnostics redact the AP identifier.

The implemented Wi-Fi adapter creates no body, physical room occupancy or
detection. From 0.5.30 the resolver retains inferred home presence and low-confidence
personal proximity near a mapped AP for a reviewed personal endpoint with an
explicit owner. It still cannot assert an exact room, override current direct
identity/location, remove the owner on disconnect or degrade observer coverage.
Derived device/personal locations use `wifi_ap_proximity`, `low` and personal
status `possible`. Consumers must label the area as "near the AP of...", not a
confirmed room. Conflicting owned AP areas remain alternatives at home scope.
These hypotheses contribute no confirmed physical minimum/current occupancy,
anonymous-body identity or PTZ support; attachment fields are neither
triangulation nor probabilities.

## Coverage

The canonical diagnostic binary sensor mirrors degraded coverage and exposes both
`unavailable_sources` and `unavailable_source_ids` for compatibility. Missing
coverage never asserts an empty home.

## Identity records

From 0.5.18, `location_cleared` means the physical detector that supported a
remembered point has measured a newer zero, with no current human-compatible
support at that point. The current room is unknown; independent home/identity
evidence is retained. The canonical presence includes `last_location` and
`location_clear_source_ids`; compatibility/identity records expose
`last_known_area`, `last_location_observed_at` and `location_clear_sources`.
Historical metadata does not create an active area or current occupancy.

This early exit preserves the original 90-second memory window and observation
time. Its expiry is scheduled without polling; no new sensor change is needed.
The metadata is snapshot continuity, not a new durable room-history store;
Recorder and historical images retain their separate behavior on restart.

A clear is restricted to a previously supporting source, matching precise area,
usable quality and measured zero newer than the remembered point. Current
human-compatible evidence protects the location. A different identified person
or animal does not prove that this owner remains there. Missing coverage,
ended camera tracks and zeros synthesized from overlapping zones are not
negatives. Nor does a clear assign the owner to the phone's new room.

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
