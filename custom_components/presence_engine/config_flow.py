"""UI configuration for Presence Engine."""

from __future__ import annotations

from copy import deepcopy
import json
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlowWithReload
from homeassistant.core import callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers import area_registry as ar, floor_registry as fr
from homeassistant.helpers.selector import selector, NumberSelector, NumberSelectorConfig, NumberSelectorMode

from .configuration import AdapterType, ConfigurationError, parse_configuration
from .configuration_ui import (
    EMPTY_CONFIGURATION, bind_entities, delete_item, mapping_rows, patch_item,
    rows_mapping, validate_draft,
)
from .discovery import apply_discovery, resolve_raw_registry_bindings
from .ha_discovery import collect_entity_descriptors
from .engine import Quality, TargetKind
from .const import (
    CONF_COMPARISON_MODE,
    CONF_CONFIGURATION,
    CONF_MAX_RECORDS,
    CONF_SAVE_DELAY,
    DEFAULT_COMPARISON_MODE,
    DEFAULT_MAX_RECORDS,
    DEFAULT_SAVE_DELAY,
    DOMAIN,
)


def _select(values, *, multiple=False, custom=False):
    options = list(values)
    if any(isinstance(value, dict) for value in options):
        options = [value if isinstance(value, dict) else {"value": value, "label": value} for value in options]
    return selector({"select": {"options": options, "multiple": multiple, "custom_value": custom, "mode": "dropdown", "translation_key": "choices"}})


def _text(*, multiple=False):
    return selector({"text": {"multiple": multiple}})


def _mapping(values, value_selector):
    if "select" in value_selector:
        select = value_selector["select"]
        if any(isinstance(value, dict) for value in select["options"]):
            select["options"] = [value if isinstance(value, dict) else {"value": value, "label": value} for value in select["options"]]
    return selector({"object": {
        "multiple": True, "label_field": "key",
        "fields": {
            "key": {"label": "Name / ID", "required": True, "selector": {"text": {}}},
            "value": {"label": "Assignment", "required": True, "selector": value_selector},
        },
    }})


def _field(schema, name, control, values, *, required=False, default=None):
    marker = vol.Required if required else vol.Optional
    value = values.get(name, default)
    schema[marker(name, default=value) if value is not None else marker(name)] = control


def _group(schema, name, fields):
    grouped = {key: schema.pop(key) for key in list(schema) if key.schema in fields}
    schema[vol.Required(name, default=dict)] = section(vol.Schema(grouped), {"collapsed": True})


