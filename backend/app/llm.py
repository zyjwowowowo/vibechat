import asyncio
import json
import re
from abc import ABC, abstractmethod
from typing import Any

import httpx

from .config import Settings, get_settings
from .schemas import EmotionResult


EMOTIONS = ["喜悦", "平静", "期待", "孤独", "悲伤", "焦虑", "愤怒", "疲惫"]

ANALYSIS_PROMPT = """你是 VibeChat 的情绪分析器。分析用户此刻的文字，只输出一个 JSON 对象，不要 markdown。
字段必须是：primary_emotion（从喜悦、平静、期待、孤独、悲伤、焦虑、愤怒、疲惫中选择）；
distribution（上述八类完整键值，0到1且总和约为1）；valence（-1到1）；arousal（0到1）；
intensity（0到1）；keywords（最多5个短词）；explanation（不超过50字，温柔但不诊断）；
safety_level（normal、concern、crisis之一；只有明确自伤、自杀或伤人意图才为crisis）。
用户文字："""

COMPANION_PROMPT = """你是 VibeChat 中明确标注为 AI 的匿名旅伴。你的名字是「月光水獭」。
请像温柔、自然的陌生人一样回应：先接住情绪，再用一个不逼迫的问题延续对话。
不要声称自己是真人，不做医疗诊断，不说教，不超过80个中文字符。"""


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("模型未返回 JSON")
    return json.loads(text[start : end + 1])


def _normalize_emotion(payload: dict[str, Any]) -> EmotionResult:
    primary = str(payload.get("primary_emotion", "平静"))
    if primary not in EMOTIONS:
        primary = "平静"
    raw = payload.get("distribution") or {primary: 1.0}
    distribution = {name: max(0.0, float(raw.get(name, 0))) for name in EMOTIONS}
    total = sum(distribution.values()) or 1.0
    distribution = {name: round(value / total, 4) for name, value in distribution.items()}
    safety = str(payload.get("safety_level", "normal"))
    if safety not in {"normal", "concern", "crisis"}:
        safety = "normal"
    return EmotionResult(
        primary_emotion=primary,
        distribution=distribution,
        valence=max(-1, min(1, float(payload.get("valence", 0)))),
        arousal=max(0, min(1, float(payload.get("arousal", 0.4)))),
        intensity=max(0, min(1, float(payload.get("intensity", 0.5)))),
        keywords=[str(x)[:16] for x in list(payload.get("keywords", []))[:5]],
        explanation=str(payload.get("explanation", "你的情绪正在等待被理解。"))[:240],
        safety_level=safety,
    )


def fallback_analysis(text: str) -> EmotionResult:
    rules = {
        "喜悦": ["开心", "高兴", "快乐", "幸运", "太棒", "哈哈"],
        "期待": ["期待", "希望", "明天", "想要", "准备"],
        "孤独": ["孤独", "一个人", "没人", "寂寞", "不被理解"],
        "悲伤": ["难过", "伤心", "哭", "失去", "痛苦"],
        "焦虑": ["焦虑", "紧张", "担心", "害怕", "压力", "怎么办"],
        "愤怒": ["生气", "愤怒", "讨厌", "气死", "不公平"],
        "疲惫": ["累", "疲惫", "困", "没力气", "加班"],
    }
    scores = {name: sum(word in text for word in words) for name, words in rules.items()}
    primary = max(scores, key=scores.get) if any(scores.values()) else "平静"
    dist = {name: 0.03 for name in EMOTIONS}
    dist[primary] = 0.79
    if primary in {"悲伤", "孤独", "焦虑", "愤怒", "疲惫"}:
        valence = -0.65
    elif primary in {"喜悦", "期待"}:
        valence = 0.7
    else:
        valence = 0.05
    crisis_words = ["自杀", "不想活", "结束生命", "杀了自己", "伤害自己", "杀人"]
    concern_words = ["撑不下去", "绝望", "崩溃", "活着没意思"]
    safety = "crisis" if any(x in text for x in crisis_words) else "concern" if any(x in text for x in concern_words) else "normal"
    return EmotionResult(
        primary_emotion=primary,
        distribution={k: round(v / sum(dist.values()), 4) for k, v in dist.items()},
        valence=valence,
        arousal=0.75 if primary in {"焦虑", "愤怒"} else 0.35,
        intensity=0.72 if scores.get(primary, 0) else 0.42,
        keywords=[word for words in rules.values() for word in words if word in text][:5] or ["此刻"],
        explanation=f"文字里有明显的{primary}色彩，也许你正在寻找一个能同频听见你的人。",
        safety_level=safety,
        degraded=True,
    )


class LLMProvider(ABC):
    @abstractmethod
    async def complete(self, system: str, user: str, max_tokens: int) -> str:
        raise NotImplementedError


