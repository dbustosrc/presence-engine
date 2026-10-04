"""Original capabilities are suggestions, not bodies or implicit ownership."""

from dataclasses import replace
import unittest

from presence_engine.configuration import AdapterType, parse_configuration
from presence_engine.configuration_ui import validate_draft
from presence_engine.discovery import (EntityDescriptor, apply_discovery, discover_candidate,
    review_candidates, candidate_source_draft)


def router(**changes):
    return replace(EntityDescriptor("registry_a", "device_tracker.endpoint", "router_example", "endpoint",
        "device_tracker", device_id="device_a", source_type="router", area_id="alpha"), **changes)


def distance(**changes):
    return replace(EntityDescriptor("registry_signal", "sensor.endpoint_receiver", "bermuda", "endpoint_receiver_a_range",
        "sensor", device_id="device_a", original_name="Distance to Receiver", unit="m", device_class="distance"), **changes)


def configuration(sources=(), identities=None):
    return parse_configuration({"schema_version": 1, "areas": {"alpha": "ground"},
        "sources": list(sources), "identities": identities or {}})


class DiscoveryReviewTests(unittest.TestCase):
    def test_router_requires_verified_capability_and_never_auto_activates(self):
        descriptor = router()
        candidate = discover_candidate(descriptor)
        self.assertEqual(candidate.adapter, AdapterType.WIFI_TRACKER)
        self.assertIsNone(candidate.suggested_area)
        plan = apply_discovery(configuration(identities={descriptor.stable_key: "person_a"}), [descriptor])
        self.assertFalse(plan.activated)
        self.assertFalse(plan.configuration.sources)
        self.assertEqual(len(plan.pending), 1)
        for variant in (router(source_type="gps"), router(source_type="bluetooth"), router(source_type=None),
                        router(tracking_type="position"), router(platform="presence_engine"), router(disabled=True)):
            self.assertIsNone(discover_candidate(variant))

    def test_disabled_and_explicit_sources_stay_excluded_from_review(self):
        config = configuration([{"source_id": "existing", "adapter": "wifi_tracker", "entity_ids": ["device_tracker.previous"],
            "entity_registry_ids": ["registry_a"], "enabled": False, "options": {"device_id": "endpoint_a"}}])
        self.assertFalse(review_candidates(config, [router()]))
        self.assertFalse(apply_discovery(config, [router()]).activated)

    def test_new_distance_is_not_hidden_by_existing_area_on_same_device(self):
        area = EntityDescriptor("registry_area", "sensor.endpoint_area", "bermuda", "endpoint", "sensor", device_id="device_a", original_name="Area")
        config = configuration([{"source_id": "area", "adapter": "bermuda_area", "entity_ids": [area.entity_id],
            "entity_registry_ids": [area.registry_id], "identity": "person_a", "options": {"target_id": "endpoint_a"}}])
        candidates = review_candidates(config, iter((area, distance())))
        self.assertEqual(len(candidates), 1)
        suggested = candidate_source_draft(candidates[0], config, (area, distance()))
        self.assertEqual(suggested["options"]["device_id"], "endpoint_a")
        self.assertEqual(suggested["identity"], "person_a")
        self.assertNotIn("area", suggested)  # The phone's registry area is not its receiver's.

    def test_distance_metrics_are_distinguished_and_nearest_range_is_not_fixed_receiver(self):
        self.assertEqual(discover_candidate(distance()).adapter, AdapterType.BERMUDA_SIGNAL)
        raw = distance(unique_id="endpoint_receiver_a_range_raw", original_name="Unfiltered Distance to Receiver")
        self.assertEqual(candidate_source_draft(discover_candidate(raw), configuration(), [raw])["options"]["metric"], "distance_unfiltered")
        for unsupported in (distance(original_name="Distance"), distance(unit=None), distance(unit="dBm"), distance(disabled=True)):
            self.assertIsNone(discover_candidate(unsupported))

    def test_unknown_owner_and_ap_room_are_not_inferred(self):
        descriptor = router(ap_attribute="connected_ap")
        suggested = candidate_source_draft(discover_candidate(descriptor), configuration(), [descriptor])
        self.assertNotIn("identity", suggested)
        self.assertNotIn("area", suggested)
        self.assertEqual(suggested["options"]["ap_attribute"], "connected_ap")
        self.assertNotIn("ap_area_map", suggested["options"])

    def test_receiver_binding_is_shared_across_devices_without_exposing_identifier(self):
        first = distance()
        second = distance(registry_id="registry_other", device_id="device_b", unique_id="other_receiver_a_range")
        config = configuration([{"source_id": "signal", "adapter": "bermuda_signal", "entity_ids": [first.entity_id],
            "options": {"device_id": "endpoint_a", "receiver_id": "physical_receiver_a", "metric": "distance"}}])
        suggested = candidate_source_draft(discover_candidate(second), config, [first, second])
        self.assertEqual(suggested["options"]["receiver_id"], "physical_receiver_a")
        self.assertNotIn("identity", suggested)

    def test_ignored_binding_survives_rename_and_never_removes_explicit_input(self):
        descriptor = EntityDescriptor("registry_radar", "binary_sensor.radar", "esphome", "radar_presence", "binary_sensor", area_id="alpha")
        ignored = apply_discovery(configuration(), [descriptor], ignored_registry_ids=("registry_radar",))
        renamed = apply_discovery(configuration(), [replace(descriptor, entity_id="binary_sensor.renamed")], ignored_registry_ids=("registry_radar",))
        self.assertFalse(ignored.activated)
        self.assertFalse(renamed.activated)
        config = configuration([{"source_id": "radar", "adapter": "binary_presence", "entity_ids": [descriptor.entity_id], "area": "alpha"}])
        self.assertEqual(apply_discovery(config, [descriptor], ignored_registry_ids=("registry_radar",)).configuration.sources, config.sources)

    def test_new_settings_are_validated_without_restricting_extension_fields(self):
        base = {"schema_version": 1, "sources": [], "discovery": {"ignored_registry_ids": ["registry_a"], "notify_new_sources": False, "extension": True}}
        validate_draft(base)
        for invalid in (None, [], {"notify_new_sources": "yes"}, {"ignored_registry_ids": [True]}, {"ignored_registry_ids": "registry_a"}):
            with self.assertRaises(ValueError):
                validate_draft({**base, "discovery": invalid})

    def test_reoffering_legacy_ready_source_does_not_automatically_activate_it(self):
        descriptor = EntityDescriptor("registry_radar", "binary_sensor.radar", "esphome", "radar_presence", "binary_sensor", area_id="alpha")
        plan = apply_discovery(configuration(), [descriptor], review_registry_ids=(descriptor.registry_id,))
        self.assertFalse(plan.activated)
        self.assertEqual(len(plan.pending), 1)

    def test_last_seen_area_is_not_suggested_as_current_bermuda_area(self):
        descriptor = EntityDescriptor("registry_a", "sensor.endpoint_area_last_seen", "bermuda", "endpoint_area_last_seen", "sensor", original_name="Area Last Seen")
        self.assertIsNone(discover_candidate(descriptor))

    def test_explicit_derived_tracker_exclusions_are_not_reoffered(self):
        config = configuration([{"source_id": "home", "adapter": "person_home", "entity_ids": ["person.owner"],
            "identity": "person_a", "options": {"ignored_source_ids": ["device_tracker.endpoint"], "ignored_source_prefixes": ["device_tracker.derived_"]}}])
        for d in (router(), router(entity_id="device_tracker.derived_other")):
            self.assertFalse(review_candidates(config, [d]))
            self.assertFalse(apply_discovery(config, [d]).pending)

    def test_bermuda_area_does_not_inherit_phone_administrative_area_or_floor(self):
        descriptor = EntityDescriptor("registry_area", "sensor.endpoint_area", "bermuda", "endpoint_area", "sensor",
            original_name="Area", area_id="alpha", device_id="device_a")
        suggested = candidate_source_draft(discover_candidate(descriptor), configuration(), [descriptor])
        self.assertNotIn("area", suggested)
        self.assertNotIn("floor", suggested)


if __name__ == "__main__":
    unittest.main()
