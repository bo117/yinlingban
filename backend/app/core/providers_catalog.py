# -*- coding: utf-8 -*-
"""
大模型总目录（角色2：郝英博 · 全厂商预置）

用户一句话需求：市面上能接到的所有大模型 API，请求地址、模型名称、
完整 URL 全都不用手动填——在这里全部预置好，界面上点选即可。

目录结构（三大能力）：
  LLM_PROVIDERS    文字大脑（对话大模型）
  VISION_PROVIDERS 图片/文字识别（多模态视觉模型）
  TTS_PROVIDERS    语音合成 TTS（火山引擎豆包语音等）

每家的字段：
  id        程序内部标识（保存到 .env 用）
  name      中文显示名（设置页展示）
  base_url  请求地址（预置好，不用手填）
  protocol  openai（OpenAI 兼容协议，绝大多数厂商） / anthropic（Claude 专用协议）
  models    模型列表 [{id, name, tags}]，第一个为"推荐"默认选中
  site      申请 Key 的官网
  key_hint  Key 长什么样子（输入框占位提示）
  note      补充说明（域名备选、注意事项等）

注意：本模块只放"公共目录数据"，不 import 任何项目模块（config 会反过来调用它，
避免循环导入）。加了新厂商只需在对应字典加一条即可，其余部分全自动。
"""

