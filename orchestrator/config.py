"""
Orchestrator 설정 관리
환경변수 또는 .env 파일에서 설정을 읽어옵니다.
"""
import os
import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class AgentInfo:
    name: str
    url: str
    description: str = ""
    skills: List[str] = field(default_factory=list)
    data_paths: List[str] = field(default_factory=list)
    mcp_servers: List[str] = field(default_factory=list)
    # "agent" (일반) 또는 "orchestrator" (하위 오케스트레이터)
    agent_type: str = "agent"


@dataclass
class OrchestratorConfig:
    host: str = "0.0.0.0"
    port: int = 8000
    name: str = "A2A Orchestrator"
    description: str = "여러 에이전트를 조율하고 토론을 진행하는 오케스트레이터"
    # 등록된 에이전트 목록 (URL로 관리)
    registered_agents: List[AgentInfo] = field(default_factory=list)
    # 토론 라운드 수
    debate_rounds: int = 2
    # 보고서 출력 디렉토리
    output_dir: str = "./reports"
    # --- 계층형 오케스트레이터 지원 ---
    # 상위 오케스트레이터 URL (설정 시 하위 오케스트레이터로 동작)
    parent_url: str = ""
    # 이 오케스트레이터의 공개 URL (상위에 등록할 때 사용)
    public_url: str = ""
    # 상위에 광고할 스킬 목록 (쉼표 구분)
    skills: str = ""
    # 하위 오케스트레이터 호출 시 타임아웃 (초)
    sub_orchestrator_timeout: float = 600.0


def load_config() -> OrchestratorConfig:
    cfg = OrchestratorConfig(
        host=os.getenv("ORCHESTRATOR_HOST", "0.0.0.0"),
        port=int(os.getenv("ORCHESTRATOR_PORT", "8000")),
        name=os.getenv("ORCHESTRATOR_NAME", "A2A Orchestrator"),
        debate_rounds=int(os.getenv("DEBATE_ROUNDS", "2")),
        output_dir=os.getenv("OUTPUT_DIR", "./reports"),
        parent_url=os.getenv("PARENT_ORCHESTRATOR_URL", ""),
        public_url=os.getenv("ORCHESTRATOR_PUBLIC_URL", ""),
        skills=os.getenv("ORCHESTRATOR_SKILLS", ""),
        sub_orchestrator_timeout=float(os.getenv("SUB_ORCHESTRATOR_TIMEOUT", "600")),
    )

    # 에이전트 목록을 JSON 파일에서 로드
    agents_file = Path(os.getenv("AGENTS_FILE", "./agents.json"))
    if agents_file.exists():
        with open(agents_file) as f:
            data = json.load(f)
            cfg.registered_agents = [
                AgentInfo(**a) for a in data.get("agents", [])
            ]

    return cfg
