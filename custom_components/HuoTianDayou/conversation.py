from __future__ import annotations

import logging

from homeassistant.components import assist_pipeline, conversation
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.util import ulid
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from home_assistant_intents import get_languages

from homeassistant.helpers import (
    config_validation as cv,
    intent,
)

from .const import (
    CONF_PRIMARY_AGENT,
    CONF_FALLBACK_AGENT,
    CONF_SECONDARY_FALLBACK_AGENT,
    CONF_CONVERSATION_MODE,
    CONVERSATION_MODE_NO_NAME,
    CONVERSATION_MODE_ADD_NAME,
    CONVERSATION_MODE_DETAILED,
    DOMAIN,
    STRANGE_ERROR_RESPONSES,
)

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

DATA_DEFAULT_ENTITY = "conversation_default_entity"

@callback
def get_default_agent(hass: HomeAssistant) -> conversation.default_agent.DefaultAgent:
    return hass.data[DATA_DEFAULT_ENTITY]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> bool:
    agent = FallbackConversationAgent(hass, entry)
    async_add_entities([agent])
    return True

class FallbackConversationAgent(conversation.ConversationEntity, conversation.AbstractConversationAgent):
    last_used_agent: str | None
    entry: ConfigEntry
    hass: HomeAssistant
    _attr_has_entity_name = True
    _attr_chat_response: str | None = None

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.last_used_agent = None
        self._attr_name = entry.title
        self._attr_unique_id = entry.entry_id
        self._attr_supported_features = (
            conversation.ConversationEntityFeature.CONTROL
        )
        self.in_context_examples = None

    @property
    def supported_languages(self) -> list[str]:
        return get_languages()

    @property
    def state_attributes(self):
        """Return the state attributes."""
        attributes = super().state_attributes or {}
        if self._attr_chat_response is not None:
            attributes["响应内容"] = self._attr_chat_response
        return attributes

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        assist_pipeline.async_migrate_engine(
            self.hass, "conversation", self.entry.entry_id, self.entity_id
        )
        conversation.async_set_agent(self.hass, self.entry, self)
        self.entry.async_on_unload(
            self.entry.add_update_listener(self._async_entry_update_listener)
        )

    async def async_will_remove_from_hass(self) -> None:
        conversation.async_unset_agent(self.hass, self.entry)
        await super().async_will_remove_from_hass()

    async def _async_entry_update_listener(
        self, hass: HomeAssistant, entry: ConfigEntry
    ) -> None:
        self._attr_supported_features = (
            conversation.ConversationEntityFeature.CONTROL
        )

    async def async_process(
        self, user_input: conversation.ConversationInput
    ) -> conversation.ConversationResult:
        agent_manager = conversation.get_agent_manager(self.hass)
        default_agent = get_default_agent(self.hass)
        agent_names = self._convert_agent_info_to_dict(
            agent_manager.async_get_agent_info()
        )
        agent_names[conversation.const.HOME_ASSISTANT_AGENT] = default_agent.name
        agents = [
            self.entry.options.get(CONF_PRIMARY_AGENT, default_agent),
            self.entry.options.get(CONF_FALLBACK_AGENT, default_agent),
            self.entry.options.get(CONF_SECONDARY_FALLBACK_AGENT, default_agent),
        ]

        conversation_mode = self.entry.options.get(CONF_CONVERSATION_MODE, CONVERSATION_MODE_ADD_NAME)

        if user_input.conversation_id is None:
            user_input.conversation_id = ulid.ulid()

        all_results = []
        result = None
        for agent_id in agents:
            agent_name = agent_names.get(agent_id, "UNKNOWN")
            if agent_id == conversation.const.HOME_ASSISTANT_AGENT:
                agent_name = default_agent.name

            result = await self._async_process_agent(
                agent_manager,
                agent_id,
                agent_name,
                user_input,
                conversation_mode,
                result,
            )
            response_text = result.response.speech['plain']['original_speech'].strip()
            
            if (response_text and 
                not response_text.lower().startswith('python') and
                result.response.response_type != intent.IntentResponseType.ERROR and
                response_text not in STRANGE_ERROR_RESPONSES):
                self._attr_chat_response = result.response.speech['plain']['speech']
                self.async_write_ha_state()
                return result
            all_results.append(result)

        intent_response = intent.IntentResponse(language=user_input.language)
        err = "完全失败。没有对话代理能够回应。"
        if conversation_mode == CONVERSATION_MODE_DETAILED:
            for res in all_results:
                r = res.response.speech['plain']
                err += f"\n{r.get('agent_name', 'UNKNOWN')} 回复: {r.get('original_speech', r['speech'])}"
        intent_response.async_set_error(
            intent.IntentResponseErrorCode.NO_INTENT_MATCH,
            err,
        )
        result = conversation.ConversationResult(
            conversation_id=result.conversation_id,
            response=intent_response
        )

        self._attr_chat_response = err
        self.async_write_ha_state()
        return result

    async def _async_process_agent(
        self,
        agent_manager: conversation.AgentManager,
        agent_id: str,
        agent_name: str,
        user_input: conversation.ConversationInput,
        conversation_mode: str,
        previous_result,
    ) -> conversation.ConversationResult:
        agent = conversation.agent_manager.async_get_agent(self.hass, agent_id)

        _LOGGER.debug("Processing in %s using %s: %s", user_input.language, agent_id, user_input.text)

        result = await agent.async_process(user_input)
        r = result.response.speech['plain']['speech']
        result.response.speech['plain']['original_speech'] = r
        result.response.speech['plain']['agent_name'] = agent_name
        result.response.speech['plain']['agent_id'] = agent_id

        if conversation_mode == CONVERSATION_MODE_NO_NAME:
            result.response.speech['plain']['speech'] = r
        elif conversation_mode == CONVERSATION_MODE_ADD_NAME:
            result.response.speech['plain']['speech'] = f"{agent_name} 回复: {r}"
        elif conversation_mode == CONVERSATION_MODE_DETAILED:
            if previous_result is not None:
                pr = previous_result.response.speech['plain'].get('original_speech', previous_result.response.speech['plain']['speech'])
                result.response.speech['plain']['speech'] = f"{previous_result.response.speech['plain'].get('agent_name', 'UNKNOWN')} 失败，回复: {pr} 然后 {agent_name} 回复: {r}"
            else:
                result.response.speech['plain']['speech'] = f"{agent_name} 回复: {r}"

        return result

    def _convert_agent_info_to_dict(self, agents_info: list[conversation.AgentInfo]) -> dict[str, str]:
        r = {}
        for agent_info in agents_info:
            agent = conversation.agent_manager.async_get_agent(self.hass, agent_info.id)
            agent_id = agent_info.id
            if hasattr(agent, "registry_entry"):
                agent_id = agent.registry_entry.entity_id
            r[agent_id] = agent_info.name
            _LOGGER.debug("agent_id %s has name %s", agent_id, agent_info.name)
        return r