# ============================================================
# 一、文字大脑：对话大模型（20 家主流厂商，全部 OpenAI 兼容除 Claude）
# ============================================================
LLM_PROVIDERS = {
    "doubao": {
        "id": "doubao", "name": "豆包 · 主力（火山方舟）", "name_en": "Doubao",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3", "protocol": "openai",
        "site": "https://console.volcengine.com/ark",
        "key_hint": "API Key：先建「推理接入点」",
        "note": "【主力】情绪价值与中文语气最好，本产品默认；火山方舟地址已预置，Key 是平台 API Key，模型名也可用「接入点ID」",
        "models": [
            {"id": "doubao-seed-1-6", "name": "豆包 Seed 1.6（最新·推荐）", "tags": ["推荐", "最新"]},
            {"id": "doubao-1.5-pro-32k", "name": "豆包 1.5 Pro", "tags": []},
            {"id": "doubao-1.5-lite-32k", "name": "豆包 1.5 Lite（快）", "tags": []},
            {"id": "doubao-seed-1-6-flash", "name": "豆包 Seed Flash（极速）", "tags": []},
        ],
    },
    "openai": {
        "id": "openai", "name": "GPT · 主力（OpenAI）", "name_en": "OpenAI",
        "base_url": "https://api.openai.com/v1", "protocol": "openai",
        "site": "https://platform.openai.com",
        "key_hint": "sk- 开头",
        "note": "【主力】情绪价值与生图能力一流；海外服务，国内直连需网络条件（可用 OpenRouter/AiHubMix 中转或自定义地址）",
        "models": [
            {"id": "gpt-6", "name": "GPT-6（最新旗舰）", "tags": ["旗舰", "最新"]},
            {"id": "gpt-5", "name": "GPT-5（上一代旗舰）", "tags": []},
            {"id": "gpt-5-mini", "name": "GPT-5 mini（快·推荐）", "tags": ["推荐"]},
            {"id": "gpt-4.1", "name": "GPT-4.1（长文本）", "tags": []},
            {"id": "gpt-4o", "name": "GPT-4o（多模态经典）", "tags": ["多模态"]},
            {"id": "gpt-4o-mini", "name": "GPT-4o mini（便宜）", "tags": []},
            {"id": "o3-mini", "name": "o3-mini（推理强）", "tags": ["推理"]},
        ],
    },
    "deepseek": {
        "id": "deepseek", "name": "DeepSeek · 辅助（写作/中文推理强）", "name_en": "DeepSeek",
        "base_url": "https://api.deepseek.com", "protocol": "openai",
        "site": "https://platform.deepseek.com",
        "key_hint": "sk- 开头",
        "note": "【辅助】写作与中文推理很强，但语气与关照度不如豆包/GPT——适合当备用脑",
        "models": [
            {"id": "deepseek-v4-flash", "name": "V4 Flash（快而省·推荐）", "tags": ["推荐"]},
            {"id": "deepseek-v4-pro", "name": "V4 Pro（最强·复杂问题）", "tags": ["旗舰"]},
            {"id": "deepseek-chat", "name": "V3 经典版（稳定便宜）", "tags": []},
            {"id": "deepseek-reasoner", "name": "R1 深度思考（慢但细）", "tags": ["推理"]},
        ],
    },
    "minimax": {
        "id": "minimax", "name": "MiniMax 稀宇科技", "name_en": "MiniMax",
        "base_url": "https://api.minimaxi.com/v1", "protocol": "openai",
        "site": "https://platform.minimaxi.com",
        "key_hint": "长串 Key（eyJ 开头）",
        "note": "国际站地址已预置；若用的是国内站，把请求地址换成 https://api.minimax.chat/v1 即可",
        "models": [
            {"id": "MiniMax-M2", "name": "MiniMax M2（最新·推荐）", "tags": ["推荐", "最新"]},
            {"id": "MiniMax-Text-01", "name": "Text-01 旗舰", "tags": []},
            {"id": "MiniMax-M1", "name": "M1 推理模型（深度思考）", "tags": ["推理"]},
            {"id": "abab6.5s-chat", "name": "abab6.5s 经典（便宜快）", "tags": []},
        ],
    },
    "anthropic": {
        "id": "anthropic", "name": "Anthropic Claude", "name_en": "Claude",
        "base_url": "https://api.anthropic.com/v1", "protocol": "anthropic",
        "site": "https://console.anthropic.com",
        "key_hint": "sk-ant- 开头",
        "note": "Claude 用的是自家协议，本系统已内置适配（无需中转）；海外服务",
        "models": [
            {"id": "claude-sonnet-4-5", "name": "Claude Sonnet 4.5（均衡·推荐）", "tags": ["推荐"]},
            {"id": "claude-opus-4-1", "name": "Claude Opus 4.1（最强）", "tags": ["旗舰"]},
            {"id": "claude-sonnet-4-20250514", "name": "Claude Sonnet 4（经典）", "tags": []},
            {"id": "claude-haiku-4-5", "name": "Claude Haiku 4.5（快而省）", "tags": []},
        ],
    },
    "gemini": {
        "id": "gemini", "name": "Google Gemini 谷歌", "name_en": "Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "protocol": "openai",
        "site": "https://aistudio.google.com/apikey",
        "key_hint": "AIza 开头",
        "note": "已预置 OpenAI 兼容地址（免中转）；个人有免费额度；海外服务",
        "models": [
            {"id": "gemini-2.5-pro", "name": "2.5 Pro（最强·推荐）", "tags": ["推荐", "多模态"]},
            {"id": "gemini-2.5-flash", "name": "2.5 Flash（快·多模态）", "tags": ["多模态"]},
            {"id": "gemini-2.5-flash-lite", "name": "2.5 Flash-Lite（最便宜）", "tags": []},
            {"id": "gemini-2.0-flash", "name": "2.0 Flash（免费额度）", "tags": ["免费"]},
        ],
    },
    "qwen": {
        "id": "qwen", "name": "阿里云 通义千问", "name_en": "Qwen",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "protocol": "openai",
        "site": "https://bailian.console.aliyun.com",
        "key_hint": "sk- 开头",
        "note": "国内直连；兼容模式地址已预置",
        "models": [
            {"id": "qwen3-max", "name": "Qwen3 Max（最新·推荐）", "tags": ["推荐", "最新"]},
            {"id": "qwen-max", "name": "qwen-max 旗舰", "tags": []},
            {"id": "qwen-plus", "name": "qwen-plus 均衡", "tags": []},
            {"id": "qwen-turbo", "name": "qwen-turbo 快", "tags": []},
            {"id": "qwen-long", "name": "qwen-long 长文本", "tags": []},
        ],
    },
    "glm": {
        "id": "glm", "name": "智谱 AI GLM", "name_en": "GLM",
        "base_url": "https://open.bigmodel.cn/api/paas/v4", "protocol": "openai",
        "site": "https://open.bigmodel.cn",
        "key_hint": "id.secret 两段式",
        "note": "国内直连；GLM 系列中文口碑好",
        "models": [
            {"id": "glm-4.6", "name": "GLM-4.6（最新·推荐）", "tags": ["推荐", "最新"]},
            {"id": "glm-4.5-air", "name": "GLM-4.5-Air（轻量）", "tags": []},
            {"id": "glm-4-plus", "name": "GLM-4-Plus（经典旗舰）", "tags": []},
            {"id": "glm-4-flash", "name": "GLM-4-Flash（免费）", "tags": ["免费"]},
            {"id": "glm-4-long", "name": "GLM-4-Long（长文本）", "tags": []},
        ],
    },
    "qianfan": {
        "id": "qianfan", "name": "百度智能云 文心一言", "name_en": "ERNIE",
        "base_url": "https://qianfan.baidubce.com/v2", "protocol": "openai",
        "site": "https://console.bce.baidu.com/qianfan",
        "key_hint": "AK 和 SK 通过插件获取 Bearer Key",
        "note": "千帆 v2 已预置 OpenAI 兼容地址",
        "models": [
            {"id": "ernie-4.5-turbo", "name": "ERNIE-4.5-Turbo（推荐）", "tags": ["推荐"]},
            {"id": "ernie-4.0-8k", "name": "ERNIE-4.0-8K（经典）", "tags": []},
            {"id": "ernie-speed-8k", "name": "ERNIE-Speed-8K（免费）", "tags": ["免费"]},
            {"id": "ernie-lite-8k", "name": "ERNIE-Lite-8K（轻量）", "tags": []},
        ],
    },
    "hunyuan": {
        "id": "hunyuan", "name": "腾讯云 混元", "name_en": "Hunyuan",
        "base_url": "https://api.hunyuan.cloud.tencent.com/v1", "protocol": "openai",
        "site": "https://cloud.tencent.com/product/hunyuan",
        "key_hint": "sk- 开头",
        "note": "国内直连；混元地址已预置",
        "models": [
            {"id": "hunyuan-turbos-latest", "name": "hunyuan-turbos（推荐）", "tags": ["推荐"]},
            {"id": "hunyuan-pro", "name": "hunyuan-pro（旗舰）", "tags": []},
            {"id": "hunyuan-lite", "name": "hunyuan-lite（免费）", "tags": ["免费"]},
        ],
    },
    "stepfun": {
        "id": "stepfun", "name": "阶跃星辰 Step", "name_en": "StepFun",
        "base_url": "https://api.stepfun.com/v1", "protocol": "openai",
        "site": "https://platform.stepfun.com",
        "key_hint": "sk- 开头",
        "note": "国内直连；中文评测排名靠前",
        "models": [
            {"id": "step-2-16k", "name": "Step-2 16K（旗舰·推荐）", "tags": ["推荐"]},
            {"id": "step-2-mini", "name": "Step-2 mini（快）", "tags": []},
            {"id": "step-1-8k", "name": "Step-1 8K（均衡）", "tags": []},
            {"id": "step-1-flash", "name": "Step-1 Flash（极速）", "tags": []},
        ],
    },
    "siliconflow": {
        "id": "siliconflow", "name": "硅基流动 SiliconFlow", "name_en": "SiliconFlow",
        "base_url": "https://api.siliconflow.cn/v1", "protocol": "openai",
        "site": "https://cloud.siliconflow.cn",
        "key_hint": "sk- 开头",
        "note": "国内直连；上面跑着几十个开源模型，冷门模型都能在这里试",
        "models": [
            {"id": "deepseek-ai/DeepSeek-V3", "name": "DeepSeek-V3（开源·推荐）", "tags": ["推荐"]},
            {"id": "deepseek-ai/DeepSeek-R1", "name": "DeepSeek-R1（推理）", "tags": ["推理"]},
            {"id": "Qwen/Qwen2.5-72B-Instruct", "name": "Qwen2.5-72B 开源", "tags": []},
            {"id": "THUDM/glm-4-9b-chat", "name": "GLM-4-9B 开源（免费）", "tags": ["免费"]},
        ],
    },
    "mistral": {
        "id": "mistral", "name": "Mistral（欧洲）", "name_en": "Mistral",
        "base_url": "https://api.mistral.ai/v1", "protocol": "openai",
        "site": "https://console.mistral.ai",
        "key_hint": "长串 Key",
        "note": "欧洲开源强厂；海外服务",
        "models": [
            {"id": "mistral-large-latest", "name": "Large（旗舰·推荐）", "tags": ["推荐"]},
            {"id": "mistral-small-latest", "name": "Small（均衡）", "tags": []},
            {"id": "open-mistral-nemo", "name": "Nemo（免费）", "tags": ["免费"]},
        ],
    },
    "groq": {
        "id": "groq", "name": "Groq（超快推理）", "name_en": "Groq",
        "base_url": "https://api.groq.com/openai/v1", "protocol": "openai",
        "site": "https://console.groq.com",
        "key_hint": "gsk_ 开头",
        "note": "开源模型极速推理，LlaMa 系列；有免费额度；海外服务",
        "models": [
            {"id": "llama-3.3-70b-versatile", "name": "Llama-3.3-70B（推荐）", "tags": ["推荐"]},
            {"id": "deepseek-r1-distill-llama-70b", "name": "DeepSeek-R1 蒸馏版", "tags": ["推理"]},
            {"id": "llama-3.1-8b-instant", "name": "Llama-3.1-8B（免费）", "tags": ["免费"]},
        ],
    },
    "xai": {
        "id": "xai", "name": "xAI Grok", "name_en": "Grok",
        "base_url": "https://api.x.ai/v1", "protocol": "openai",
        "site": "https://console.x.ai",
        "key_hint": "xai- 开头",
        "note": "马斯克家的 Grok；海外服务",
        "models": [
            {"id": "grok-4", "name": "Grok-4（最新·推荐）", "tags": ["推荐", "最新"]},
            {"id": "grok-3", "name": "Grok-3（上一代旗舰）", "tags": []},
            {"id": "grok-2-latest", "name": "Grok-2（稳定）", "tags": []},
        ],
    },
    "baichuan": {
        "id": "baichuan", "name": "百川智能", "name_en": "Baichuan",
        "base_url": "https://api.baichuan-ai.com/v1", "protocol": "openai",
        "site": "https://platform.baichuan-ai.com",
        "key_hint": "sk- 开头",
        "note": "国内直连",
        "models": [
            {"id": "Baichuan4", "name": "Baichuan4（旗舰·推荐）", "tags": ["推荐"]},
            {"id": "Baichuan4-Air", "name": "Baichuan4-Air（轻量）", "tags": []},
            {"id": "Baichuan3-Turbo", "name": "Baichuan3-Turbo（快）", "tags": []},
        ],
    },
    "openrouter": {
        "id": "openrouter", "name": "OpenRouter（一个 Key 通吃 GPT/Claude/Gemini）", "name_en": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1", "protocol": "openai",
        "site": "https://openrouter.ai/keys",
        "key_hint": "sk-or- 开头",
        "note": "聚合中转：不想注册多家时的省事选择，国内可用；模型名带厂商前缀",
        "models": [
            {"id": "anthropic/claude-sonnet-4.5", "name": "Claude Sonnet 4.5（推荐）", "tags": ["推荐"]},
            {"id": "openai/gpt-5", "name": "GPT-5", "tags": ["旗舰"]},
            {"id": "openai/gpt-4o", "name": "GPT-4o", "tags": []},
            {"id": "google/gemini-2.5-pro", "name": "Gemini 2.5 Pro", "tags": []},
            {"id": "deepseek/deepseek-chat", "name": "DeepSeek V3", "tags": []},
        ],
    },
    "aihubmix": {
        "id": "aihubmix", "name": "AiHubMix 中转（GPT/Claude/Gemini 直连可用）", "name_en": "AiHubMix",
        "base_url": "https://aihubmix.com/v1", "protocol": "openai",
        "site": "https://aihubmix.com",
        "key_hint": "sk- 开头",
        "note": "国内直连的中转聚合：人民币充值，一个 Key 用 GPT/Claude/Gemini 全家；模型名与官方一致",
        "models": [
            {"id": "gpt-5-mini", "name": "GPT-5 mini（推荐）", "tags": ["推荐"]},
            {"id": "claude-sonnet-4-5", "name": "Claude Sonnet 4.5", "tags": []},
            {"id": "gemini-2.5-pro", "name": "Gemini 2.5 Pro", "tags": []},
            {"id": "gpt-4o", "name": "GPT-4o", "tags": []},
        ],
    },
    "deepinfra": {
        "id": "deepinfra", "name": "DeepInfra（开源模型中转）", "name_en": "DeepInfra",
        "base_url": "https://api.deepinfra.com/v1/openai", "protocol": "openai",
        "site": "https://deepinfra.com",
        "key_hint": "长串 Key",
        "note": "海外开源模型聚合，价格低；Llama / Qwen / DeepSeek 系列",
        "models": [
            {"id": "meta-llama/Llama-3.3-70B-Instruct-Turbo", "name": "Llama-3.3-70B（推荐）", "tags": ["推荐"]},
            {"id": "deepseek-ai/DeepSeek-V3", "name": "DeepSeek-V3", "tags": []},
            {"id": "Qwen/Qwen2.5-72B-Instruct", "name": "Qwen2.5-72B", "tags": []},
        ],
    },
    "together": {
        "id": "together", "name": "Together AI（开源模型云）", "name_en": "Together",
        "base_url": "https://api.together.xyz/v1", "protocol": "openai",
        "site": "https://api.together.ai",
        "key_hint": "长串 Key",
        "note": "开源模型极速推理；海外服务",
        "models": [
            {"id": "meta-llama/Llama-3.3-70B-Instruct-Turbo", "name": "Llama-3.3-70B（推荐）", "tags": ["推荐"]},
            {"id": "deepseek-ai/DeepSeek-V3", "name": "DeepSeek-V3", "tags": []},
            {"id": "Qwen/Qwen2.5-72B-Instruct", "name": "Qwen2.5-72B", "tags": []},
        ],
    },
    "custom": {
        "id": "custom", "name": "自定义（OpenAI 兼容中转/网关）", "name_en": "Custom",
        "base_url": "", "protocol": "openai",
        "site": "",
        "key_hint": "该服务的 API Key（请求地址单独填）",
        "note": "任何 OpenAI 兼容的中转/网关：公司内网、聚合中转等。选此项后填请求地址与模型名，模型名按你的网关实际支持自由填写",
        "models": [
            {"id": "gpt-6", "name": "gpt-6（示例，可自填其它模型）", "tags": ["示例"]},
        ],
    },
}

