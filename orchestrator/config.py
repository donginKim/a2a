"""
Orchestrator 설정 관리
환경변수 또는 .env 파일에서 설정을 읽어옵니다.
"""
import os
import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict


@dataclass
class AgentInfo:
    name: str
    url: str
    description: str = ""


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


def load_config() -> OrchestratorConfig:
    cfg = OrchestratorConfig(
        host=os.getenv("ORCHESTRATOR_HOST", "0.0.0.0"),
        port=int(os.getenv("ORCHESTRATOR_PORT", "8000")),
        name=os.getenv("ORCHESTRATOR_NAME", "A2A Orchestrator"),
        debate_rounds=int(os.getenv("DEBATE_ROUNDS", "2")),
        output_dir=os.getenv("OUTPUT_DIR", "./reports"),
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
