from __future__ import annotations

from presence_engine.configuration import EngineConfiguration, parse_configuration


def integration_config() -> EngineConfiguration:
    return parse_configuration(
        {
            "schema_version": 1,
            "areas": {
                "alpha": "floor_alpha",
                "beta": "floor_alpha",
                "gamma": "floor_beta",
            },
            "adjacency": {
                "alpha": ["beta"],
                "beta": ["alpha"],
                "gamma": [],
            },
            "identities": {"device_a": "person_a"},
            "cameras": {
                "camera_a": {
                    "floor": "floor_alpha",
                    "zone_to_area": {"zone_alpha": "alpha", "zone_beta": "beta"},
                    "profile_to_area": {
                        "profile_alpha": "alpha",
                        "profile_beta": "beta",
                    },
                    "profile_entity_id": "select.camera_profile",
                    "preset_entity_id": "select.camera_preset",
                    "movement_entity_id": "sensor.camera_motion_state",
                    "stable_states": ["available"],
                    "moving_states": ["moving"],
                }
            },
            "sources": [
                {
                    "source_id": "frigate_events",
                    "adapter": "frigate_events",
                    "topics": ["frigate/events"],
                    "options": {"labels": ["person", "dog"]},
                },
                {
                    "source_id": "frigate_faces",
                    "adapter": "frigate_face",
                    "topics": ["frigate/tracked_object_update"],
                    "options": {"recognition_threshold": 0.8},
                },
                {
                    "source_id": "device_area",
                    "adapter": "bermuda_area",
                    "entity_ids": ["sensor.device_area"],
                    "floor": "floor_alpha",
                    "identity": "person_a",
                    "target_kind": "device",
                    "spatial_quality": "medium",
                    "options": {"area_map": {"Alpha Room": "alpha"}},
                },
                {
                    "source_id": "area_count",
                    "adapter": "count",
                    "entity_ids": ["sensor.area_count"],
                    "area": "alpha",
                    "floor": "floor_alpha",
                    "target_kind": "person",
                    "spatial_quality": "high",
                    "dependency_group": "area_counter",
                },
            ],
        }
    )