# ============================================================
# 二、图片/文字识别：多模态视觉模型（同一家厂商复用同一个 Key）
# ============================================================
VISION_PROVIDERS = {
    "openai": {
        "id": "openai", "name": "GPT-4o 看图 · 主力（OpenAI）", "name_en": "OpenAI",
        "base_url": "https://api.openai.com/v1", "protocol": "openai",
        "site": "https://platform.openai.com", "key_hint": "sk- 开头",
        "note": "识图+看图问答全能",
        "models": [
            {"id": "gpt-4o", "name": "GPT-4o（全能·推荐）", "tags": ["推荐"]},
            {"id": "gpt-4o-mini", "name": "GPT-4o mini（省）", "tags": []},
        ],
    },
    "anthropic": {
        "id": "anthropic", "name": "Claude 看图", "name_en": "Claude",
        "base_url": "https://api.anthropic.com/v1", "protocol": "anthropic",
        "site": "https://console.anthropic.com", "key_hint": "sk-ant- 开头",
        "note": "文档/截图阅读理解强",
        "models": [
            {"id": "claude-sonnet-4-20250514", "name": "Claude Sonnet 4（推荐）", "tags": ["推荐"]},
        ],
    },
    "gemini": {
        "id": "gemini", "name": "Google Gemini 看图", "name_en": "Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "protocol": "openai",
        "site": "https://aistudio.google.com/apikey", "key_hint": "AIza 开头",
        "note": "免费额度大，识图准",
        "models": [
            {"id": "gemini-2.5-flash", "name": "2.5 Flash（快·推荐）", "tags": ["推荐"]},
            {"id": "gemini-2.5-pro", "name": "2.5 Pro（最强）", "tags": []},
            {"id": "gemini-2.0-flash", "name": "2.0 Flash（免费）", "tags": []},
        ],
    },
    "qwen": {
        "id": "qwen", "name": "通义千问 VL 看图", "name_en": "Qwen-VL",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "protocol": "openai",
        "site": "https://bailian.console.aliyun.com", "key_hint": "sk- 开头",
        "note": "国内识图，中文场景友好",
        "models": [
            {"id": "qwen-vl-max", "name": "qwen-vl-max（推荐）", "tags": ["推荐"]},
            {"id": "qwen-vl-plus", "name": "qwen-vl-plus（均衡）", "tags": []},
        ],
    },
    "glm": {
        "id": "glm", "name": "智谱 GLM-4V 看图", "name_en": "GLM-4V",
        "base_url": "https://open.bigmodel.cn/api/paas/v4", "protocol": "openai",
        "site": "https://open.bigmodel.cn", "key_hint": "id.secret 两段式",
        "note": "国内直连；GLM-4V-Flash 免费",
        "models": [
            {"id": "glm-4v-plus", "name": "GLM-4V-Plus（推荐）", "tags": ["推荐"]},
            {"id": "glm-4v-flash", "name": "GLM-4V-Flash（免费）", "tags": ["免费"]},
        ],
    },
    "minimax": {
        "id": "minimax", "name": "MiniMax 看图", "name_en": "MiniMax-VL",
        "base_url": "https://api.minimaxi.com/v1", "protocol": "openai",
        "site": "https://platform.minimaxi.com", "key_hint": "长串 Key（eyJ 开头）",
        "note": "国内可用国内站地址 https://api.minimax.chat/v1",
        "models": [
            {"id": "MiniMax-VL-01", "name": "MiniMax-VL-01（推荐）", "tags": ["推荐"]},
        ],
    },
    "doubao": {
        "id": "doubao", "name": "豆包看图 · 主力（火山方舟）", "name_en": "Doubao",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3", "protocol": "openai",
        "site": "https://console.volcengine.com/ark", "key_hint": "平台 API Key",
        "note": "价格便宜；模型名也可填方舟的「接入点ID」",
        "models": [
            {"id": "doubao-1.5-vision-pro-32k", "name": "豆包 视觉 Pro（推荐）", "tags": ["推荐"]},
        ],
    },
    "hunyuan": {
        "id": "hunyuan", "name": "腾讯混元 看图", "name_en": "Hunyuan",
        "base_url": "https://api.hunyuan.cloud.tencent.com/v1", "protocol": "openai",
        "site": "https://cloud.tencent.com/product/hunyuan", "key_hint": "sk- 开头",
        "note": "国内直连",
        "models": [
            {"id": "hunyuan-vision", "name": "hunyuan-vision（推荐）", "tags": ["推荐"]},
            {"id": "hunyuan-turbos-vision-latest", "name": "hunyuan-turbos-vision", "tags": []},
        ],
    },
    "stepfun": {
        "id": "stepfun", "name": "阶跃星辰 看图", "name_en": "StepFun",
        "base_url": "https://api.stepfun.com/v1", "protocol": "openai",
        "site": "https://platform.stepfun.com", "key_hint": "sk- 开头",
        "note": "国内直连",
        "models": [
            {"id": "step-1v-32k", "name": "Step-1V-32K（推荐）", "tags": ["推荐"]},
        ],
    },
    "openrouter": {
        "id": "openrouter", "name": "OpenRouter 看图（Claude/GPT 聚合）", "name_en": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1", "protocol": "openai",
        "site": "https://openrouter.ai/keys", "key_hint": "sk-or- 开头",
        "note": "和文字同一个 OpenRouter Key；国内可用",
        "models": [
            {"id": "anthropic/claude-sonnet-4.5", "name": "Claude Sonnet 4.5（推荐）", "tags": ["推荐"]},
            {"id": "openai/gpt-4o", "name": "GPT-4o", "tags": []},
        ],
    },
    "siliconflow": {
        "id": "siliconflow", "name": "硅基流动 看图", "name_en": "SiliconFlow",
        "base_url": "https://api.siliconflow.cn/v1", "protocol": "openai",
        "site": "https://cloud.siliconflow.cn", "key_hint": "sk- 开头",
        "note": "开源视觉模型集散地",
        "models": [
            {"id": "Qwen/Qwen2.5-VL-72B-Instruct", "name": "Qwen2.5-VL-72B 开源（推荐）", "tags": ["推荐"]},
            {"id": "Qwen/Qwen2-VL-7B-Instruct", "name": "Qwen2-VL-7B 开源（省）", "tags": []},
        ],
    },
    "custom": {
        "id": "custom", "name": "自定义（OpenAI 兼容视觉网关）", "name_en": "Custom Vision",
        "base_url": "", "protocol": "openai",
        "site": "",
        "key_hint": "该服务的 API Key（请求地址单独填）",
        "note": "任何 OpenAI 兼容的多模态网关：模型名按你的网关实际支持自由填写，不限于示例",
        "models": [
            {"id": "gpt-4o", "name": "gpt-4o（示例，可自填其它模型）", "tags": ["示例"]},
        ],
    },
}

