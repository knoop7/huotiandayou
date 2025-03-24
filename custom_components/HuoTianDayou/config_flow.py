from __future__ import annotations
import logging
from typing import Any
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import callback, HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig, SelectSelectorMode, TemplateSelector, BooleanSelector

from .const import (
    DOMAIN, CONF_CONVERSATION_MODE, CONF_PRIMARY_AGENT, CONF_FALLBACK_AGENT,
    CONF_SECONDARY_FALLBACK_AGENT, CONF_ERROR_RESPONSES, CONF_ENABLE_SPEAKER,
    CONF_SPEAKER_ENTITY, CONF_SPEAKER_TYPE, CONF_TTS_SERVICE,
    CONVERSATION_MODE_NO_NAME, CONVERSATION_MODE_ADD_NAME, CONVERSATION_MODE_DETAILED,
    SPEAKER_TYPE_DISABLED, SPEAKER_TYPE_XIAOMI, SPEAKER_TYPE_OTHER,CONF_ENABLE_AI_SUMMARY,
    DEFAULT_NAME, DEFAULT_CONVERSATION_MODE, DEFAULT_PRIMARY_AGENT,
    DEFAULT_FALLBACK_AGENT, DEFAULT_ERROR_RESPONSES,
)

LOGGER = logging.getLogger(__name__)

@callback
def get_conversation_agents(hass: HomeAssistant) -> list[dict[str, str]]:
    try:
        agents = []
        for entity_id in hass.states.async_entity_ids("conversation"):
            state = hass.states.get(entity_id)
            if not state or state.attributes.get("entity") != "HuoTianDaYou.ai":
                friendly_name = state.attributes.get("friendly_name") if state else entity_id.split('.')[-1]
                agents.append({"value": entity_id, "label": friendly_name})
        
        if not agents:
            LOGGER.info("未找到有效的对话代理")
            return [{"value": "no_agents", "label": "无可用对话代理"}]
        return agents
    except Exception as e:
        LOGGER.info(f"获取对话代理失败: {e}")
        return [{"value": "no_agents", "label": "无可用对话代理"}]

class KaderManagerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema({vol.Required(CONF_NAME, default=DEFAULT_NAME): str}),
            )
        return self.async_create_entry(title=user_input[CONF_NAME], data=user_input)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        return OptionsFlowHandler(config_entry)

