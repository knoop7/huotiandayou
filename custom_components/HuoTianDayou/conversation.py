from __future__ import annotations

import logging
import asyncio  

from homeassistant.components import assist_pipeline, conversation
from homeassistant.components.conversation import trace
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
    CONF_SPEAKER_ENTITY,
    CONF_SPEAKER_TYPE,
    CONF_TTS_SERVICE,
    CONF_ENABLE_AI_SUMMARY,
    CONVERSATION_MODE_NO_NAME,
    CONVERSATION_MODE_ADD_NAME,
    CONVERSATION_MODE_DETAILED,
    SPEAKER_TYPE_DISABLED,
    SPEAKER_TYPE_XIAOMI,
    SPEAKER_TYPE_OTHER,
    DOMAIN,
    DEFAULT_ERROR_RESPONSES,
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
        attributes = super().state_attributes or {}
        attributes["entity"] = "HuoTianDaYou.ai"
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
        
    async def _call_speaker_service(self, text: str) -> None:
        speaker_entity = self.entry.options.get(CONF_SPEAKER_ENTITY)
        speaker_type = self.entry.options.get(CONF_SPEAKER_TYPE, SPEAKER_TYPE_DISABLED)
        
        if not speaker_entity or speaker_type == SPEAKER_TYPE_DISABLED:
            return
            
        try:
            if speaker_type == SPEAKER_TYPE_XIAOMI:
                await self.hass.services.async_call(
                    "xiaomi_miot",
                    "intelligent_speaker",
                    {
                        "entity_id": speaker_entity,
                        "execute": False,
                        "silent": False,
                        "text": text
                    },
                    blocking=True
                )
            elif speaker_type == SPEAKER_TYPE_OTHER:
                tts_service = self.entry.options.get(CONF_TTS_SERVICE)
                if tts_service:
                    service_parts = tts_service.split('.')
                    if len(service_parts) == 2:
                        domain, service = service_parts
                        await self.hass.services.async_call(
                            domain,
                            service,
                            {
                                "entity_id": speaker_entity,
                                "message": text
                            },
                            blocking=True
                        )
        except Exception as e:
            _LOGGER.info("Failed to call speaker service: %s", e)

    async def async_process(
        self, user_input: conversation.ConversationInput
    ) -> conversation.ConversationResult:
        with trace.async_conversation_trace() as conversation_trace:
            agent_manager = conversation.get_agent_manager(self.hass)
            default_agent = get_default_agent(self.hass)
            agent_names = self._convert_agent_info_to_dict(
                agent_manager.async_get_agent_info()
            )
            agent_names[conversation.const.HOME_ASSISTANT_AGENT] = default_agent.name
        
            trace.async_conversation_trace_append(
                trace.ConversationTraceEventType.ASYNC_PROCESS,
                {
                    "text": user_input.text,
                    "conversation_id": user_input.conversation_id,
                    "language": user_input.language,
                    "component": DOMAIN
                }
            )
        
            primary_agent = self.entry.options.get(CONF_PRIMARY_AGENT)
            fallback_agent = self.entry.options.get(CONF_FALLBACK_AGENT)
            secondary_fallback_agent = self.entry.options.get(CONF_SECONDARY_FALLBACK_AGENT)
        
            agents = []
            if primary_agent:
                agents.append(primary_agent)
            if fallback_agent:
                agents.append(fallback_agent)
            if secondary_fallback_agent:
                agents.append(secondary_fallback_agent)
        
            if not agents:
                intent_response = intent.IntentResponse(language=user_input.language)
                intent_response.async_set_error(
                    intent.IntentResponseErrorCode.NO_INTENT_MATCH,
                    "未配置对话代理，请在配置中添加至少一个对话代理。"
                )
                return conversation.ConversationResult(
                    conversation_id=user_input.conversation_id or ulid.ulid(),
                    response=intent_response
                )

            conversation_mode = self.entry.options.get(CONF_CONVERSATION_MODE, CONVERSATION_MODE_ADD_NAME)
            enable_ai_summary = self.entry.options.get(CONF_ENABLE_AI_SUMMARY, False)

            if user_input.conversation_id is None:
                user_input.conversation_id = ulid.ulid()
            is_summary_request = False
            if "请根据用户的问题" in user_input.text and "以及以下AI的回复进行总结和优化" in user_input.text:
                is_summary_request = True
        
            if is_summary_request:
                trace.async_conversation_trace_append(
                    trace.ConversationTraceEventType.AGENT_DETAIL,
                    {"detail": "Processing summary request"}
                )
                result = await self._process_summary_request(user_input, agent_manager, agents, agent_names, default_agent, conversation_mode)
                conversation_trace.set_result(result=result.as_dict())
                return result
        
            if enable_ai_summary and len(agents) >= 2:
                trace.async_conversation_trace_append(
                    trace.ConversationTraceEventType.AGENT_DETAIL,
                    {"detail": "Processing with AI summary", "agents": agents}
                )
                result = await self._process_with_summary(user_input, agent_manager, agents, agent_names, default_agent, conversation_mode)
                conversation_trace.set_result(result=result.as_dict())
                return result
            else:
                trace.async_conversation_trace_append(
                    trace.ConversationTraceEventType.AGENT_DETAIL,
                    {"detail": "Processing with fallback", "agents": agents}
                )
                result = await self._process_with_fallback(user_input, agent_manager, agents, agent_names, default_agent, conversation_mode)
                conversation_trace.set_result(result=result.as_dict())
                return result

    async def _process_summary_request(self, user_input, agent_manager, agents, agent_names, default_agent, conversation_mode):
        if not agents:
            return self._create_error_response(user_input, [], conversation_mode)
            
        agent_id = agents[-1] if agents else None
        if not agent_id:
            return self._create_error_response(user_input, [], conversation_mode)
            
        if not isinstance(agent_id, str):
            if hasattr(agent_id, "__class__") and agent_id.__class__.__name__ == "DefaultAgent":
                agent_id = conversation.const.HOME_ASSISTANT_AGENT
            else:
                try:
                    agent_id = str(agent_id)
                except:
                    agent_id = conversation.const.HOME_ASSISTANT_AGENT
        
        agent_name = agent_names.get(agent_id, "UNKNOWN")
        if agent_id == conversation.const.HOME_ASSISTANT_AGENT:
            agent_name = default_agent.name
            
        try:
            agent = conversation.agent_manager.async_get_agent(self.hass, agent_id)
            result = await agent.async_process(user_input)
            
            response_text = result.response.speech['plain']['speech']
            result.response.speech['plain']['original_speech'] = response_text
            result.response.speech['plain']['agent_name'] = f" ({agent_name})"
            result.response.speech['plain']['agent_id'] = agent_id
            
            if conversation_mode == CONVERSATION_MODE_NO_NAME:
                result.response.speech['plain']['speech'] = response_text
            elif conversation_mode == CONVERSATION_MODE_ADD_NAME:
                result.response.speech['plain']['speech'] = f" ({agent_name}) 回复: {response_text}"
            elif conversation_mode == CONVERSATION_MODE_DETAILED:
                result.response.speech['plain']['speech'] = f" ({agent_name}) 回复: {response_text}"
            
            if (response_text and 
                not response_text.lower().startswith('python') and
                response_text not in DEFAULT_ERROR_RESPONSES and
                len(response_text) > 10):
                self._attr_chat_response = result.response.speech['plain']['speech']
                self.async_write_ha_state()
                asyncio.create_task(self._call_speaker_service(result.response.speech['plain']['speech']))
                return result
        except Exception as e:
            _LOGGER.info("Error processing summary request: %s", e)
            
            trace.async_conversation_trace_append(
                trace.ConversationTraceEventType.AGENT_DETAIL,
                {
                    "error": str(e),
                    "detail": "Error processing summary request"
                }
            )
            
        return self._create_error_response(user_input, [], conversation_mode)

    async def _process_with_summary(self, user_input, agent_manager, agents, agent_names, default_agent, conversation_mode):
        all_results = []
        primary_responses = []
        
        for i in range(len(agents) - 1):
            agent_id = agents[i]
            if not agent_id:
                continue
                
            agent_name = agent_names.get(agent_id, "UNKNOWN")
            if agent_id == conversation.const.HOME_ASSISTANT_AGENT:
                agent_name = default_agent.name
                
            if not isinstance(agent_id, str):
                if hasattr(agent_id, "__class__") and agent_id.__class__.__name__ == "DefaultAgent":
                    agent_id = conversation.const.HOME_ASSISTANT_AGENT
                else:
                    try:
                        agent_id = str(agent_id)
                    except:
                        agent_id = conversation.const.HOME_ASSISTANT_AGENT
            
            result = await self._async_process_agent(
                agent_manager,
                agent_id,
                agent_name,
                user_input,
                CONVERSATION_MODE_NO_NAME,  
                None,
            )
            
            response_text = result.response.speech['plain']['original_speech'].strip()
            
            if (response_text and 
                not response_text.lower().startswith('python') and
                response_text not in DEFAULT_ERROR_RESPONSES and
                len(response_text) > 10):
                primary_responses.append({"agent_name": agent_name, "response": response_text})
            all_results.append(result)
        
        if not primary_responses:
            return self._create_error_response(user_input, all_results, conversation_mode)
        
        final_agent_id = agents[-1]
        if not isinstance(final_agent_id, str):
            if hasattr(final_agent_id, "__class__") and final_agent_id.__class__.__name__ == "DefaultAgent":
                final_agent_id = conversation.const.HOME_ASSISTANT_AGENT
            else:
                try:
                    final_agent_id = str(final_agent_id)
                except:
                    final_agent_id = conversation.const.HOME_ASSISTANT_AGENT
        
        summary_prompt = f"""<AI_SUMMARY_REQUEST>
请根据用户的问题：'{user_input.text}'，以及以下AI的回复进行总结和优化：

"""
        
        for resp in primary_responses:
            summary_prompt += f"- {resp['agent_name']}：{resp['response']}\n"
            
        summary_prompt += """
请你首先进行多维度的思考分析，然后给出最终的回复结果，最终结果不要解释自己为什么这样回复。你的回复必须严格按照以下格式：

<ANALYSIS_SECTION>

[评估各个AI回复的准确性和完整性]

</ANALYSIS_SECTION>

<SUMMARY_SECTION>
[在这里提供简洁、清晰、有条理的总结，最终更新所有AI的答案生成自己的答案]
</SUMMARY_SECTION>

严格注意：
- 你的回复必须包含且仅包含上述两个部分，并使用指定的标记
- 不要在回复中添加任何其他前言、说明或额外内容
- 不要使用"这里是我的分析"等引导语
- 分析部分必须在代码块中，总结部分必须在标记内
- 总结应该综合各个AI的观点，并添加你自己的见解

请严格按照上述格式回复，不要有任何偏差。
</AI_SUMMARY_REQUEST>
"""
        
        device_id = getattr(user_input, "device_id", None)
        
        try:
            original_context = getattr(user_input, "context", {})
            
            summary_input = conversation.ConversationInput(
                text=summary_prompt,
                conversation_id=user_input.conversation_id,
                language=user_input.language,
                context=original_context, 
                device_id=device_id,
                agent_id=final_agent_id
            )
        except Exception as e:
            _LOGGER.error("Failed to create summary input: %s", e)
            
            trace.async_conversation_trace_append(
                trace.ConversationTraceEventType.AGENT_DETAIL,
                {
                    "error": str(e),
                    "detail": "Failed to create summary input"
                }
            )
            
            return self._create_error_response(user_input, all_results, conversation_mode)
        
        final_agent_name = agent_names.get(final_agent_id, "UNKNOWN")
        if final_agent_id == conversation.const.HOME_ASSISTANT_AGENT:
            final_agent_name = default_agent.name
            
        result = await self._async_process_agent(
            agent_manager,
            final_agent_id,
            final_agent_name, 
            summary_input,
            CONVERSATION_MODE_NO_NAME,  
            None,
        )
        
        response_text = result.response.speech['plain']['original_speech'].strip()
        
        cleaned_response = self._clean_ai_response(response_text)
        
        analysis_part = cleaned_response.get('analysis', '')
        summary_part = cleaned_response.get('summary', '')
        
        if conversation_mode == CONVERSATION_MODE_NO_NAME:
            result.response.speech['plain']['speech'] = summary_part if summary_part else response_text
        elif conversation_mode == CONVERSATION_MODE_ADD_NAME:
            result.response.speech['plain']['speech'] = f" ({final_agent_name}) 回复: {summary_part if summary_part else response_text}"
        elif conversation_mode == CONVERSATION_MODE_DETAILED:
            detailed_response = ""
            
            for resp in primary_responses:
                detailed_response += f" ({resp['agent_name']}) 回复: {resp['response']}\n"
            
            detailed_response += "\n"
            
            if analysis_part:
                detailed_response += f"\n{analysis_part}\n\n\n"
            
            if summary_part:
                detailed_response += f" ({final_agent_name}) 回复: {summary_part}"
            else:
                detailed_response += f" ({final_agent_name}) 回复: {response_text}"
            
            result.response.speech['plain']['speech'] = detailed_response
        
        if (response_text and 
            not response_text.lower().startswith('python') and
            response_text not in DEFAULT_ERROR_RESPONSES and
            len(response_text) > 10):
            self._attr_chat_response = result.response.speech['plain']['speech']
            self.async_write_ha_state()
            asyncio.create_task(self._call_speaker_service(result.response.speech['plain']['speech']))
            return result
        all_results.append(result)
        
        return self._create_error_response(user_input, all_results, conversation_mode)

    async def _process_with_fallback(self, user_input, agent_manager, agents, agent_names, default_agent, conversation_mode):
        
        all_results = []
        result = None
        
        for agent_id in agents:
            if not agent_id:
                continue
                
            agent_name = agent_names.get(agent_id, "UNKNOWN")
            if agent_id == conversation.const.HOME_ASSISTANT_AGENT:
                agent_name = default_agent.name
            
            if not isinstance(agent_id, str):
                if hasattr(agent_id, "__class__") and agent_id.__class__.__name__ == "DefaultAgent":
                    agent_id = conversation.const.HOME_ASSISTANT_AGENT
                else:
                    try:
                        agent_id = str(agent_id)
                    except:
                        agent_id = conversation.const.HOME_ASSISTANT_AGENT
            
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
                response_text not in DEFAULT_ERROR_RESPONSES and
                len(response_text) > 10):
                self._attr_chat_response = result.response.speech['plain']['speech']
                self.async_write_ha_state()
                asyncio.create_task(self._call_speaker_service(result.response.speech['plain']['speech']))
                return result
            all_results.append(result)
        
        return self._create_error_response(user_input, all_results, conversation_mode)

    def _clean_ai_response(self, response_text):
        result = {
            'analysis': '',
            'summary': ''
        }
        
        if '<AI_SUMMARY_REQUEST>' in response_text:
            response_text = response_text.replace('<AI_SUMMARY_REQUEST>', '').strip()
        if '</AI_SUMMARY_REQUEST>' in response_text:
            response_text = response_text.replace('</AI_SUMMARY_REQUEST>', '').strip()
        
        if '<ANALYSIS_SECTION>' in response_text and '</ANALYSIS_SECTION>' in response_text:
            try:
                analysis = response_text.split('<ANALYSIS_SECTION>', 1)[1].split('</ANALYSIS_SECTION>', 1)[0].strip()
                result['analysis'] = analysis
            except IndexError:
                pass

        if '<SUMMARY_SECTION>' in response_text and '</SUMMARY_SECTION>' in response_text:
            try:
                summary = response_text.split('<SUMMARY_SECTION>', 1)[1].split('</SUMMARY_SECTION>', 1)[0].strip()
                result['summary'] = summary
            except IndexError:
                pass
        elif not result['summary']:
            if result['analysis'] and '```' in response_text:
                try:
                    summary_part = response_text.split('```', 2)[2].strip()
                    result['summary'] = summary_part
                except IndexError:
                    pass
            if not result['summary']:
                clean_text = response_text
                for tag in ['<ANALYSIS_SECTION>', '</ANALYSIS_SECTION>', '<SUMMARY_SECTION>', '</SUMMARY_SECTION>']:
                    clean_text = clean_text.replace(tag, '')
                result['summary'] = clean_text.strip()
        
        return result

    def _create_error_response(self, user_input, all_results, conversation_mode):
        intent_response = intent.IntentResponse(language=user_input.language)
        err = "error processing!"
        
        trace.async_conversation_trace_append(
            trace.ConversationTraceEventType.AGENT_DETAIL,
            {
                "error": err,
                "detail": "Creating error response"
            }
        )
        
        if conversation_mode == CONVERSATION_MODE_DETAILED and all_results:
            for res in all_results:
                if res and hasattr(res, 'response') and res.response and hasattr(res.response, 'speech'):
                    r = res.response.speech['plain']
                    err += f"\n{r.get('agent_name', 'UNKNOWN')} 回复: {r.get('original_speech', r['speech'])}"
        
        intent_response.async_set_error(
            intent.IntentResponseErrorCode.NO_INTENT_MATCH,
            err,
        )
        
        result = conversation.ConversationResult(
            conversation_id=user_input.conversation_id,
            response=intent_response
        )
        
        self._attr_chat_response = err
        self.async_write_ha_state()
        asyncio.create_task(self._call_speaker_service(err))
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
        trace.async_conversation_trace_append(
            trace.ConversationTraceEventType.AGENT_DETAIL,
            {
                "agent_id": agent_id,
                "agent_name": agent_name,
                "text": user_input.text
            }
        )
        
        agent = conversation.agent_manager.async_get_agent(self.hass, agent_id)

        try:
            result = await agent.async_process(user_input)
            
            trace.async_conversation_trace_append(
                trace.ConversationTraceEventType.AGENT_DETAIL,
                {
                    "agent_id": agent_id,
                    "agent_name": agent_name,
                    "response": result.response.speech['plain']['speech'] if result.response.speech and 'plain' in result.response.speech else "No response"
                }
            )
        except Exception as e:
            _LOGGER.info("Error processing agent %s: %s", agent_id, e)
            trace.async_conversation_trace_append(
                trace.ConversationTraceEventType.AGENT_DETAIL,
                {
                    "agent_id": agent_id,
                    "agent_name": agent_name,
                    "error": str(e)
                }
            )
            raise
            
        r = result.response.speech['plain']['speech']
        result.response.speech['plain']['original_speech'] = r
        result.response.speech['plain']['agent_name'] = agent_name
        result.response.speech['plain']['agent_id'] = agent_id
        
        is_summary = False
        if "请根据用户的问题" in user_input.text and "以及以下AI的回复进行总结和优化" in user_input.text:
            is_summary = True
        
        if conversation_mode == CONVERSATION_MODE_NO_NAME:
            result.response.speech['plain']['speech'] = r
        elif conversation_mode == CONVERSATION_MODE_ADD_NAME:
            if is_summary:
                result.response.speech['plain']['speech'] = f" {agent_name} 回复: {r}"
            else:
                result.response.speech['plain']['speech'] = f"{agent_name} 回复: {r}"
        elif conversation_mode == CONVERSATION_MODE_DETAILED:
            if is_summary:
                result.response.speech['plain']['speech'] = f" ({agent_name}) 回复: {r}"
            elif previous_result is not None:
                if previous_result.response.response_type == intent.IntentResponseType.ERROR:
                    prev_name = previous_result.response.speech['plain'].get('agent_name', 'UNKNOWN')
                    prev_text = previous_result.response.speech['plain'].get('original_speech', previous_result.response.speech['plain']['speech'])
                    result.response.speech['plain']['speech'] = f"{prev_name} 失败，回复: {prev_text} 然后 {agent_name} 回复: {r}"
                else:
                    result.response.speech['plain']['speech'] = f"{agent_name} 回复: {r}"
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
                r[agent_id] = self.hass.states.get(agent_id).attributes.get("friendly_name", agent_info.name)
            else:
                r[agent_id] = agent_info.name
                
            _LOGGER.debug("agent_id %s has name %s", agent_id, r[agent_id])
        return r