# ============================================================
# 三、语音合成 TTS（统一走火山引擎 / GPT，另留 OpenAI 兼容自定义位）
# ------------------------------------------------------------
# 每家带 voices 音色表（M=男声 / F=女声），前端「音色」胶囊直接渲染；
# 火山引擎 Key 格式：AppID:AccessToken（冒号分隔；只填 AccessToken 时
# AppID 从 .env 的 VOLC_TTS_APPID 读）。
# ============================================================
TTS_PROVIDERS = {
    "volcengine": {
        "id": "volcengine", "name": "火山引擎 · 豆包语音", "name_en": "Volcengine TTS",
        "base_url": "https://openspeech.bytedance.com/api/v1/tts", "protocol": "volc_tts",
        "site": "https://console.volcengine.com/speech",
        "key_hint": "AppID:AccessToken（控制台 → 语音技术 → 应用管理）",
        "note": "中文音色自然，国内直连，长辈配音首选；M4/M5/F4/F5 为大模型音色，需开通「大模型语音合成」",
        "models": [
            {"id": "doubao-tts", "name": "豆包语音合成（推荐）", "tags": ["推荐"]},
            {"id": "doubao-tts-hd", "name": "豆包语音合成（高清）", "tags": []},
        ],
        "voices": [
            {"id": "BV001_streaming", "name": "F1 · 通用女声", "gender": "F"},
            {"id": "BV002_streaming", "name": "M1 · 通用男声", "gender": "M"},
            {"id": "BV701_streaming", "name": "F2 · 播报女声", "gender": "F"},
            {"id": "BV700_streaming", "name": "M2 · 播报男声", "gender": "M"},
            {"id": "BV005_streaming", "name": "F3 · 甜美女声", "gender": "F"},
            {"id": "BV003_streaming", "name": "M3 · 逍遥男声", "gender": "M"},
            {"id": "zh_female_cancan_mars_bigtts", "name": "F4 · 灿灿（大模型）", "gender": "F"},
            {"id": "zh_female_shuangkuaisisi_mars_bigtts", "name": "F5 · 思思（大模型）", "gender": "F"},
            {"id": "zh_male_jingqiangkanye_mars_bigtts", "name": "M4 · 京腔侃爷（大模型）", "gender": "M"},
            {"id": "zh_male_beijingxiaoye_mars_bigtts", "name": "M5 · 北京小爷（大模型）", "gender": "M"},
        ],
    },
    "openai": {
        "id": "openai", "name": "GPT · OpenAI 语音", "name_en": "OpenAI TTS",
        "base_url": "https://api.openai.com/v1", "protocol": "openai_tts",
        "site": "https://platform.openai.com", "key_hint": "sk- 开头",
        "note": "gpt-4o-mini-tts 最新模型，音色可用一句话调语气；海外服务，国内需网络条件",
        "models": [
            {"id": "gpt-4o-mini-tts", "name": "GPT-4o mini TTS（最新·推荐）", "tags": ["推荐"]},
            {"id": "tts-1", "name": "tts-1（经典·快）", "tags": []},
            {"id": "tts-1-hd", "name": "tts-1-hd（高保真）", "tags": []},
        ],
        "voices": [
            {"id": "nova", "name": "F1 · Nova 活力女声", "gender": "F"},
            {"id": "shimmer", "name": "F2 · Shimmer 柔和女声", "gender": "F"},
            {"id": "coral", "name": "F3 · Coral 温暖女声", "gender": "F"},
            {"id": "sage", "name": "F4 · Sage 沉稳女声", "gender": "F"},
            {"id": "alloy", "name": "F5 · Alloy 中性声", "gender": "F"},
            {"id": "onyx", "name": "M1 · Onyx 深沉男声", "gender": "M"},
            {"id": "echo", "name": "M2 · Echo 沉稳男声", "gender": "M"},
            {"id": "ash", "name": "M3 · Ash 温和男声", "gender": "M"},
            {"id": "fable", "name": "M4 · Fable 叙事男声", "gender": "M"},
            {"id": "ballad", "name": "M5 · Ballad 抒情男声", "gender": "M"},
        ],
    },
    "custom": {
        "id": "custom", "name": "自定义（OpenAI 兼容 /audio/speech）", "name_en": "Custom TTS",
        "base_url": "", "protocol": "openai_tts",
        "site": "",
        "key_hint": "该服务的 API Key（请求地址单独填）",
        "note": "任何 OpenAI 兼容 TTS：硅基流动 CosyVoice、MiniMax 兼容位、公司内网网关等；保存后在下方填请求地址",
        "models": [
            {"id": "FunAudioLLM/CosyVoice2-0.5B", "name": "CosyVoice2（硅基流动示例）", "tags": ["示例"]},
        ],
        "voices": [
            {"id": "default", "name": "默认音色（按服务商填）", "gender": "F"},
        ],
    },
}

