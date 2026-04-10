"""
LLM 프로바이더 연동
- 설정된 프로바이더(claude-code, claude-api, openai)로 LLM 처리
- 로컬 데이터 파일에 접근 가능 (claude-code 모드)
"""
from pathlib import Path

from config import AgentConfig
from llm_provider import create_provider


async def process_with_claude(
    prompt: str,
    config: AgentConfig,
) -> str:
    """
    설정된 프로바이더로 프롬프트를 처리합니다.
    로컬 data_dir에 있는 파일에 접근할 수 있습니다 (claude-code 모드).
    """
    allowed = [t.strip() for t in config.allowed_tools.split(",") if t.strip()]
    data_dir = Path(config.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
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

    provider = create_provider(config.provider)
    return await provider.generate(
        prompt=prompt,
        system_prompt=system_prompt,
        cwd=data_path,
        allowed_tools=allowed,
        max_turns=10,
    )
