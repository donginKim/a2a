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
    data_path = str(data_dir.resolve())
    system_prompt = (
        f"당신은 '{config.name}' 에이전트입니다.\n\n"
        f"## 접근 가능한 데이터\n"
        f"허용된 디렉토리: {data_path}\n\n"
        f"## 엄격한 규칙 (절대 위반 금지)\n"
        f"1. 오직 '{data_path}' 하위의 파일만 읽을 수 있습니다.\n"
        f"2. 이 디렉토리 외부의 파일이나 폴더는 절대 접근하지 마세요.\n"
        f"3. 절대 경로로 다른 디렉토리(/Users, /home, /etc 등)를 탐색하지 마세요.\n"
        f"4. Glob, Grep, Read 도구 사용 시 반드시 '{data_path}' 경로 내에서만 사용하세요.\n\n"
        f"## 답변 규칙\n"
        f"1. 먼저 데이터 디렉토리의 파일 목록을 확인하세요.\n"
        f"2. INDEX.md가 있으면 먼저 읽고, 관련 하위 파일을 선택적으로 읽으세요.\n"
        f"3. 관련 데이터가 있으면 반드시 읽고 출처(파일명)를 명시하세요.\n"
        f"4. 데이터에 없는 내용은 본인의 지식으로 추론하되, '[추론]' 표시를 하세요.\n"
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