# ============================================================
# 四、图片生成（GPT 最新 gpt-image 系列 / 火山豆包 Seedream / OpenAI 兼容自定义）
# ============================================================
IMAGE_PROVIDERS = {
    "openai": {
        "id": "openai", "name": "GPT 云端生图", "name_en": "OpenAI Images",
        "base_url": "https://api.openai.com/v1", "protocol": "openai_images",
        "site": "https://platform.openai.com", "key_hint": "sk- 开头",
        "note": "GPT 最新 gpt-image-2.5 系列，与文字模型同用一个 OpenAI Key；海外服务，国内直连需网络条件（可用 OpenAI 兼容中转地址）",
        "models": [
            {"id": "gpt-image-2.5-flare", "name": "gpt-image-2.5-flare（最新·快·推荐）", "tags": ["推荐", "最新"]},
            {"id": "gpt-image-2.5-sunburst", "name": "gpt-image-2.5-sunburst（精绘/编辑）", "tags": ["最新"]},
            {"id": "gpt-image-1.5", "name": "gpt-image-1.5（上一代均衡）", "tags": []},
            {"id": "gpt-image-1", "name": "gpt-image-1（经典稳定）", "tags": []},
        ],
    },
    "doubao": {
        "id": "doubao", "name": "火山引擎 · 豆包生图", "name_en": "Doubao Seedream",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3", "protocol": "openai_images",
        "site": "https://console.volcengine.com/ark",
        "key_hint": "火山方舟 API Key（与豆包聊天/看图同一个 Key）",
        "note": "国内直连、便宜好看；Seedream 系列文生图，模型名也可填方舟的「接入点ID」",
        "models": [
            {"id": "doubao-seedream-4-0", "name": "Seedream 4.0（推荐）", "tags": ["推荐"]},
            {"id": "doubao-seedream-3-0-t2i", "name": "Seedream 3.0 文生图", "tags": []},
        ],
    },
    "custom": {
        "id": "custom", "name": "自定义（OpenAI 兼容 /images/generations）", "name_en": "Custom Images",
        "base_url": "", "protocol": "openai_images",
        "site": "",
        "key_hint": "该服务的 API Key（请求地址单独填）",
        "note": "任何 OpenAI 兼容图片网关/中转：请求地址可填 …/v1 或完整 …/images/generations 端点（原样使用，不改根地址）；模型名按你的网关实际支持自由填写，不限于下面示例",
        "models": [
            {"id": "gpt-image-2.5-flare", "name": "gpt-image-2.5-flare（示例，可自填其它模型）", "tags": ["示例"]},
        ],
    },
}

