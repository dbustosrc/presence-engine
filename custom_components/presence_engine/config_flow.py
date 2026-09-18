"""UI configuration for Presence Engine."""

from __future__ import annotations

from copy import deepcopy
import json
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlowWithReload
from homeassistant.core import callback
from homeassistant.helpers.selector import NumberSelector, NumberSelectorConfig, NumberSelectorMode

from .configuration import ConfigurationError, parse_configuration
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


EMPTY_CONFIGURATION = {
    "schema_version": 1,
    "areas": {},
    "adjacency": {},
    "identities": {},
    "cameras": {},
    "sources": [],
}


class PresenceEngineConfigFlow(ConfigFlow, domain=DOMAIN):
    """Create and reconfigure the single engine instance."""

    VERSION = 1

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        return await self._configuration_step("user", user_input)

    async def async_step_reconfigure(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        return await self._configuration_step("reconfigure", user_input)

    async def _configuration_step(
        self,
        step_id: str,
        user_input: dict[str, Any] | None,
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                raw = json.loads(user_input[CONF_CONFIGURATION])
                if not isinstance(raw, dict):
                    raise ConfigurationError("configuration root must be an object")
                parse_configuration(raw)
            except (json.JSONDecodeError, ConfigurationError, TypeError, ValueError):
                errors[CONF_CONFIGURATION] = "invalid_configuration"
            else:
                if step_id == "reconfigure":
                    return self.async_update_reload_and_abort(
                        self._get_reconfigure_entry(),
                        data_updates={CONF_CONFIGURATION: raw},
                    )
                await self.async_set_unique_id(DOMAIN)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="Presence Engine",
                    data={CONF_CONFIGURATION: raw},
                )

        suggested = deepcopy(EMPTY_CONFIGURATION)
        if step_id == "reconfigure":
            suggested = self._get_reconfigure_entry().data[CONF_CONFIGURATION]
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_CONFIGURATION,
                    default=json.dumps(suggested, indent=2, sort_keys=True),
                ): str
            }
        )
        return self.async_show_form(step_id=step_id, data_schema=schema, errors=errors)

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