class OptionsFlowHandler(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        super().__init__()  
        self._config_entry = config_entry 
        self._user_input: dict[str, Any] = dict(config_entry.options)
        
    def _process_user_input(self, user_input: dict[str, Any], exclude_keys: list[str] = ["back"]) -> None:

        if user_input:
            current_options = dict(self._config_entry.options)
            
            for key, value in user_input.items():
                if key not in exclude_keys:
                    if key == CONF_SECONDARY_FALLBACK_AGENT and value in (None, ""):
                        if key in self._user_input:
                            self._user_input.pop(key)
                    elif value not in (None, ""):
                        self._user_input[key] = value
                    elif key in current_options and key not in self._user_input:
                        self._user_input[key] = current_options[key]
            
            for key, value in current_options.items():
                if key not in self._user_input and key not in user_input and value not in (None, "") and key != CONF_SECONDARY_FALLBACK_AGENT:
                    self._user_input[key] = value

    def _get_xiaomi_speakers(self) -> list[dict[str, str]]:
        speakers = []
        for entity_id in self.hass.states.async_entity_ids("media_player"):
            if entity_id.startswith("media_player.xiaomi_"):
                state = self.hass.states.get(entity_id)
                if state:
                    friendly_name = state.attributes.get("friendly_name", entity_id)
                    speakers.append({"value": entity_id, "label": friendly_name})
        return speakers
        
    def _get_all_media_players(self) -> list[dict[str, str]]:
        players = []
        for entity_id in self.hass.states.async_entity_ids("media_player"):
            if "xiaomi" not in entity_id.lower():
                state = self.hass.states.get(entity_id)
                if state:
                    friendly_name = state.attributes.get("friendly_name", entity_id)
                    players.append({"value": entity_id, "label": friendly_name})
        return players
        
    def _get_tts_services(self) -> list[dict[str, str]]:
        tts_services = []
        services = self.hass.services.async_services()
        tts_engines = {
            "edge_tts": "Microsoft Edge TTS", "xiaomo": "Edge TTS", "google_translate": "Google Translate TTS",
            "cloud": "Home Assistant Cloud TTS", "demo": "Home Assistant Cloud TTS", "elevenlabs": "ElevenLabs TTS", 
            "aliyun_bailian": "Aliyun bailian TTS"
        }
        for domain, domain_services in services.items():
            if domain == "tts":
                for service_name in domain_services:
                    if service_name.endswith("_say"):
                        service_id = f"{domain}.{service_name}"
                        display_name = service_id
                        for prefix, name in tts_engines.items():
                            if prefix in service_name:
                                display_name = name
                                break
                        tts_services.append({"value": service_id, "label": display_name})
        return tts_services

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            self._user_input = user_input.copy()
            next_step = user_input.get("next_step")
            return (await self.async_step_agent_settings() if next_step == "agent_settings" else
                   await self.async_step_conversation_settings() if next_step == "conversation_settings" else
                   await self.async_step_speaker_settings() if next_step == "speaker_settings" else
                   self.async_create_entry(title="", data=self._user_input))

        schema = vol.Schema({
            vol.Required("next_step", default="agent_settings"): SelectSelector(
                SelectSelectorConfig(
                    options=[
                        {"value": "agent_settings", "label": "对话代理设置"},
                        {"value": "conversation_settings", "label": "对话模式设置"},
                        {"value": "speaker_settings", "label": "语音输出设置"}
                    ],
                    mode=SelectSelectorMode.DROPDOWN
                )
            ),
        })

        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            last_step=False,
            description_placeholders={"integration_title": "integration_title", "current_config": "current_config"}
        )

    async def async_step_agent_settings(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        available_agents = get_conversation_agents(self.hass)
        available_agent_ids = [agent["value"] for agent in available_agents]
        errors = {}

        if not available_agents or (len(available_agents) == 1 and available_agents[0]["value"] == "no_agents"):
            errors["base"] = "no_agents_available"

        if user_input is not None:
            if user_input.get("back"):
                return await self.async_step_init()
            
            if not available_agent_ids or "no_agents" in available_agent_ids:
                errors["base"] = "no_agents_available"
            else:
                if CONF_PRIMARY_AGENT in user_input and user_input[CONF_PRIMARY_AGENT] not in available_agent_ids:
                    errors[CONF_PRIMARY_AGENT] = "invalid_agent"
                if CONF_FALLBACK_AGENT in user_input and user_input[CONF_FALLBACK_AGENT] not in available_agent_ids:
                    errors[CONF_FALLBACK_AGENT] = "invalid_agent"
                if (CONF_SECONDARY_FALLBACK_AGENT in user_input and 
                    user_input[CONF_SECONDARY_FALLBACK_AGENT] and 
                    user_input[CONF_SECONDARY_FALLBACK_AGENT] not in available_agent_ids):
                    errors[CONF_SECONDARY_FALLBACK_AGENT] = "invalid_agent"
                
            if not errors:
                if CONF_SECONDARY_FALLBACK_AGENT in user_input and not user_input[CONF_SECONDARY_FALLBACK_AGENT]:
                    if CONF_SECONDARY_FALLBACK_AGENT in self._user_input:
                        self._user_input.pop(CONF_SECONDARY_FALLBACK_AGENT)
                    user_input_copy = user_input.copy()
                    user_input_copy.pop(CONF_SECONDARY_FALLBACK_AGENT, None)
                    self._process_user_input(user_input_copy, exclude_keys=["back", "next_step", "save_and_exit"])
                else:
                    self._process_user_input(user_input, exclude_keys=["back", "next_step", "save_and_exit"])
                
                if user_input.get("save_and_exit") or not user_input.get("next_step"):
                    return self.async_create_entry(title="", data=self._user_input)
                else:
                    return await self.async_step_conversation_settings()

        current_primary = self._config_entry.options.get(CONF_PRIMARY_AGENT, DEFAULT_PRIMARY_AGENT)
        if current_primary not in available_agent_ids and available_agent_ids and available_agent_ids[0] != "no_agents":
            current_primary = available_agent_ids[0]
            
        current_fallback = self._config_entry.options.get(CONF_FALLBACK_AGENT, DEFAULT_FALLBACK_AGENT)
        if current_fallback not in available_agent_ids and available_agent_ids and available_agent_ids[0] != "no_agents":
            current_fallback = available_agent_ids[0]
            
        current_secondary = self._config_entry.options.get(CONF_SECONDARY_FALLBACK_AGENT, None)

        schema = vol.Schema({
            vol.Required(CONF_PRIMARY_AGENT, description={"suggested_value": current_primary}): SelectSelector(
                SelectSelectorConfig(options=available_agents, mode=SelectSelectorMode.DROPDOWN)
            ),
            vol.Required(CONF_FALLBACK_AGENT, description={"suggested_value": current_fallback}): SelectSelector(
                SelectSelectorConfig(options=available_agents, mode=SelectSelectorMode.DROPDOWN)
            ),
            vol.Optional(CONF_SECONDARY_FALLBACK_AGENT, description={"suggested_value": current_secondary}): SelectSelector(
                SelectSelectorConfig(options=available_agents, mode=SelectSelectorMode.DROPDOWN)
            ),
            vol.Optional("back", default=False): bool,
        })

        return self.async_show_form(
            step_id="agent_settings",
            data_schema=schema,
            errors=errors,
            description_placeholders={}
        )

    async def async_step_conversation_settings(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors = {}

        if user_input is not None:
            if user_input.get("back"):
                return await self.async_step_init()
                
            if not user_input.get(CONF_CONVERSATION_MODE):
                errors[CONF_CONVERSATION_MODE] = "invalid_conversation_mode"
            if not user_input.get(CONF_ERROR_RESPONSES):
                errors[CONF_ERROR_RESPONSES] = "invalid_error_responses"
                
            if not errors:
                self._process_user_input(user_input, exclude_keys=["back", "next_step", "save_and_exit"])
                
                if user_input.get("save_and_exit") or not user_input.get("next_step"):
                    return self.async_create_entry(title="", data=self._user_input)
                else:
                    return await self.async_step_speaker_settings()

        current_mode = self._config_entry.options.get(CONF_CONVERSATION_MODE, DEFAULT_CONVERSATION_MODE)
        if not current_mode:
            current_mode = DEFAULT_CONVERSATION_MODE
        current_error_responses = self._config_entry.options.get(CONF_ERROR_RESPONSES, DEFAULT_ERROR_RESPONSES)

        schema = vol.Schema({
            vol.Required(CONF_CONVERSATION_MODE, description={"suggested_value": current_mode}): SelectSelector(
                SelectSelectorConfig(
                    options=[
                        {"value": CONVERSATION_MODE_NO_NAME, "label": "不显示名称（精简模式）"},
                        {"value": CONVERSATION_MODE_ADD_NAME, "label": "显示 AI 名称（前后备推荐）"},
                        {"value": CONVERSATION_MODE_DETAILED, "label": "详细显示内容（深度思考首选）"}
                    ],
                    mode=SelectSelectorMode.DROPDOWN
                )
            ),
            vol.Required(CONF_ERROR_RESPONSES, description={"suggested_value": current_error_responses}): TemplateSelector(),
            vol.Optional(CONF_ENABLE_AI_SUMMARY, default=self._config_entry.options.get(CONF_ENABLE_AI_SUMMARY, False)): BooleanSelector(),
            vol.Optional("back", default=False): bool,
        })

        return self.async_show_form(
            step_id="conversation_settings",
            data_schema=schema,
            errors=errors,
            description_placeholders={}
        )

    async def async_step_speaker_settings(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors = {}

        if user_input is not None:
            if user_input.get("back"):
                return await self.async_step_init()
                
            self._process_user_input(user_input, exclude_keys=["back", "next_step", "save_and_exit"])
            
            speaker_type = user_input.get(CONF_SPEAKER_TYPE)
            if speaker_type == SPEAKER_TYPE_XIAOMI:
                return await self.async_step_xiaomi_speaker()
            elif speaker_type == SPEAKER_TYPE_OTHER:
                return await self.async_step_other_speaker()
            else:
                return self.async_create_entry(title="", data=self._user_input)

        current_speaker_type = self._config_entry.options.get(CONF_SPEAKER_TYPE, SPEAKER_TYPE_DISABLED)

        schema = vol.Schema({
            vol.Required(CONF_SPEAKER_TYPE, description={"suggested_value": current_speaker_type}): SelectSelector(
                SelectSelectorConfig(
                    options=[
                        {"value": SPEAKER_TYPE_DISABLED, "label": "关闭语音输出"},
                        {"value": SPEAKER_TYPE_XIAOMI, "label": "小米音箱"},
                        {"value": SPEAKER_TYPE_OTHER, "label": "其他音箱"}
                    ],
                    mode=SelectSelectorMode.DROPDOWN
                )
            ),
            vol.Optional("back", default=False): bool,
        })

        return self.async_show_form(
            step_id="speaker_settings",
            data_schema=schema,
            errors=errors,
            description_placeholders={}
        )
        
    async def async_step_xiaomi_speaker(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        available_speakers = self._get_xiaomi_speakers()
        errors = {}
        
        if user_input is not None:
            if user_input.get("back"):
                return await self.async_step_speaker_settings()
                
            speaker_entity = user_input.get(CONF_SPEAKER_ENTITY)
            available_speaker_ids = [speaker["value"] for speaker in available_speakers]
            
            if not available_speakers:
                errors["base"] = "no_speakers_available"
            elif not speaker_entity or speaker_entity not in available_speaker_ids:
                errors[CONF_SPEAKER_ENTITY] = "invalid_speaker"
            
            if not errors:
                self._process_user_input(user_input)
                
                return self.async_create_entry(title="", data=self._user_input)

        available_speaker_ids = [speaker["value"] for speaker in available_speakers]
        current_speaker = self._config_entry.options.get(CONF_SPEAKER_ENTITY)

        if not available_speakers:
            errors["base"] = "no_speakers_available"
            schema = vol.Schema({
                vol.Optional("back", default=False): bool,
                vol.Optional("save_and_exit", default=True): bool,
            })
        else:
            schema = vol.Schema({
                vol.Required(CONF_SPEAKER_ENTITY, description={"suggested_value": current_speaker}): SelectSelector(
                    SelectSelectorConfig(
                        options=available_speakers, 
                        mode=SelectSelectorMode.DROPDOWN
                    )
                ),
                vol.Optional("back", default=False): bool,
            })

        return self.async_show_form(
            step_id="xiaomi_speaker",
            data_schema=schema,
            errors=errors,
            description_placeholders={}
        )
    async def async_step_other_speaker(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        available_speakers = self._get_all_media_players()
        available_tts = self._get_tts_services()
        errors = {}
        
        if user_input is not None:
            if user_input.get("back"):
                return await self.async_step_speaker_settings()
                
            speaker_entity = user_input.get(CONF_SPEAKER_ENTITY)
            tts_service = user_input.get(CONF_TTS_SERVICE)
            
            available_speaker_ids = [speaker["value"] for speaker in available_speakers]
            available_tts_ids = [tts["value"] for tts in available_tts]
            
            if not available_speakers:
                errors["base"] = "no_speakers_available"
            elif not speaker_entity or speaker_entity not in available_speaker_ids:
                errors[CONF_SPEAKER_ENTITY] = "invalid_speaker"
                
            if not available_tts:
                errors["base"] = "no_tts_available"
            elif not tts_service or tts_service not in available_tts_ids:
                errors[CONF_TTS_SERVICE] = "invalid_tts_service"
            
            if not errors:
                self._process_user_input(user_input)
                
                return self.async_create_entry(title="", data=self._user_input)

        available_speaker_ids = [speaker["value"] for speaker in available_speakers]
        current_speaker = self._config_entry.options.get(CONF_SPEAKER_ENTITY)
        available_tts_ids = [tts["value"] for tts in available_tts]
        current_tts = self._config_entry.options.get(CONF_TTS_SERVICE)

        schema = vol.Schema({
            vol.Optional("info", default="no_speakers_or_tts"): str,
            vol.Optional("back", default=False): bool,
        }) if not available_speakers or not available_tts else vol.Schema({
            vol.Required(CONF_SPEAKER_ENTITY, description={"suggested_value": current_speaker}): SelectSelector(
                SelectSelectorConfig(options=available_speakers, mode=SelectSelectorMode.DROPDOWN)
            ),
            vol.Required(CONF_TTS_SERVICE, description={"suggested_value": current_tts}): SelectSelector(
                SelectSelectorConfig(options=available_tts, mode=SelectSelectorMode.DROPDOWN)
            ),
            vol.Optional("back", default=False): bool,
        })

        return self.async_show_form(
            step_id="other_speaker",
            data_schema=schema,
            errors=errors,
            description_placeholders={}
        )