class PresenceEngineConfigFlow(ConfigFlow, domain=DOMAIN):
    """Create and reconfigure the single engine instance."""

    VERSION = 1

    def __init__(self) -> None:
        self._draft = deepcopy(EMPTY_CONFIGURATION)
        self._reconfiguring = False
        self._key = ""
        self._section = ""
        self._adapter = "binary_presence"

    def _descriptors(self):
        return collect_entity_descriptors(self.hass)

    def _navigation(self, *, add=True):
        spanish = getattr(getattr(self.hass, "config", None), "language", "en").startswith("es")
        result = [{"value": "__back__", "label": "Volver" if spanish else "Back"}]
        if add:
            result.insert(0, {"value": "__add__", "label": "Agregar nuevo" if spanish else "Add new"})
        return result

    def _areas(self):
        registry = ar.async_get(self.hass)
        return [{"value": key, "label": registry.async_get_area(key).name if registry.async_get_area(key) else key.replace("_", " ").title()}
                for key in self._draft["areas"]]

    def _floors(self):
        values = {key: key.replace("_", " ").title() for key in self._draft["areas"].values()}
        values.update({floor.floor_id: floor.name for floor in fr.async_get(self.hass).floors.values()})
        return [{"value": key, "label": label} for key, label in values.items()]

    def _identities(self):
        identities = set(self._draft["identities"].values())
        identities.update(source["identity"] for source in self._draft["sources"] if source.get("identity"))
        for source in self._draft["sources"]:
            identities.update(source.get("options", {}).get("identity_map", {}).values())
        runtime = getattr(self._get_reconfigure_entry(), "runtime_data", None) if self._reconfiguring else None
        if runtime:
            identities.update(runtime.faces.observed.values())
        return sorted(identities)

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        return await self.async_step_menu()

    async def async_step_reconfigure(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        self._reconfiguring = True
        self._draft = resolve_raw_registry_bindings(
            self._get_reconfigure_entry().data[CONF_CONFIGURATION], self._descriptors(),
        )
        # Preserve the supported API import used by existing installations.
        if user_input is not None and CONF_CONFIGURATION in user_input:
            result = await self.async_step_advanced(user_input)
            return await self.async_step_save({}) if not result.get("errors") else result
        return await self.async_step_menu()

    async def async_step_menu(self, user_input=None):
        return self.async_show_menu(step_id="menu", menu_options=[
            "areas", "identities", "cameras", "sources", "discovery", "frigate", "advanced", "save",
        ])

    async def _choose(self, section, step_id, user_input):
        self._section = section
        if user_input is not None:
            self._key = user_input["item"]
            if self._key == "__back__":
                return await self.async_step_menu()
            if self._key == "__add__":
                self._key = ""
                if section == "sources":
                    return await self.async_step_source_type()
            return await getattr(self, f"async_step_{step_id[:-1]}_edit")()
        if section == "sources":
            items = [{"value": item["source_id"], "label": f"{item['source_id']} · {item['adapter']}" + (" · disabled" if not item.get("enabled", True) else "")}
                     for item in self._draft[section]]
        elif section == "identities":
            items = [{"value": key, "label": key.replace("_", " ").title()} for key in self._identities()]
        elif section == "areas":
            items = self._areas()
        else:
            items = list(self._draft[section])
        return self.async_show_form(step_id=step_id, data_schema=vol.Schema({
            vol.Required("item"): _select([*self._navigation(), *items]),
        }))

    async def async_step_areas(self, user_input=None):
        return await self._choose("areas", "areas", user_input)

    async def async_step_identities(self, user_input=None):
        # The plural is irregular; keep explicit native step names.
        if user_input is not None and user_input["item"] not in {"__add__", "__back__"}:
            self._key = user_input["item"]
            return await self.async_step_identity_edit()
        if user_input is not None and user_input["item"] == "__add__":
            self._key = ""
            return await self.async_step_identity_edit()
        return await self._choose("identities", "identities", user_input)

    async def async_step_cameras(self, user_input=None):
        return await self._choose("cameras", "cameras", user_input)

    async def async_step_sources(self, user_input=None):
        return await self._choose("sources", "sources", user_input)

    async def async_step_source_type(self, user_input=None):
        if user_input is not None:
            self._adapter = user_input["adapter"]
            return await self.async_step_source_edit()
        return self.async_show_form(step_id="source_type", data_schema=vol.Schema({
            vol.Required("adapter"): _select([item.value for item in AdapterType]),
        }))

    async def async_step_area_edit(self, user_input=None):
        values = {"id": self._key, "floor": self._draft["areas"].get(self._key),
                  "neighbours": self._draft["adjacency"].get(self._key, [])}
        schema = {}
        _field(schema, "id", _text(), values, required=True)
        _field(schema, "ha_area", selector({"area": {}}), {})
        _field(schema, "floor", _select(self._floors(), custom=True), values, required=True)
        _field(schema, "neighbours", _select(self._areas(), multiple=True), values, default=[])
        _field(schema, "remove", bool, {}, default=False)
        def edit(data):
            draft = deepcopy(self._draft)
            key = self._key or data.get("ha_area") or data["id"]
            if not self._key and key in draft["areas"]:
                raise ConfigurationError("Area ID already exists")
            draft["areas"][key] = data["floor"]
            draft["adjacency"][key] = data.get("neighbours", [])
            return draft
        return await self._edit("area_edit", schema, user_input, edit, "areas")

    async def async_step_identity_edit(self, user_input=None):
        bindings = {key: value for key, value in self._draft["identities"].items() if value == self._key}
        descriptors = self._descriptors()
        entities = sorted({item.entity_id for item in descriptors if item.stable_key in bindings} | {
            entity_id for source in self._draft["sources"]
            if source.get("identity") == self._key and source["adapter"] in {"person_home", "bermuda_area"}
            for entity_id in source.get("entity_ids", [])
        })
        face_names = set()
        for source in self._draft["sources"]:
            face_names.update(name for name, identity in source.get("options", {}).get("identity_map", {}).items() if identity == self._key)
        runtime = getattr(self._get_reconfigure_entry(), "runtime_data", None) if self._reconfiguring else None
        catalogue = sorted(set(runtime.faces.catalogue) | set(runtime.faces.observed)) if runtime else []
        if runtime:
            face_names.update(name for name, identity in runtime.faces.observed.items() if identity == self._key)
        values = {"id": self._key, "entities": entities, "face_names": sorted(face_names), "bindings": mapping_rows(bindings)}
        schema = {}
        _field(schema, "id", _text(), values, required=True)
        _field(schema, "entities", selector({"entity": {"multiple": True, "filter": [{"domain": "person"}, {"domain": "sensor", "integration": "bermuda"}]}}), values)
        _field(schema, "face_names", _select(sorted(set(catalogue) | face_names), multiple=True, custom=True), values)
        _field(schema, "bindings", _mapping({}, {"text": {}}), values)
        def edit(data):
            draft = deepcopy(self._draft)
            key = self._key or data["id"]
            if not self._key and key in self._identities():
                raise ConfigurationError("Identity ID already exists")
            for binding in bindings:
                draft["identities"].pop(binding, None)
            supplied = rows_mapping(data.get("bindings", []))
            selected = set(data.get("entities", []))
            for descriptor in descriptors:
                if descriptor.entity_id in selected:
                    supplied[descriptor.stable_key] = key
                elif descriptor.entity_id in entities:
                    supplied.pop(descriptor.stable_key, None)
            # This entry declares a canonical identity, not evidence of presence.
            if key not in parse_configuration(draft).identity_ids and not supplied:
                supplied[f"identity:{key}"] = key
            if any(identity != key for identity in supplied.values()):
                raise ConfigurationError("All bindings must use this identity ID")
            draft["identities"].update(supplied)
            for source in draft["sources"]:
                if source["adapter"] in {"person_home", "bermuda_area"}:
                    channel_entities = set(source.get("entity_ids", []))
                    if channel_entities & selected:
                        if not channel_entities <= selected:
                            raise ConfigurationError("Select every entity of a shared identity source or split that source first")
                        source["identity"] = key
                    elif source.get("identity") == key and channel_entities & set(entities):
                        source["identity"] = None
                if source["adapter"] != "frigate_face":
                    continue
                mapping = source.setdefault("options", {}).setdefault("identity_map", {})
                for name in list(mapping):
                    if mapping[name] == key:
                        del mapping[name]
                mapping.update({name: key for name in data.get("face_names", [])})
            if data.get("face_names") and not any(source["adapter"] == "frigate_face" for source in draft["sources"]):
                raise ConfigurationError("Configure a Frigate face source first")
            return draft
        return await self._edit("identity_edit", schema, user_input, edit, "identities")

    async def async_step_camera_edit(self, user_input=None):
        item = deepcopy(self._draft["cameras"].get(self._key, {}))
        values = {"id": self._key, **item}
        schema = {}
        _field(schema, "id", _text(), values, required=True)
        _field(schema, "floor", _select(self._floors(), custom=True), values, required=True)
        _field(schema, "fixed_area", _select(self._areas()), values)
        _field(schema, "admission_mode", _select(["any_detection", "mapped_current_zone"]), values, required=True, default="any_detection")
        for field in ("zone_to_area", "profile_to_area"):
            values[field] = mapping_rows(item.get(field, {}))
            _field(schema, field, _mapping({}, {"select": {"options": self._areas()}}), values, default=[])
        for field in ("profile_entity_id", "preset_entity_id", "movement_entity_id"):
            _field(schema, field, selector({"entity": {}}), values)
        _field(schema, "availability_entity_ids", selector({"entity": {"multiple": True}}), values, default=[])
        for field, default in (("stable_states", ["available"]), ("moving_states", ["moving"]),
                               ("availability_unavailable_states", ["unknown", "unavailable", "none", "", "off", "down", "disconnected"])):
            _field(schema, field, _text(multiple=True), values, default=default)
        _field(schema, "remove", bool, {}, default=False)
        _group(schema, "ptz", {"profile_to_area", "profile_entity_id", "preset_entity_id", "movement_entity_id", "stable_states", "moving_states"})
        _group(schema, "health", {"availability_entity_ids", "availability_unavailable_states"})
        def edit(data):
            key = self._key or data["id"]
            if not self._key and key in self._draft["cameras"]:
                raise ConfigurationError("Camera ID already exists")
            changes = {field: data.get(field) for field in ("floor", "fixed_area", "admission_mode")}
            for field in ("zone_to_area", "profile_to_area"):
                changes[field] = rows_mapping(data.get(field, []))
            for field in ("stable_states", "moving_states", "availability_unavailable_states"):
                changes[field] = data[field]
            for field, registry_field in (("profile_entity_id", "profile_registry_id"), ("preset_entity_id", "preset_registry_id"), ("movement_entity_id", "movement_registry_id"), ("availability_entity_ids", "availability_registry_ids")):
                bind_entities(item, field, registry_field, data.get(field, [] if field.endswith("ids") else None), self._descriptors())
                if field in item:
                    changes[field] = item[field]
                if registry_field in item:
                    changes[registry_field] = item[registry_field]
            return patch_item(self._draft, "cameras", key, changes)
        return await self._edit("camera_edit", schema, user_input, edit, "cameras")

    async def async_step_source_edit(self, user_input=None):
        item = deepcopy(next((item for item in self._draft["sources"] if item["source_id"] == self._key), {}))
        adapter = item.get("adapter", self._adapter)
        values = {"id": self._key, **item}
        schema = {}
        _field(schema, "id", _text(), values, required=True)
        _field(schema, "enabled", bool, values, required=True, default=True)
        mqtt_source = adapter in {"frigate_events", "frigate_face"}
        if mqtt_source:
            topic = "frigate/events" if adapter == "frigate_events" else "frigate/tracked_object_update"
            _field(schema, "topics", _text(multiple=True), values, required=True, default=[topic])
        else:
            _field(schema, "entity_ids", selector({"entity": {"multiple": True}}), values, required=True, default=[])
        for field, values_select in (("area", self._areas()), ("floor", self._floors()), ("identity", self._identities()), ("camera_id", list(self._draft["cameras"]))):
            _field(schema, field, _select(values_select, custom=field == "identity"), values)
        for field, choices, default in (("target_kind", [item.value for item in TargetKind], "unknown_living"),
                                         ("spatial_quality", [item.value for item in Quality], "unknown"),
                                         ("availability_role", ["auto", "coverage", "observation"], "auto")):
            _field(schema, field, _select(choices), values, default=default)
        for field in ("dependency_group", "coverage_group"):
            _field(schema, field, _text(), values)
        _field(schema, "expires_after_seconds", selector({"number": {"min": 1, "mode": "box"}}), values)
        options = deepcopy(item.get("options", {}))
        option_fields = {"location_method": _text(), "target_id": _text()}
        if adapter == "frigate_events":
            option_fields["labels"] = _text(multiple=True)
        if adapter == "frigate_face":
            option_fields["recognition_threshold"] = selector({"number": {"min": 0, "max": 1, "step": 0.01, "mode": "box"}})
            options.setdefault("recognition_threshold", 0.8)
            option_fields["identity_map"] = _mapping({}, {"select": {"options": self._identities(), "custom_value": True}})
        if adapter == "bermuda_area":
            option_fields["area_map"] = _mapping({}, {"select": {"options": self._areas()}})
        if adapter == "mtr_count":
            option_fields["total_entity_id"] = selector({"entity": {"domain": "sensor"}})
            option_fields["zone_areas"] = _mapping({}, {"select": {"options": ["", *self._areas()]}})
        if adapter == "person_home":
            option_fields["ignored_source_ids"] = selector({"entity": {"multiple": True}})
            option_fields["ignored_source_prefixes"] = _text(multiple=True)
        if adapter == "source_health":
            option_fields["healthy_states"] = _text(multiple=True)
            option_fields["unhealthy_states"] = _text(multiple=True)
        mapping_fields = {"identity_map", "zone_areas", "area_map"}
        for field, control in option_fields.items():
            value = options.get(field)
            if field in mapping_fields:
                value = mapping_rows({key: value if value is not None else "" for key, value in (value or {}).items()})
            _field(schema, field, control, {field: value}, required=field in {"recognition_threshold", "total_entity_id"})
        _group(schema, "advanced_source", {"target_kind", "spatial_quality", "availability_role", "dependency_group", "coverage_group", "expires_after_seconds", "location_method", "target_id"})
        def edit(data):
            key = self._key or data["id"]
            if not self._key and any(source["source_id"] == key for source in self._draft["sources"]):
                raise ConfigurationError("Source ID already exists")
            changes = {"adapter": adapter, "enabled": data["enabled"]}
            for field in ("area", "floor", "identity", "camera_id", "dependency_group", "coverage_group", "expires_after_seconds", "target_kind", "spatial_quality", "availability_role"):
                changes[field] = data.get(field) or None
            if mqtt_source:
                changes["topics"] = data["topics"]
            else:
                bind_entities(item, "entity_ids", "entity_registry_ids", data["entity_ids"], self._descriptors())
                changes["entity_ids"] = item["entity_ids"]
                changes["entity_registry_ids"] = item.get("entity_registry_ids", [])
            for field in option_fields:
                value = data.get(field)
                if field in mapping_fields:
                    value = rows_mapping(value or [])
                    if field == "zone_areas":
                        value = {key: area or None for key, area in value.items()}
                if value not in (None, "", [], {}) or value == {} and field in options:
                    options[field] = value
                else:
                    options.pop(field, None)
            changes["options"] = options
            return patch_item(self._draft, "sources", key, changes)
        return await self._edit("source_edit", schema, user_input, edit, "sources")

    async def _edit(self, step_id, schema, user_input, edit, section):
        errors = {}
        if user_input is not None:
            suggested = user_input
            user_input = dict(user_input)
            for name in ("ptz", "health", "advanced_source"):
                user_input.update(user_input.pop(name, {}))
            try:
                if self._key and user_input.get("id") != self._key:
                    raise ConfigurationError("Existing IDs are stable; create a new item instead of renaming")
                if user_input.get("remove"):
                    if section == "identities":
                        raise ConfigurationError("Remove identity associations through their sources; records are retained")
                    draft = delete_item(self._draft, section, self._key)
                else:
                    draft = edit(user_input)
                    validate_draft(draft)
            except (ConfigurationError, KeyError, TypeError, ValueError) as err:
                errors["base"] = "invalid_configuration"
                return self.async_show_form(step_id=step_id, data_schema=self.add_suggested_values_to_schema(vol.Schema(schema), suggested), errors=errors,
                                            description_placeholders={"detail": str(err)})
            self._draft = draft
            return await self.async_step_menu()
        return self.async_show_form(step_id=step_id, data_schema=vol.Schema(schema), errors=errors, description_placeholders={"detail": ""})

    async def async_step_discovery(self, user_input=None):
        plan = apply_discovery(parse_configuration(self._draft), self._descriptors())
        configured = {item["source_id"] for item in self._draft["sources"]}
        automatic = [item for item in plan.configuration.sources if item.source_id not in configured]
        choices = [{"value": item.source_id, "label": f"{item.entity_ids[0]} · active"} for item in automatic]
        choices.extend({"value": item.descriptor.registry_id, "label": f"{item.descriptor.entity_id} · {', '.join(item.missing_configuration)}"} for item in plan.pending)
        if user_input is not None:
            selected = user_input["item"]
            if selected == "__back__":
                return await self.async_step_menu()
            source = next((item for item in automatic if item.source_id == selected), None)
            if source:
                # MappingProxyType is deliberately not passed to asdict/deepcopy.
                from .configuration_ui import source_to_raw
                self._draft["sources"].append(source_to_raw(source))
                self._key = source.source_id
            else:
                candidate = next(item for item in plan.pending if item.descriptor.registry_id == selected)
                self._key = ""
                self._adapter = candidate.adapter.value
                self._draft["sources"].append({"source_id": f"manual_{selected.replace('-', '')[:12]}", "adapter": self._adapter,
                                                "entity_ids": [candidate.descriptor.entity_id], "entity_registry_ids": [candidate.descriptor.registry_id],
                                                "enabled": False})
                self._key = self._draft["sources"][-1]["source_id"]
            return await self.async_step_source_edit()
        return self.async_show_form(step_id="discovery", data_schema=vol.Schema({vol.Required("item"): _select([*self._navigation(add=False), *choices])}))

    async def async_step_frigate(self, user_input=None):
        values = self._draft.get("frigate", {})
        if user_input is not None:
            user_input = dict(user_input)
            refresh = user_input.pop("refresh_catalogue", False)
            draft = deepcopy(self._draft)
            draft["frigate"] = {**values, **user_input}
            try:
                validate_draft(draft)
            except (ConfigurationError, ValueError, TypeError) as err:
                return self.async_show_form(step_id="frigate", data_schema=self._frigate_schema(user_input), errors={"base": "invalid_configuration"}, description_placeholders={"detail": str(err)})
            self._draft = draft
            if refresh and self._reconfiguring:
                runtime = getattr(self._get_reconfigure_entry(), "runtime_data", None)
                if runtime and values == draft["frigate"]:
                    await runtime.async_refresh_faces(force=True)
            return await self.async_step_menu()
        return self.async_show_form(step_id="frigate", data_schema=self._frigate_schema(values), description_placeholders={"detail": ""})

    def _frigate_schema(self, values):
        schema = {}
        _field(schema, "discover_faces", bool, values, default=True)
        _field(schema, "url", selector({"text": {"type": "url"}}), values, default="")
        _field(schema, "username", _text(), values, default="")
        _field(schema, "password", selector({"text": {"type": "password"}}), values, default="")
        _field(schema, "availability_topic", _text(), values, default="frigate/available")
        _field(schema, "cookie_name", _text(), values, default="frigate_token")
        _field(schema, "refresh_catalogue", bool, {}, default=False)
        return vol.Schema(schema)

    async def async_step_save(self, user_input=None):
        if user_input is None:
            return self.async_show_form(step_id="save", data_schema=vol.Schema({}), description_placeholders={"detail": "", "areas": str(len(self._draft["areas"])), "cameras": str(len(self._draft["cameras"])), "sources": str(len(self._draft["sources"]))})
        try:
            validate_draft(self._draft)
        except (ConfigurationError, KeyError, TypeError, ValueError) as err:
            return self.async_show_form(step_id="save", data_schema=vol.Schema({}), errors={"base": "invalid_configuration"}, description_placeholders={"detail": str(err), "areas": "", "cameras": "", "sources": ""})
        if self._reconfiguring:
            entry = self._get_reconfigure_entry()
            if entry.data[CONF_CONFIGURATION] == self._draft:
                return self.async_abort(reason="no_changes")
            return self.async_update_reload_and_abort(entry, data_updates={CONF_CONFIGURATION: self._draft})
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title="Presence Engine", data={CONF_CONFIGURATION: self._draft})

    async def async_step_advanced(self, user_input=None):
        errors: dict[str, str] = {}
        detail = ""
        if user_input is not None:
            try:
                raw = json.loads(user_input[CONF_CONFIGURATION])
                if not isinstance(raw, dict):
                    raise ConfigurationError("configuration root must be an object")
                old_frigate = self._draft.get("frigate", {})
                new_frigate = raw.get("frigate", {})
                if not isinstance(new_frigate, dict):
                    raise ConfigurationError("frigate must be an object")
                if "password" not in new_frigate and all(new_frigate.get(key) == old_frigate.get(key) for key in ("url", "username")) and old_frigate.get("password"):
                    raw["frigate"]["password"] = old_frigate["password"]
                validate_draft(raw)
            except (json.JSONDecodeError, ConfigurationError, KeyError, TypeError, ValueError) as err:
                errors[CONF_CONFIGURATION] = "invalid_configuration"
                detail = str(err)
            else:
                self._draft = {**deepcopy(EMPTY_CONFIGURATION), **raw}
                return await self.async_step_menu()

        suggested = deepcopy(self._draft)
        suggested.get("frigate", {}).pop("password", None)
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_CONFIGURATION,
                    default=json.dumps(suggested, indent=2, sort_keys=True),
                ): str
            }
        )
        return self.async_show_form(step_id="advanced", data_schema=schema, errors=errors, description_placeholders={"detail": detail})

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return PresenceEngineOptionsFlow()


class PresenceEngineOptionsFlow(OptionsFlowWithReload):
    """Runtime-only options; source semantics remain in entry data."""

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_COMPARISON_MODE,
                    default=options.get(CONF_COMPARISON_MODE, DEFAULT_COMPARISON_MODE),
                ): bool,
                vol.Required(
                    CONF_MAX_RECORDS,
                    default=options.get(CONF_MAX_RECORDS, DEFAULT_MAX_RECORDS),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=100,
                        max=10_000,
                        step=100,
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_SAVE_DELAY,
                    default=options.get(CONF_SAVE_DELAY, DEFAULT_SAVE_DELAY),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=5,
                        max=300,
                        step=5,
                        mode=NumberSelectorMode.BOX,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
