from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import (
    ConversationAgentSelector,
    ConversationAgentSelectorConfig,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    DOMAIN,
    CONF_CONVERSATION_MODE,
    CONF_PRIMARY_AGENT,
    CONF_FALLBACK_AGENT,
    CONF_SECONDARY_FALLBACK_AGENT,
    CONVERSATION_MODE_NO_NAME,
    CONVERSATION_MODE_ADD_NAME,
    CONVERSATION_MODE_DETAILED,
    DEFAULT_NAME,
    DEFAULT_CONVERSATION_MODE,
    DEFAULT_PRIMARY_AGENT,
    DEFAULT_FALLBACK_AGENT,
    DEFAULT_SECONDARY_FALLBACK_AGENT,
)

class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:

        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {
                        vol.Required(CONF_NAME, default=DEFAULT_NAME): str,
                        vol.Required(CONF_CONVERSATION_MODE, default=DEFAULT_CONVERSATION_MODE): SelectSelector(
                            SelectSelectorConfig(
                                options=[
                                    {"value": CONVERSATION_MODE_NO_NAME, "label": "不显示名称"},
                                    {"value": CONVERSATION_MODE_ADD_NAME, "label": "显示AI名称（推荐）"},
                                    {"value": CONVERSATION_MODE_DETAILED, "label": "详细显示内容（不推荐）"},
                                ],
                                mode=SelectSelectorMode.DROPDOWN,
                                translation_key="conversation_mode",
                            ),
                        ),
                    }
                ),
            )

        return self.async_create_entry(title=user_input[CONF_NAME], data=user_input)

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:

        return OptionsFlowHandler(config_entry)

class OptionsFlowHandler(config_entries.OptionsFlow):

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:

        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:

        if user_input is not None:
            # Remove secondary fallback if not set
            if not user_input.get(CONF_SECONDARY_FALLBACK_AGENT):
                user_input.pop(CONF_SECONDARY_FALLBACK_AGENT, None)
            return self.async_create_entry(title="", data=user_input)

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_PRIMARY_AGENT,
                    default=self.config_entry.options.get(
                        CONF_PRIMARY_AGENT, DEFAULT_PRIMARY_AGENT
                    ),
                ): ConversationAgentSelector(ConversationAgentSelectorConfig()),
                vol.Required(
                    CONF_FALLBACK_AGENT,
                    default=self.config_entry.options.get(
                        CONF_FALLBACK_AGENT, DEFAULT_FALLBACK_AGENT
                    ),
                ): ConversationAgentSelector(ConversationAgentSelectorConfig()),
                vol.Optional(
                    CONF_SECONDARY_FALLBACK_AGENT,
                    description={"suggested_value": self.config_entry.options.get(CONF_SECONDARY_FALLBACK_AGENT)},
                ): ConversationAgentSelector(ConversationAgentSelectorConfig()),
                vol.Required(
                    CONF_CONVERSATION_MODE,
                    default=self.config_entry.options.get(
                        CONF_CONVERSATION_MODE, DEFAULT_CONVERSATION_MODE
                    ),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            {"value": CONVERSATION_MODE_NO_NAME, "label": "不显示名称"},
                            {"value": CONVERSATION_MODE_ADD_NAME, "label": "显示AI名称（推荐）"},
                            {"value": CONVERSATION_MODE_DETAILED, "label": "详细显示内容（不推荐）"},
                        ],
                        mode=SelectSelectorMode.DROPDOWN,
                        translation_key="conversation_mode",
                    ),
                ),
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)