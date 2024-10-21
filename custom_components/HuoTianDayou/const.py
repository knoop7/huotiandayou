
DOMAIN = "kadermanager"

CONF_PRIMARY_AGENT = "primary_agent"
CONF_FALLBACK_AGENT = "fallback_agent"
CONF_SECONDARY_FALLBACK_AGENT = "secondary_fallback_agent"
CONF_CONVERSATION_MODE = "conversation_mode"

CONVERSATION_MODE_NO_NAME = "no_name"
CONVERSATION_MODE_ADD_NAME = "add_name"
CONVERSATION_MODE_DETAILED = "detailed"

DEFAULT_NAME = "火天大有（聚合AI）"
DEFAULT_CONVERSATION_MODE = CONVERSATION_MODE_ADD_NAME
DEFAULT_PRIMARY_AGENT = "HomeAssistant"
DEFAULT_FALLBACK_AGENT = "HomeAssistant"
DEFAULT_SECONDARY_FALLBACK_AGENT = None

PLATFORMS = ["conversation"]

# 可自行添加，是检测句。
STRANGE_ERROR_RESPONSES = [
    "很抱歉，我无法理解你的问题。",
    "对不起，我没有找到相关的答案。",
    "抱歉，我不明白你的意思。",
    "抱歉，暂不支持该操作。如果问题持续，可能需要调整指令。"
]