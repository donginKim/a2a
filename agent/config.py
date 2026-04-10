"""
에이전트 설정 관리
"""
import os
from dataclasses import dataclass


@dataclass
class AgentConfig:
    # 서버 설정
    host: str = "0.0.0.0"
    port: int = 8001
    # 에이전트 정보
    name: str = "My Agent"
    description: str = "A2A 에이전트"
    # LLM 프로바이더 (claude-code | claude-api | openai)
    provider: str = "claude-code"
    # 오케스트레이터 URL (자동 등록용)
    orchestrator_url: str = "http://localhost:8000"
    # 이 에이전트의 공개 URL (Cloudflare tunnel URL)
    public_url: str = ""
    # 데이터 디렉토리 (에이전트가 접근할 로컬 파일)
    data_dir: str = "./data"
    # 허용할 도구 목록 (claude-code에서만 사용)
    allowed_tools: str = "Read,Glob,Grep"
    # 에이전트 스킬셋 (쉼표 구분)
    skills: str = "general,analysis"
    # 추가 데이터 경로 (쉼표 구분, 에이전트가 참고할 파일/폴더)
    data_paths: str = ""
    # MCP 서버 목록 (쉼표 구분)
    mcp_servers: str = ""


def load_config() -> AgentConfig:
    return AgentConfig(
        host=os.getenv("AGENT_HOST", "0.0.0.0"),
        port=int(os.getenv("AGENT_PORT", "8001")),
        name=os.getenv("AGENT_NAME", "My Agent"),
        description=os.getenv("AGENT_DESCRIPTION", "A2A 에이전트"),
        provider=os.getenv("AGENT_PROVIDER", "claude-code"),
        orchestrator_url=os.getenv("ORCHESTRATOR_URL", "http://localhost:8000"),
        public_url=os.getenv("AGENT_PUBLIC_URL", ""),
        data_dir=os.getenv("DATA_DIR", "./data"),
        allowed_tools=os.getenv("ALLOWED_TOOLS", "Read,Glob,Grep"),
        skills=os.getenv("AGENT_SKILLS", "general,analysis"),
        data_paths=os.getenv("AGENT_DATA_PATHS", ""),
        mcp_servers=os.getenv("AGENT_MCP_SERVERS", ""),
    )
