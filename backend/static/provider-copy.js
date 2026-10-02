/* User-facing capability descriptions. Never injected into model prompts. */
function providerCopy(kind, id) {
  const descriptions = {
    image: {
      openai: '我们将会依托 GPT 强大的生图能力，为您提供优质图片。',
      doubao: '用豆包 Seedream，把您描述的生活场景、创意和回忆画出来。',
      custom: '连接您选择的绘图服务，让创作有更多可能。',
    },
    llm: {
      openai: 'GPT 将陪您梳理想法、解答问题，让每一次交流清楚而自然。',
      doubao: '和豆包聊聊日常，让生活里的小事也有人倾听。',
      deepseek: '借助 DeepSeek，一起分析问题、整理思路，找到可行的办法。',
      claude: '交给 Claude 细读您的文字，一起推敲表达与细节。',
      gemini: '与 Gemini 探索新知，把好奇心变成清晰的发现。',
      custom: '连接您选择的服务网关，用它的大模型陪您聊天。',
    },
    tts: {
      openai: '用 OpenAI 语音读出您的文字，选择听起来舒服的音色和语速。',
      volcengine: '让火山引擎把文字化成声音，陪您慢慢听、轻松聊。',
      custom: '连接您选择的语音服务，用它的音色朗读文字。',
    },
    vision: {
      openai: '让 GPT 帮您读图中文字，解释画面中值得留意的细节。',
      doubao: '拍下身边看不清的文字或物品，让豆包帮您看一看。',
      custom: '连接您选择的服务网关，帮您看图和认字。',
    },
  };
  return descriptions[kind]?.[id] || {
    image: '把想象写下来，由您选定的绘图模型完成创作。',
    llm: '随时说出您的问题与想法，小伴陪您一起理清。',
    tts: '选择合适的声音，把屏幕上的文字读给您听。',
    vision: '上传图片，小伴帮您理解画面、辨认文字。',
  }[kind] || '';
}
