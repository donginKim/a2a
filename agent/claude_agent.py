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
        f"로컬 데이터 디렉토리: {data_dir.resolve()}\n\n"
        f"## 필수 규칙\n"
        f"1. 질문에 답변하기 전에 반드시 데이터 디렉토리의 파일 목록을 먼저 확인하세요.\n"
        f"2. 관련 파일이 있으면 반드시 읽고 내용을 근거로 답변하세요.\n"
        f"3. 데이터에 기반한 답변은 출처(파일명)를 명시하세요.\n"
        f"4. 데이터에 없는 내용은 일반 지식으로 답변하되, 데이터 근거가 아님을 밝히세요.\n"
        f"5. 명확하고 구체적인 의견을 제시해주세요."
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
