# Generic regression matrix

The repository contains no installation names or captured household data. This
matrix names the generic invariant represented by each unit test. Mapping to a
private installation corpus belongs outside this repository.

| Invariant | Executable proof |
|---|---|
| One moving person is not made into two exact people by a stale adjacent location | `test_stale_room_plus_new_adjacent_count_is_not_two_exact_people` |
| A real visitor is not hidden by a registered device or known person | `test_stale_device_does_not_hide_a_real_visitor`, `test_recognized_person_does_not_hide_nonadjacent_visitor` |
| A transient aggregate spike remains an interval | `test_unstable_count_spike_remains_interval`, `test_transient_aggregate_two_is_provisional` |
| Sustained independent evidence can support an exact second person | `test_same_area_stable_count_two_preserves_second_person`, `test_sustained_aggregate_two_becomes_exact` |
| One native animal target remains one trajectory | `test_same_animal_target_across_areas_is_one_trajectory` |
| Overlapping animal aggregates remain explicitly ambiguous | `test_two_animal_aggregates_with_overlapping_coverage_remain_ambiguous` |
| Person and animal evidence cannot merge | `test_person_and_animal_are_never_merged` |
| A stationary device cannot override a directly recognized owner | `test_stationary_device_does_not_duplicate_recognized_owner_elsewhere` |
| Floor-scoped direct identity can be refined by current room evidence | `test_floor_scope_identity_can_be_refined_by_current_area_evidence` |
| Floor-scoped device association plus anonymous room evidence stays ambiguous | `test_device_floor_scope_plus_area_evidence_keeps_visitor_uncertainty` |
| Same-area device and aggregate evidence do not duplicate a person | `test_registered_device_corroborated_in_same_area_is_one_person` |
| Event and aggregate from the same dependency are counted once | `test_event_and_aggregate_in_same_dependency_group_are_not_added` |
| Previous direct trajectory resists a contradictory device jump | `test_previous_direct_path_beats_newer_device_jump` |
| Current zones beat profiles; accumulated zones are not current location | `test_current_zone_has_priority_over_profile`, `test_entered_zone_is_not_current_location` |
| PTZ motion never reuses a requested or previous room as fact | `test_moving_never_uses_requested_or_previous_profile` |
| A late zone revises the same detection without rewriting its event time | `test_late_current_zone_revises_same_event_without_retrodating` |
| Late identity does not rewrite event or spatial time | `test_recognition_time_does_not_replace_detection_time`, `test_late_identity_does_not_rewrite_event_time_or_location` |
| Partial updates cannot erase unrelated dimensions | `test_partial_identity_envelope_cannot_clear_existing_location`, `test_explicit_revision_can_clear_a_dimension` |
| Removing/offlining a source affects only its evidence and degrades coverage | `test_source_removal_does_not_remove_other_sources`, `test_missing_source_degrades_coverage_without_asserting_empty` |
| The core has no platform, network or installation coupling | `test_core_has_no_platform_or_network_imports`, `test_core_does_not_contain_installation_identifiers` |

Notification replacement and recipient policy are deliberately not implemented
in the core. The core supplies stable detection identity and revision so that a
later consumer can make that policy without recomputing the event.
