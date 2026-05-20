# MindMarket YouTube Voice System

## Purpose

This is the reusable voice and script system for the Chinese YouTube channel:

**美股账户风控笔记**

The goal is to keep every video sounding like the same person and same channel:

- calm
- analytical
- direct
- not hype-driven
- risk-control first
- educational, not investment advice

Current voice reference:

- `docs/marketing/youtube/audio/2026-05-19/raw-user-voice-part1.m4a`
- `docs/marketing/youtube/audio/2026-05-19/enhanced-user-voice-part1.wav`
- `docs/marketing/youtube/audio/voice-pack/raw-user-voice-part1.m4a`
- `docs/marketing/youtube/audio/voice-pack/raw-user-voice-part2.m4a`
- `docs/marketing/youtube/audio/voice-pack/enhanced-user-voice-part1.wav`
- `docs/marketing/youtube/audio/voice-pack/enhanced-user-voice-part2.wav`
- `docs/marketing/youtube/audio/voice-pack/zhengdong-voice-reference-v1.wav`

Voice reference v1 duration: about 5 minutes 41 seconds after cleanup.

## Voice Direction

Use the user's real voice as the target style:

- Speak like explaining to a serious retail investor, not reading news.
- Avoid robotic word-by-word delivery.
- Use short sentences.
- Add natural pauses before key conclusions.
- Emphasize risk questions, not market predictions.
- Keep the tone professional but conversational.

## Pacing Rules

Use these marks in scripts:

- `【停顿】` pause 0.5-1.0 seconds
- `【放慢】` slow down for important explanation
- `【加重】` emphasize this phrase
- `【转折】` shift tone before reframing the point

Avoid long paragraphs. Break spoken copy every 1-3 sentences.

## Standard Opening

Use this intro for daily market-close videos:

```text
大家好，这里是美股账户风控笔记。

我是郑东。

这个频道不做荐股，也不预测明天哪只股票一定会涨。

我们每天用机构风控的视角，来看美股市场、宏观变化、保证金账户安全，以及个人投资组合风险。

今天我们重点看一个问题：

【停顿】
<当天核心问题>
```

Examples:

```text
今天我们重点看一个问题：
为什么今天美股指数看起来没大跌，但账户风险其实已经变了？
```

```text
今天我们重点看一个问题：
如果 Nasdaq 再跌 5% 到 10%，普通投资者的保证金账户会不会进入危险区？
```

## Short Opening Variant

Use this when the video needs to start faster:

```text
大家好，这里是美股账户风控笔记，我是郑东。

今天我们不猜明天涨跌。

我们只看一个更重要的问题：

【停顿】
<当天风险问题>
```

## Standard Closing

Use this ending for most videos:

```text
总结一下，今天真正重要的不是指数涨了多少、跌了多少。

而是市场背后的风险驱动有没有变化。

收益率、波动率、科技股、保证金空间、组合相关性，这些东西会一起影响你的账户安全。

【放慢】
所以收盘后，与其只问：
我今天赚了多少，亏了多少。

不如多问一句：
如果明天市场继续波动，我的账户能不能扛得住？

这里是美股账户风控笔记。

内容仅用于教育和研究，不构成投资建议。

我们明天继续用机构风控视角看市场。
```

## Product CTA Closing

Use this only 1-2 times per week, not every day:

```text
如果你也想用账户级别的方式看风险，
我正在做 MindMarket AI。

它不是荐股工具，
而是帮助个人投资者查看组合风险、压力测试、保证金安全边界和 AI 风险摘要。

网站是：
mindmarket.app

内容仅用于教育和研究，不构成投资建议。

我们明天继续用机构风控视角看市场。
```

## Daily Video Structure

Target length: 6.5-8 minutes.

1. Opening identity and risk question
2. Market snapshot
3. Macro driver
4. Portfolio risk interpretation
5. Margin / stress-test angle
6. Risk checklist
7. Optional MindMarket soft CTA
8. Standard closing

## Script Style Rules

Use:

- "我更关心的是..."
- "从风控角度看..."
- "这不是预测，而是账户安全问题。"
- "真正要问的不是这只股票明天涨不涨。"
- "而是如果市场继续波动，你的账户能不能扛得住。"

Avoid:

- "一定会涨"
- "必须买"
- "暴跌预警"
- "稳赚"
- "内幕"
- "散户必看"
- "错过后悔"

## Voice Clone Workflow

To generate future videos with the user's own voice:

1. Keep at least 10-20 minutes of clean voice samples.
2. Record in the same room and mic setup when possible.
3. Use a voice cloning provider such as Hyperframe / HeyGen / ElevenLabs if available.
4. Upload only the user's own authorized voice samples.
5. Generate narration from the script with the same pacing marks.
6. Review every generated voiceover before publishing.

The current v1 voice pack is enough to infer pacing style and write scripts. For a more stable voice clone, collect 10-20 minutes of clean speech in the same room and mic setup.

## Default Generation Policy

For every future video:

1. Use `zhengdong-voice-reference-v1.wav` as the voice style reference.
2. Write the script in short spoken paragraphs, not article-style prose.
3. Add pacing marks only where the delivery needs emphasis.
4. Keep the opening and closing consistent unless the user requests a different format.
5. If using Hyperframe or another AI voice tool, upload the voice reference pack and select the closest cloned voice before rendering.
6. If voice cloning is unavailable, ask the user to record narration; do not publish robotic system TTS.

## Hyperframe Voice Prompt

Use this style instruction when generating narration in Hyperframe:

```text
Use the uploaded Zhengdong voice reference. The narration should sound like a calm Chinese finance/risk-control host explaining market risk to retail investors. Keep the tone analytical, conversational, and natural. Avoid robotic word-by-word delivery. Use short pauses after important risk questions. Emphasize key phrases such as "从风控角度看", "账户级别风险", and "这不是投资建议". Do not sound like a sensational stock promoter.
```

## Recording Guidance

Record future samples like this:

- quiet room
- phone or mic 15-20 cm from mouth
- no background music
- no reverb-heavy room
- read naturally, not loudly
- pause after important sentences
- if a sentence is wrong, stop and repeat only that sentence
