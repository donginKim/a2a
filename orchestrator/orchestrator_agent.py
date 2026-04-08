"""
오케스트레이터 핵심 로직
- 에이전트들에게 Task 분배
- 토론 진행 (다중 라운드)
- 결과 취합 및 보고서 생성
"""
import asyncio
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

import httpx
from a2a.client import A2AClient
from a2a.types import (
    Message,
    Part,
    Role,
    SendMessageRequest,
    MessageSendParams,
    TextPart,
)

from claude_agent_sdk import query, ClaudeAgentOptions, ResultMessage
from config import OrchestratorConfig, AgentInfo


def _make_message(text: str) -> Message:
    return Message(
        messageId=str(uuid.uuid4()),
        role=Role.user,
        parts=[Part(root=TextPart(text=text))],
    )


def _extract_text(message: Message) -> str:
    parts = []
    for part in message.parts:
        root = getattr(part, "root", part)
        if hasattr(root, "text"):
            parts.append(root.text)
    return "\n".join(parts)


async def call_agent(
    http_client: httpx.AsyncClient,
    agent: AgentInfo,
    prompt: str,
    timeout: float = 120.0,
) -> str:
    """단일 에이전트에게 Task를 보내고 결과를 반환합니다."""
    try:
        client = await A2AClient.get_client_from_agent_card_url(
            http_client, agent.url
        )
        response = await client.send_message(
            SendMessageRequest(
                id=str(uuid.uuid4()),
                params=MessageSendParams(message=_make_message(prompt)),
            )
        )
        # response는 Task 또는 Message 형태
        if hasattr(response, "result"):
            result = response.result
            if hasattr(result, "status") and hasattr(result.status, "message"):
                msg = result.status.message
                if msg:
                    return _extract_text(msg)
            if hasattr(result, "parts"):
                return _extract_text(result)
        return str(response)
    except Exception as e:
        return f"[{agent.name} 오류] {str(e)}"


async def gather_opinions(
    http_client: httpx.AsyncClient,
    agents: List[AgentInfo],
    topic: str,
    context: str = "",
) -> Dict[str, str]:
    """모든 에이전트로부터 의견을 동시에 수집합니다."""
    prompt = topic
    if context:
        prompt = f"{context}\n\n위 맥락을 참고하여 다음 주제에 대한 의견을 제시해주세요:\n{topic}"

    tasks = [call_agent(http_client, agent, prompt) for agent in agents]
    results = await asyncio.gather(*tasks)
    return {agents[i].name: results[i] for i in range(len(agents))}


async def synthesize_with_claude(prompt: str) -> str:
    """Claude Agent SDK로 내용을 합성합니다."""
    result_text = ""
    async for message in query(
        prompt=prompt,
        options=ClaudeAgentOptions(allowed_tools=[]),
    ):
        if isinstance(message, ResultMessage):
            result_text = message.result
            break
    return result_text or "(합성 실패)"


async def run_debate(
    config: OrchestratorConfig,
    topic: str,
) -> Dict:
    """
    토론을 진행하고 최종 보고서를 반환합니다.

    흐름:
    1. 각 에이전트에게 초기 의견 요청
    2. N라운드 토론 (상대 의견 보여주고 반론 요청)
    3. Claude가 전체 토론 취합 후 보고서 생성
    """
    history = []

    async with httpx.AsyncClient(timeout=120.0) as http_client:
        agents = config.registered_agents
        if not agents:
            return {"error": "등록된 에이전트가 없습니다. agents.json을 확인하세요."}

        print(f"\n{'='*60}")
        print(f"토론 주제: {topic}")
        print(f"참여 에이전트: {[a.name for a in agents]}")
        print(f"{'='*60}\n")

        # 라운드 0: 초기 의견 수집
        print("[라운드 0] 초기 의견 수집 중...")
        initial_opinions = await gather_opinions(http_client, agents, topic)
        history.append({"round": 0, "type": "initial", "opinions": initial_opinions})
        for name, opinion in initial_opinions.items():
            print(f"  [{name}]: {opinion[:100]}...")

        # 라운드 1~N: 토론
        for round_num in range(1, config.debate_rounds + 1):
            print(f"\n[라운드 {round_num}] 토론 진행 중...")
            prev_opinions = history[-1]["opinions"]

            # 다른 에이전트 의견을 컨텍스트로 구성
            debate_opinions = {}
            tasks = []
            for agent in agents:
                others_context = "\n".join(
                    f"- {name}: {opinion}"
                    for name, opinion in prev_opinions.items()
                    if name != agent.name
                )
                prompt = (
                    f"주제: {topic}\n\n"
                    f"다른 참여자들의 의견:\n{others_context}\n\n"
                    f"위 의견들을 참고하여 당신의 심화된 견해를 제시해주세요. "
                    f"동의하는 부분과 다른 관점이 있다면 구체적으로 설명해주세요."
                )
                tasks.append(call_agent(http_client, agent, prompt))

            results = await asyncio.gather(*tasks)
            for i, agent in enumerate(agents):
                debate_opinions[agent.name] = results[i]
                print(f"  [{agent.name}]: {results[i][:100]}...")

            history.append({"round": round_num, "type": "debate", "opinions": debate_opinions})

        # 최종 보고서 생성
        print("\n[보고서] Claude로 최종 보고서 작성 중...")
        history_text = ""
        for h in history:
            round_label = "초기 의견" if h["round"] == 0 else f"라운드 {h['round']}"
            history_text += f"\n## {round_label}\n"
            for name, opinion in h["opinions"].items():
                history_text += f"**{name}**: {opinion}\n\n"

        report_prompt = (
            f"다음은 '{topic}'에 대한 멀티 에이전트 토론 내용입니다.\n\n"
            f"{history_text}\n\n"
            f"위 토론 내용을 바탕으로 다음 구조의 보고서를 작성해주세요:\n"
            f"1. 핵심 요약\n"
            f"2. 주요 합의 사항\n"
            f"3. 쟁점 및 다양한 관점\n"
            f"4. 결론 및 권고사항\n"
        )

        report = await synthesize_with_claude(report_prompt)

        # 보고서 저장
        output_dir = Path(config.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = output_dir / f"report_{timestamp}.md"
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(f"# 토론 보고서: {topic}\n\n")
            f.write(f"**생성일시**: {datetime.now().isoformat()}\n\n")
            f.write(f"**참여 에이전트**: {', '.join(a.name for a in agents)}\n\n")
            f.write("---\n\n")
            f.write(report)

        print(f"\n보고서 저장 완료: {report_path}")
        return {
            "topic": topic,
            "agents": [a.name for a in agents],
            "rounds": len(history),
            "report": report,
            "report_path": str(report_path),
            "history": history,
        }