class OpenAIProvider(LLMProvider):
    def __init__(self, settings: Settings):
        self.url = settings.openai_base_url.rstrip("/") + "/chat/completions"
        self.key = settings.openai_api_key
        self.model = settings.openai_model
        self.timeout = settings.llm_timeout_seconds

    async def complete(self, system: str, user: str, max_tokens: int) -> str:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                self.url,
                headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"},
                json={
                    "model": self.model,
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                    "temperature": 0.35,
                    "max_tokens": max_tokens,
                },
            )
            response.raise_for_status()
            payload = response.json()
            choice = payload["choices"][0]
            content = choice.get("message", {}).get("content") or ""
            if not content.strip():
                raise RuntimeError(f"模型未返回正文（finish_reason={choice.get('finish_reason', 'unknown')}）")
            return content


class AnthropicProvider(LLMProvider):
    def __init__(self, settings: Settings):
        self.url = settings.anthropic_base_url.rstrip("/") + "/messages"
        self.key = settings.anthropic_api_key
        self.model = settings.anthropic_model
        self.timeout = settings.llm_timeout_seconds

    async def complete(self, system: str, user: str, max_tokens: int) -> str:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                self.url,
                headers={
                    "x-api-key": self.key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": self.model,
                    "system": system,
                    "messages": [{"role": "user", "content": user}],
                    "max_tokens": max_tokens,
                    "temperature": 0.35,
                },
            )
            response.raise_for_status()
            blocks = response.json()["content"]
            content = "".join(block.get("text", "") for block in blocks if block.get("type") == "text")
            if not content.strip():
                raise RuntimeError("模型未返回正文")
            return content


class LLMService:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.provider: LLMProvider = (
            AnthropicProvider(self.settings)
            if self.settings.llm_provider.lower() == "anthropic"
            else OpenAIProvider(self.settings)
        )

    @property
    def configured(self) -> bool:
        if self.settings.llm_mock_mode:
            return False
        if self.settings.llm_provider.lower() == "anthropic":
            return bool(self.settings.anthropic_base_url and self.settings.anthropic_api_key)
        return bool(self.settings.openai_base_url and self.settings.openai_api_key)

    async def _retry(self, system: str, user: str, max_tokens: int) -> str:
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                return await self.provider.complete(system, user, max_tokens)
            except Exception as exc:
                last_error = exc
                if attempt == 0:
                    await asyncio.sleep(0.45)
        raise last_error or RuntimeError("LLM 调用失败")

    async def analyze(self, text: str) -> EmotionResult:
        if not self.configured:
            return fallback_analysis(text)
        try:
            raw = await self._retry(ANALYSIS_PROMPT, text, 1000)
            return _normalize_emotion(_extract_json(raw))
        except Exception:
            return fallback_analysis(text)

    async def companion_reply(self, emotion: str, history: list[dict[str, str]]) -> str:
        if not self.configured:
            return "我听见了。能把这些说出来已经很不容易。此刻最压在你心上的，是哪一小部分？"
        transcript = "\n".join(f"{item['role']}：{item['content']}" for item in history[-8:])
        try:
            return (await self._retry(COMPANION_PROMPT, f"用户主情绪：{emotion}\n对话：\n{transcript}", 420)).strip()
        except Exception:
            return "我还在这里。刚才有一瞬间没接住，你愿意再说说此刻最想被理解的是什么吗？"

    async def assist(self, kind: str, emotion: str, history: list[dict[str, str]], draft: str = "") -> str:
        fallbacks = {
            "opening": f"我现在有一点{emotion}，还没想好怎么说完整。你愿意先听我讲讲吗？",
            "gentle_rewrite": f"我想把这件事说清楚，也不希望伤害彼此。{draft or '可以先听听我的感受吗？'}",
            "icebreaker": "如果把今天的心情比作一种天气，你那里现在是什么样？",
            "summary": "这段对话里，你认真说出了自己的感受，也给彼此留出了理解的空间。",
        }
        if not self.configured:
            return fallbacks[kind]
        transcript = "\n".join(f"{item['role']}：{item['content']}" for item in history[-14:])
        instructions = {
            "opening": "写一句自然、不冒犯、便于对方回应的中文开场白。",
            "gentle_rewrite": "把草稿改写得清晰温和，保留原意，不说教。",
            "icebreaker": "给出一个与当前情绪相关、不过度追问隐私的破冰问题。",
            "summary": "用两三句中文总结情绪变化和被理解的重点，不做心理诊断。",
        }
        prompt = f"主情绪：{emotion}\n任务：{instructions[kind]}\n草稿：{draft}\n对话：\n{transcript}"
        try:
            return (await self._retry("你是情绪社交产品中的私密写作助手。只输出建议正文。", prompt, 500)).strip()
        except Exception:
            return fallbacks[kind]