# ============================================================
# 工具函数（config 与 api 层共用）
# ============================================================

# 厂商别名：用户说 Claude，目录 id 是 anthropic；说 GPT 也容错指向 openai
PROVIDER_ALIASES = {"claude": "anthropic", "gpt": "openai", "gemini": "gemini"}


def normalize_pid(pid: str) -> str:
    """厂商ID 规范化：接受常见别名（claude→anthropic、gpt→openai）"""
    p = (pid or "").strip().lower()
    return PROVIDER_ALIASES.get(p, p)


def get_catalog(section: str) -> dict:
    """按能力取目录：llm / vision / tts / image"""
    return {"llm": LLM_PROVIDERS, "vision": VISION_PROVIDERS,
            "tts": TTS_PROVIDERS, "image": IMAGE_PROVIDERS}[section]




def default_model(p: dict) -> str:
    """厂商默认模型 = 目录里第一个（推荐位）"""
    return p["models"][0]["id"] if p.get("models") else ""


def public_card(p: dict) -> dict:
    """输出给前端的目录卡片（不含任何密钥，纯公开信息）"""
    return {
        "id": p["id"], "name": p["name"], "name_en": p.get("name_en", ""),
        "base_url": p["base_url"], "protocol": p["protocol"],
        "site": p.get("site", ""), "key_hint": p.get("key_hint", ""),
        "note": p.get("note", ""),
        "models": p.get("models", []),
        "voices": p.get("voices", []),
    }