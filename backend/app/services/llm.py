"""LLM provider 추상화 — 벤더 종속 없이 갈아끼우는 어댑터 계층.

현업 패턴: AI 기능을 특정 벤더(OpenAI/Gemini/로컬)에 묶지 않고
공통 인터페이스 뒤에 둔다. .env의 LLM_PROVIDER만 바꾸면 교체된다.

지원: gemini(클라우드 무료등급) · ollama(로컬) · rule(LLM 안 씀)
호출하는 쪽(ai_insight, chatbot)은 provider를 못 쓰면 규칙 기반으로 넘어간다.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

import httpx

from app.core.config import settings


class LLMProvider(ABC):
    name: str

    @abstractmethod
    def generate(self, prompt: str) -> str:
        """프롬프트 → 생성 텍스트. 실패 시 예외."""

    @abstractmethod
    def available(self) -> bool:
        """호출 가능한 설정인지(키 존재 등)."""


class GeminiProvider(LLMProvider):
    name = "gemini"

    def available(self) -> bool:
        return bool(settings.gemini_api_key)

    def generate(self, prompt: str) -> str:
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{settings.gemini_model}:generateContent")
        resp = httpx.post(
            url,
            params={"key": settings.gemini_api_key},
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()


class OllamaProvider(LLMProvider):
    name = "ollama"

    def available(self) -> bool:
        try:
            httpx.get(f"{settings.ollama_host}/api/tags", timeout=2)
            return True
        except httpx.HTTPError:
            return False

    def generate(self, prompt: str) -> str:
        resp = httpx.post(
            f"{settings.ollama_host}/api/generate",
            json={"model": settings.ollama_model, "prompt": prompt, "stream": False},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json().get("response", "").strip()


class RuleProvider(LLMProvider):
    """LLM을 안 쓰겠다고 지정한 경우(LLM_PROVIDER=rule).

    available()이 늘 False라서 호출하는 쪽이 바로 규칙 기반으로 넘어간다.
    이게 없으면 rule로 설정해도 Gemini로 폴백되는데, 키가 있으면 실제로
    호출까지 돼버려서 설정과 동작이 어긋난다.
    """
    name = "rule"

    def available(self) -> bool:
        return False

    def generate(self, prompt: str) -> str:
        raise RuntimeError("rule provider는 LLM을 호출하지 않는다")


_PROVIDERS = {"gemini": GeminiProvider, "ollama": OllamaProvider,
              "rule": RuleProvider}


def get_provider(name: str | None = None) -> LLMProvider:
    """설정된(또는 지정된) provider 인스턴스 반환."""
    key = (name or settings.llm_provider or "gemini").lower()
    cls = _PROVIDERS.get(key, GeminiProvider)
    return cls()
