"""
Claude Agent SDK 연동
- Claude Code 구독 계정으로 LLM 처리
- 로컬 데이터 파일에 접근 가능
"""
import asyncio
from pathlib import Path
from typing import List

from claude_agent_sdk import query, ClaudeAgentOptions, ResultMessage, CLINotFoundError, CLIConnectionError

from config import AgentConfig


async def process_with_claude(
    prompt: str,
    config: AgentConfig,
) -> str:
    """
    Claude Agent SDK로 프롬프트를 처리합니다.
    로컬 data_dir에 있는 파일에 접근할 수 있습니다.
    """
    allowed = [t.strip() for t in config.allowed_tools.split(",") if t.strip()]
    data_dir = Path(config.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    # 데이터 디렉토리 정보를 시스템 프롬프트에 포함
    system_prompt = (
        f"당신은 '{config.name}' 에이전트입니다.\n"
        f"로컬 데이터 디렉토리: {data_dir.resolve()}\n"
        f"이 디렉토리의 파일들을 참고하여 답변할 수 있습니다.\n"
        f"명확하고 구체적인 의견을 제시해주세요."
    )

    try:
        result_text = ""
        async for message in query(
            prompt=prompt,
            options=ClaudeAgentOptions(
                cwd=str(data_dir.resolve()),
                allowed_tools=allowed,
                system_prompt=system_prompt,
                max_turns=10,
            ),
        ):
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
        return f"[오류] Claude Code 연결 실패: {str(e)}"
    except Exception as e:
        return f"[오류] 처리 중 예외 발생: {str(e)}"
