"""
LLM 프로바이더 추상화 레이어
- Claude Code (구독 기반, claude-agent-sdk)
- Claude API (API 키 기반, anthropic SDK)
- OpenAI API (API 키 기반, openai SDK)

환경변수:
  AGENT_PROVIDER: claude-code | claude-api | openai (기본: claude-code)
  ANTHROPIC_API_KEY: Claude API 사용 시 필요
  OPENAI_API_KEY: OpenAI API 사용 시 필요
  LLM_MODEL: 모델명 오버라이드 (선택)
"""
import asyncio
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional


class LLMProvider(ABC):
    """LLM 프로바이더 베이스 클래스"""

    name: str = "unknown"

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        cwd: Optional[str] = None,
        allowed_tools: Optional[list] = None,
        max_turns: int = 10,
    ) -> str:
        """프롬프트를 처리하고 결과 텍스트를 반환합니다."""
        ...

    @abstractmethod
    async def synthesize(self, prompt: str, timeout: float = 120.0) -> str:
        """도구 없이 텍스트 합성만 수행합니다. (오케스트레이터 보고서 생성용)"""
        ...


class ClaudeCodeProvider(LLMProvider):
    """Claude Code 구독 기반 프로바이더 (claude-agent-sdk)"""

    name = "claude-code"

    async def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        cwd: Optional[str] = None,
        allowed_tools: Optional[list] = None,
        max_turns: int = 10,
    ) -> str:
        from claude_agent_sdk import (
            query,
            ClaudeAgentOptions,
            ResultMessage,
            CLINotFoundError,
            CLIConnectionError,
        )

        options = ClaudeAgentOptions(
            cwd=cwd or ".",
            allowed_tools=allowed_tools or [],
            system_prompt=system_prompt,
            max_turns=max_turns,
        )

        try:
            result_text = ""
            async for message in query(prompt=prompt, options=options):
                if isinstance(message, ResultMessage):
                    result_text = message.result
                    break
            return result_text or "(응답 없음)"
        except CLINotFoundError:
            return (
                "[오류] Claude Code CLI가 설치되어 있지 않습니다.\n"
                "설치: npm install -g @anthropic-ai/claude-code\n"
                "로그인: claude"
            )
        except CLIConnectionError as e:
            return f"[오류] Claude Code 연결 실패: {e}"
        except Exception as e:
            return f"[오류] Claude Code 처리 중 예외: {e}"

    async def synthesize(self, prompt: str, timeout: float = 120.0) -> str:
        from claude_agent_sdk import query, ClaudeAgentOptions, ResultMessage

        async def _run():
            result_text = ""
            async for message in query(
                prompt=prompt,
                options=ClaudeAgentOptions(allowed_tools=[]),
            ):
                if isinstance(message, ResultMessage):
                    result_text = message.result
                    break
            return result_text or "(합성 실패)"

        try:
            return await asyncio.wait_for(_run(), timeout=timeout)
        except asyncio.TimeoutError:
            return f"(Claude Code 합성 타임아웃 - {timeout}초)"
        except Exception as e:
            return f"(Claude Code 합성 오류: {e})"


class ClaudeAPIProvider(LLMProvider):
    """Claude API 키 기반 프로바이더 (anthropic SDK)"""

    name = "claude-api"

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.model = model or os.environ.get("LLM_MODEL", "claude-sonnet-4-20250514")

    def _get_client(self):
        try:
            import anthropic
        except ImportError:
            raise ImportError(
                "anthropic 패키지가 필요합니다: pip install anthropic"
            )
        return anthropic.AsyncAnthropic(api_key=self.api_key)

    async def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        cwd: Optional[str] = None,
        allowed_tools: Optional[list] = None,
        max_turns: int = 10,
    ) -> str:
        try:
            client = self._get_client()
            messages = [{"role": "user", "content": prompt}]
            kwargs = {"model": self.model, "max_tokens": 8192, "messages": messages}
            if system_prompt:
                kwargs["system"] = system_prompt

            response = await client.messages.create(**kwargs)
            return response.content[0].text if response.content else "(응답 없음)"
        except ImportError as e:
            return f"[오류] {e}"
        except Exception as e:
            return f"[오류] Claude API 처리 중 예외: {e}"

    async def synthesize(self, prompt: str, timeout: float = 120.0) -> str:
        try:
            client = self._get_client()
            response = await asyncio.wait_for(
                client.messages.create(
                    model=self.model,
                    max_tokens=8192,
                    messages=[{"role": "user", "content": prompt}],
                ),
                timeout=timeout,
            )
            return response.content[0].text if response.content else "(합성 실패)"
        except asyncio.TimeoutError:
            return f"(Claude API 합성 타임아웃 - {timeout}초)"
        except Exception as e:
            return f"(Claude API 합성 오류: {e})"


class OpenAIProvider(LLMProvider):
    """OpenAI API 프로바이더 (openai SDK) — GPT, Codex 등"""

    name = "openai"

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.model = model or os.environ.get("LLM_MODEL", "gpt-4o")

    def _get_client(self):
        try:
            import openai
        except ImportError:
            raise ImportError(
                "openai 패키지가 필요합니다: pip install openai"
            )
        return openai.AsyncOpenAI(api_key=self.api_key)

    async def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        cwd: Optional[str] = None,
        allowed_tools: Optional[list] = None,
        max_turns: int = 10,
    ) -> str:
        try:
            client = self._get_client()
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            response = await client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=8192,
            )
            return response.choices[0].message.content or "(응답 없음)"
        except ImportError as e:
            return f"[오류] {e}"
        except Exception as e:
            return f"[오류] OpenAI 처리 중 예외: {e}"

    async def synthesize(self, prompt: str, timeout: float = 120.0) -> str:
        try:
            client = self._get_client()
            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=8192,
                ),
                timeout=timeout,
            )
            return response.choices[0].message.content or "(합성 실패)"
        except asyncio.TimeoutError:
            return f"(OpenAI 합성 타임아웃 - {timeout}초)"
        except Exception as e:
            return f"(OpenAI 합성 오류: {e})"


# --- 프로바이더 팩토리 ---

PROVIDERS = {
    "claude-code": ClaudeCodeProvider,
    "claude-api": ClaudeAPIProvider,
    "openai": OpenAIProvider,
}


def create_provider(provider_name: str = "claude-code", **kwargs) -> LLMProvider:
    """프로바이더 이름으로 인스턴스를 생성합니다."""
    provider_cls = PROVIDERS.get(provider_name)
    if not provider_cls:
        raise ValueError(
            f"알 수 없는 프로바이더: {provider_name}. "
            f"지원: {', '.join(PROVIDERS.keys())}"
        )
    return provider_cls(**kwargs)
