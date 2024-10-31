from __future__ import annotations
import logging
from typing import Any
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import callback, HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import (
   SelectSelector,
   SelectSelectorConfig,
   SelectSelectorMode,
   BooleanSelector,
   ConversationAgentSelector,
   ConversationAgentSelectorConfig,
   TemplateSelector,
)
from homeassistant.components import conversation

from .const import (
   DOMAIN,
   CONF_CONVERSATION_MODE,
   CONF_PRIMARY_AGENT,
   CONF_FALLBACK_AGENT,
   CONF_SECONDARY_FALLBACK_AGENT,
   CONF_ERROR_RESPONSES,
   CONF_ENABLE_SPEAKER,
   CONF_SPEAKER_ENTITY,
   CONVERSATION_MODE_NO_NAME,
   CONVERSATION_MODE_ADD_NAME,
   CONVERSATION_MODE_DETAILED,
   DEFAULT_NAME,
   DEFAULT_CONVERSATION_MODE,
   DEFAULT_PRIMARY_AGENT,
   DEFAULT_FALLBACK_AGENT,
   DEFAULT_ERROR_RESPONSES,
)

LOGGER = logging.getLogger(__name__)

@callback
def get_conversation_agents(hass: HomeAssistant) -> list[dict[str, str]]:
   agents = []
   for entity_id in hass.states.async_entity_ids("conversation"):
       state = hass.states.get(entity_id)
       if not state or state.attributes.get("entity") != "HuoTianDaYou.ai":
           friendly_name = state.attributes.get("friendly_name") if state else entity_id.split('.')[1]
           agents.append({"value": entity_id, "label": friendly_name})
   return agents

class KaderManagerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
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
       self._user_input = {}

   def _get_xiaomi_speakers(self) -> list[dict[str, str]]:
       speakers = []
       for entity_id in self.hass.states.async_entity_ids("media_player"):
           if entity_id.startswith("media_player.xiaomi_"):
               state = self.hass.states.get(entity_id)
               if state:
                   friendly_name = state.attributes.get("friendly_name", entity_id)
                   speakers.append({
                       "value": entity_id,
                       "label": friendly_name
                   })
       return speakers

   async def async_step_init(
       self, user_input: dict[str, Any] | None = None
   ) -> FlowResult:
       available_agents = get_conversation_agents(self.hass)
       available_agent_ids = [agent["value"] for agent in available_agents]
       errors = {}

       if user_input is not None:
           if not user_input.get(CONF_CONVERSATION_MODE):
               errors[CONF_CONVERSATION_MODE] = "invalid_conversation_mode"
           if not user_input.get(CONF_ERROR_RESPONSES):
               errors[CONF_ERROR_RESPONSES] = "invalid_error_responses"
           
           self._user_input = user_input.copy()
           if not errors:
               if user_input.get(CONF_ENABLE_SPEAKER, False):
                   return await self.async_step_speaker()
               return self.async_create_entry(title="", data=self._user_input)

       current_secondary = self.config_entry.options.get(CONF_SECONDARY_FALLBACK_AGENT)
       suggested_secondary = current_secondary if current_secondary in available_agent_ids else None

       schema = vol.Schema({
           vol.Required(
               CONF_PRIMARY_AGENT,
               default=self.config_entry.options.get(
                   CONF_PRIMARY_AGENT, DEFAULT_PRIMARY_AGENT
               ) if self.config_entry.options.get(
                   CONF_PRIMARY_AGENT, DEFAULT_PRIMARY_AGENT
               ) in available_agent_ids else DEFAULT_PRIMARY_AGENT
           ): SelectSelector(
               SelectSelectorConfig(
                   options=available_agents,
                   mode=SelectSelectorMode.DROPDOWN,
                   translation_key="primary_agent"
               )
           ),
           vol.Required(
               CONF_FALLBACK_AGENT,
               default=self.config_entry.options.get(
                   CONF_FALLBACK_AGENT, DEFAULT_FALLBACK_AGENT
               ) if self.config_entry.options.get(
                   CONF_FALLBACK_AGENT, DEFAULT_FALLBACK_AGENT
               ) in available_agent_ids else DEFAULT_FALLBACK_AGENT
           ): SelectSelector(
               SelectSelectorConfig(
                   options=available_agents,
                   mode=SelectSelectorMode.DROPDOWN,
                   translation_key="fallback_agent"
               )
           ),
           vol.Optional(
               CONF_SECONDARY_FALLBACK_AGENT,
               description={
                   "suggested_value": suggested_secondary
               }
           ): SelectSelector(
               SelectSelectorConfig(
                   options=available_agents,
                   mode=SelectSelectorMode.DROPDOWN,
                   translation_key="secondary_fallback_agent"
               )
           ),
           vol.Required(
               CONF_CONVERSATION_MODE,
               default=self.config_entry.options.get(
                   CONF_CONVERSATION_MODE, DEFAULT_CONVERSATION_MODE
               )
           ): SelectSelector(
               SelectSelectorConfig(
                   options=[
                       {
                           "value": CONVERSATION_MODE_NO_NAME,
                           "label": "不显示名称"
                       },
                       {
                           "value": CONVERSATION_MODE_ADD_NAME,
                           "label": "显示AI名称（推荐）"
                       },
                       {
                           "value": CONVERSATION_MODE_DETAILED,
                           "label": "详细显示内容（不推荐）"
                       },
                   ],
                   mode=SelectSelectorMode.DROPDOWN,
                   translation_key="conversation_mode"
               )
           ),
           vol.Required(
               CONF_ERROR_RESPONSES,
               default=self.config_entry.options.get(
                   CONF_ERROR_RESPONSES, DEFAULT_ERROR_RESPONSES
               )
           ): TemplateSelector(),
           vol.Required(
               CONF_ENABLE_SPEAKER,
               default=self.config_entry.options.get(CONF_ENABLE_SPEAKER, False),
               description={"translation_key": "options.step.init.data.enable_speaker"}
           ): BooleanSelector(),
       })

       return self.async_show_form(
           step_id="init",
           data_schema=schema,
           errors=errors,
           description_placeholders={"translation_key": "options.step.init.description"}
       )

   async def async_step_speaker(
       self, user_input: dict[str, Any] | None = None
   ) -> FlowResult:
       available_speakers = self._get_xiaomi_speakers()
       errors = {}

       if user_input is not None:
           speaker_entity = user_input.get(CONF_SPEAKER_ENTITY)
           available_speaker_ids = [speaker["value"] for speaker in available_speakers]
           
           if available_speakers and (not speaker_entity or speaker_entity not in available_speaker_ids):
               errors[CONF_SPEAKER_ENTITY] = "invalid_speaker"
           
           if not errors:
               self._user_input.update(user_input)
               return self.async_create_entry(title="", data=self._user_input)

       if available_speakers:
           schema = vol.Schema({
               vol.Required(
                   CONF_SPEAKER_ENTITY,
                   description={
                       "suggested_value": self.config_entry.options.get(CONF_SPEAKER_ENTITY),
                       "translation_key": "options.step.speaker.data.speaker_entity"
                   }
               ): SelectSelector(
                   SelectSelectorConfig(
                       options=available_speakers,
                       mode=SelectSelectorMode.DROPDOWN,
                       translation_key="speaker_type"
                   )
               ),
           })
       else:
           schema = vol.Schema({
               vol.Optional(
                   CONF_SPEAKER_ENTITY,
                   description={
                       "suggested_value": self.config_entry.options.get(CONF_SPEAKER_ENTITY),
                       "translation_key": "options.step.speaker.data.no_speakers"
                   }
               ): SelectSelector(
                   SelectSelectorConfig(
                       options=[{"value": "", "label": "未检测到可用的小爱音箱"}],
                       mode=SelectSelectorMode.DROPDOWN,
                       translation_key="speaker_type"
                   )
               ),
           })

       return self.async_show_form(
           step_id="speaker",
           data_schema=schema,
           errors=errors,
           description_placeholders={
               "translation_key": "options.step.speaker.description"
           }
       )