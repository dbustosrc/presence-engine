# Domain contract v1

The core accepts normalized observations and emits immutable projections. It
does not discover devices, subscribe to transports, operate actuators or choose
notification recipients.

## Observation

An observation has four independent clocks:

- `detected_at`: when the physical event began or was first observed;
- claim-specific `observed_at`: when identity, location, count or image became
  true or was measured;
- `received_at`: when the envelope reached the engine;
- resolver `evaluated_at`: when a snapshot was computed.

An adapter identifies its source and may provide target, dependency and
coverage groups. These identifiers have different meanings:

- `target_id` joins updates known to describe the same native target;
- `dependency_group` prevents adding an event and an aggregate derived from the
  same producer;
- `coverage_group` records sensors whose fields of view overlap and therefore
  cannot safely be summed.

Each mutable dimension has an independent `RevisionStamp`. An update carrying
explicit stamps changes only those dimensions. An update without stamps is a
convenience full envelope for non-empty claims; it cannot erase omitted claims.
Erasing a claim requires `None` plus a newer explicit revision.

## DetectionResult

A detection is keyed by the external event identity and can be enriched without
changing `detected_at`. Identity and spatial observation times stay separate.
Its monotonically increasing revision lets a consumer distinguish an exact
duplicate from a useful refinement of the same event.

The projection also carries the identity method and score, contributing source
IDs, and the image belonging to that detection when one exists. The image keeps
its own observation time and area; consumers must not treat either as the
current location of an identified person. Supported opaque image references are
projected to a browser-ready authenticated URL so presentation code does not
depend on a camera integration's storage convention. When the origin provides
an event clip, the same image metadata carries its browser-ready clip URL.

## PresenceSnapshot

A snapshot is a current, deterministic projection of active observations plus
an explicitly supplied previous snapshot. It keeps devices outside the human
presence collection. A linked device identifies an association, not proof that
its owner occupies the same room.

Counts are closed intervals. Exact values use the same minimum and maximum;
uncertain correlation preserves the wider interval rather than inventing or
hiding a person. Person, animal and unknown-living hypotheses are never merged
solely because their time and area match.

`unavailable_source_ids` lists the configured sources responsible for
`coverage_degraded`. An unavailable source never means that its target is away
or that the covered area is empty.

Camera evidence may be guarded by exact availability entities. While a camera
is unavailable, its active evidence is removed and subsequent visual events
are ignored. Recovery permits only newly received evidence; stale events are
not replayed as current. Other cameras and non-visual sources remain usable.

Known native classification is preserved separately from the broad target
kind. Identity and location metadata retain their own quality, observation
time, method and source identifiers; consumers do not infer one dimension
from the other.

## Public projections

Public entities are deterministic views of one `PresenceSnapshot`
revision. The general sensor, coverage sensor, identity tracker and identity
record therefore expose the same snapshot identifier and revision. A missing
identity hypothesis produces an unknown tracker state, never an invented
`not_home` state. Image metadata is retained independently from current
location.

## Geometry

Current object zones take precedence over a PTZ profile. Entered/accumulated
zones never represent current location. While moving, or when telemetry is
invalid, only the camera scope is emitted. A profile can resolve an area only
after an adapter confirms that the physical camera reached that profile.

## Determinism

The resolver receives all inputs, configuration, previous state and clock as
arguments. Equal inputs produce equal results regardless of input order. No
module imports Home Assistant, MQTT, network clients or installation-specific
identifiers.
