"""Bounded scalar radar telemetry, separate from occupancy and identity."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
import math
from typing import TYPE_CHECKING, Mapping

from .engine import require_aware

if TYPE_CHECKING:
    from .adapters.base import AdapterEnvelope
    from .configuration import SourceDefinition


RADAR_METRICS = ("x", "y", "distance", "moving_distance", "still_distance", "speed")


@dataclass(frozen=True, slots=True)
class RadarSample:
    """One sensor-frame scalar; a target slot is not a persistent body ID."""

    source_id: str
    entity_id: str
    target_slot: str
    metric: str
    observed_at: datetime
    received_at: datetime
    value: float | None
    unit: str
    status: str
    clock_basis: str = "envelope"
    sensor_frame: str = ""
    coverage_group: str | None = None

    def __post_init__(self):
        require_aware(self.observed_at, "radar observed_at")
        require_aware(self.received_at, "radar received_at")
        if self.observed_at > self.received_at:
            raise ValueError("radar observation cannot be after reception")
        if not self.source_id or not self.entity_id or not self.target_slot or not self.sensor_frame or self.metric not in RADAR_METRICS:
            raise ValueError("radar requires a source, entity, slot and supported metric")
        if self.clock_basis not in {"envelope", "ha_state_update"}:
            raise ValueError("invalid radar clock basis")
        if self.status not in {"valid", "unknown", "unavailable", "invalid_value", "invalid_unit"}:
            raise ValueError("invalid radar status")
        if self.status == "valid":
            units = {"m/s", "cm/s", "mm/s"} if self.metric == "speed" else {"m", "cm", "mm"}
            if type(self.value) not in (int, float) or not math.isfinite(self.value) or self.unit not in units:
                raise ValueError("valid radar sample requires finite value and compatible unit")
            if self.metric.endswith("distance") and self.value < 0:
                raise ValueError("radar range cannot be negative")
        elif self.value is not None:
            raise ValueError("missing radar sample cannot carry a value")

    def encode(self):
        return {**asdict(self), "observed_at": self.observed_at.isoformat(),
                "received_at": self.received_at.isoformat()}

    @classmethod
    def decode(cls, raw):
        return cls(**{**raw, "observed_at": datetime.fromisoformat(raw["observed_at"]),
                      "received_at": datetime.fromisoformat(raw["received_at"])})


def radar_sample(definition: SourceDefinition, envelope: AdapterEnvelope) -> RadarSample:
    binding = definition.options["radar_channels"][envelope.channel]
    state = str(envelope.payload.get("state", ""))
    attributes = envelope.payload.get("attributes", {})
    unit = attributes.get("unit_of_measurement", "") if isinstance(attributes, Mapping) else ""
    unit = unit if isinstance(unit, str) else ""
    status, value = "valid", None
    if state.casefold() in {"unknown", "unavailable", "none", ""}:
        status = "unavailable" if state.casefold() == "unavailable" else "unknown"
    else:
        try:
            value = float(state)
            if not math.isfinite(value) or binding["metric"].endswith("distance") and value < 0:
                status, value = "invalid_value", None
        except ValueError:
            status = "invalid_value"
        units = {"m/s", "cm/s", "mm/s"} if binding["metric"] == "speed" else {"m", "cm", "mm"}
        if status == "valid" and unit not in units:
            status, value = "invalid_unit", None
    stamp = envelope.payload.get("last_updated", envelope.observed_at)
    observed = datetime.fromisoformat(stamp) if isinstance(stamp, str) else stamp
    return RadarSample(definition.source_id, envelope.channel, binding["target_slot"],
                       binding["metric"], observed, envelope.received_at, value, unit, status,
                       "ha_state_update" if "last_updated" in envelope.payload else "envelope",
                       definition.dependency_group or definition.source_id, definition.coverage_group)


class RadarHistory:
    """Keep per-channel clocks; never manufacture a synchronous XY frame."""

    def __init__(self, sources, now):
        self.definitions = {s.source_id: s for s in sources if s.enabled and s.options.get("radar_channels")}
        self.now = now
        self.samples: dict[tuple[str, str], list[RadarSample]] = {}
        self.latest: dict[tuple[str, str], RadarSample] = {}
        self.truncated: set[tuple[str, str]] = set()

    def matches(self, sample):
        definition = self.definitions.get(sample.source_id)
        binding = definition.options["radar_channels"].get(sample.entity_id) if definition else None
        return bool(binding and sample.target_slot == binding["target_slot"]
                    and sample.metric == binding["metric"] and sample.received_at <= self.now()
                    and sample.sensor_frame == (definition.dependency_group or definition.source_id)
                    and sample.coverage_group == definition.coverage_group)

    def retain(self, sample):
        if not self.matches(sample):
            return
        key = (sample.source_id, sample.entity_id)
        prior = self.latest.get(key)
        if prior and (sample.observed_at <= prior.observed_at
                      or (sample.value, sample.unit, sample.status) == (prior.value, prior.unit, prior.status)):
            return
        self.latest[key] = sample
        self.trim()
        options = self.definitions[sample.source_id].options
        if self.now() - sample.observed_at >= timedelta(seconds=options.get("history_seconds", 120)):
            return
        history = self.samples.setdefault(key, [])
        history.append(sample)
        limit = int(options.get("history_limit", 32))
        if len(history) > limit:
            del history[:-limit]
            self.truncated.add(key)

    def trim(self):
        for key, history in self.samples.items():
            cutoff = self.now() - timedelta(seconds=self.definitions[key[0]].options.get("history_seconds", 120))
            self.samples[key] = [s for s in history if s.observed_at > cutoff]

    def payload(self, *, include_samples=False):
        self.trim()
        result = []
        for source_id, definition in sorted(self.definitions.items()):
            for entity_id, binding in sorted(definition.options["radar_channels"].items()):
                key = (source_id, entity_id)
                history = self.samples.get(key, [])
                latest = history[-1] if history else None
                item = {"source_id": source_id, "entity_id": entity_id, **binding,
                        "sensor_frame": definition.dependency_group or source_id,
                        "coverage_group": definition.coverage_group,
                        "sample_count": len(history), "truncated": key in self.truncated,
                        "latest_value": latest.value if latest else None, "unit": latest.unit if latest else None,
                        "status": latest.status if latest else "no_recent_samples",
                        "observed_at": latest.observed_at.isoformat() if latest else None,
                        "received_at": latest.received_at.isoformat() if latest else None,
                        "clock_basis": latest.clock_basis if latest else None}
                if include_samples:
                    item["samples"] = [s.encode() for s in history]
                result.append(item)
        return result
