"""
오케스트레이터 핵심 로직
- 에이전트들에게 Task 분배
- 토론 진행 (다중 라운드)
- 결과 취합 및 보고서 생성
"""
import asyncio
import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

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
        client = A2AClient(http_client, url=agent.url)
        response = await client.send_message(
            SendMessageRequest(
                id=str(uuid.uuid4()),
                params=MessageSendParams(message=_make_message(prompt)),
            )
        )
        # response 파싱: 다양한 응답 구조 처리
        result = getattr(response, "result", response)

        # Message 직접 반환 (parts가 있는 경우)
        if hasattr(result, "parts") and result.parts:
            text = _extract_text(result)
            if text:
                return text

        # Task 형태 (status.message에 텍스트)
        status = getattr(result, "status", None)
        if status:
            msg = getattr(status, "message", None)
            if msg and hasattr(msg, "parts"):
                text = _extract_text(msg)
                if text:
                    return text

        # history에서 마지막 메시지 추출
        history = getattr(result, "history", None)
        if history:
            for h in reversed(history):
                if hasattr(h, "parts"):
                    text = _extract_text(h)
                    if text:
                        return text

        # artifacts에서 추출
        artifacts = getattr(result, "artifacts", None)
        if artifacts:
            for a in artifacts:
                if hasattr(a, "parts"):
                    text = _extract_text(a)
                    if text:
                        return text

        return f"[{agent.name}] 응답 파싱 실패: {str(response)[:200]}"
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


async def select_agents_for_topic(
    agents: List[AgentInfo],
    topic: str,
    min_agents: int = 1,
) -> List[AgentInfo]:
    """주제에 가장 적합한 에이전트를 Claude로 선별합니다."""
    # 스킬이 정의된 에이전트가 없으면 전체 반환
    if not any(a.skills for a in agents):
        return agents

    agents_desc = "\n".join(
        f'- name: "{a.name}", description: "{a.description}", skills: {a.skills}'
        for a in agents
    )
    prompt = (
        f"다음 주제와 에이전트 목록을 보고, 주제에 가장 적합한 에이전트를 선택하세요.\n\n"
        f"주제: {topic}\n\n"
        f"에이전트 목록:\n{agents_desc}\n\n"
        f"반드시 JSON 배열로만 응답하세요. 에이전트 이름만 포함합니다.\n"
        f'예시: ["agent-a", "agent-b"]\n'
        f"적합한 에이전트가 없으면 모든 에이전트를 포함하세요."
    )

    try:
        response = await synthesize_with_claude(prompt)
        # JSON 배열 추출
        match = re.search(r'\[.*?\]', response, re.DOTALL)
        if match:
            selected_names = json.loads(match.group())
            selected = [a for a in agents if a.name in selected_names]
            if len(selected) >= min_agents:
                print(f"  스킬 매칭 결과: {[a.name for a in selected]}")
                return selected
    except Exception as e:
        print(f"  스킬 매칭 실패 (전체 에이전트 사용): {e}")

    return agents


async def run_debate_streaming(
    config: OrchestratorConfig,
    topic: str,
    event_callback,
):
    """
    스트리밍 토론. event_callback(event_type, data_dict)를 호출하여 진행 상황을 전달합니다.
    단일 에이전트면 바로 답변, 2개 이상이면 토론.
    """
    async with httpx.AsyncClient(timeout=120.0) as http_client:
        agents = config.registered_agents
        if any(a.skills for a in agents):
            await event_callback("status", {"phase": "skill_matching", "message": "주제에 적합한 에이전트 선별 중..."})
            agents = await select_agents_for_topic(agents, topic)
        if not agents:
            await event_callback("error", {"message": "등록된 에이전트가 없습니다."})
            return

        # 단일 에이전트: 바로 답변
        if len(agents) == 1:
            agent = agents[0]
            await event_callback("status", {"phase": "single", "message": f"{agent.name}에게 질문 중..."})
            response = await call_agent(http_client, agent, topic)
            await event_callback("single_response", {"agent": agent.name, "response": response})
            await event_callback("status", {"phase": "complete", "message": "완료"})
            return

        # 토론 모드
        await event_callback("status", {
            "phase": "start",
            "message": f"토론 시작 - 에이전트 {len(agents)}개 참여: {', '.join(a.name for a in agents)}",
        })

        history = []

        # 라운드 0: 초기 의견
        await event_callback("status", {"phase": "round", "message": "라운드 0: 초기 의견 수집 중..."})
        for agent in agents:
            response = await call_agent(http_client, agent, topic)
            await event_callback("opinion", {"agent": agent.name, "round": 0, "opinion": response})
            history.append({"agent": agent.name, "round": 0, "opinion": response})

        prev_opinions = {h["agent"]: h["opinion"] for h in history if h["round"] == 0}

        # 라운드 1~N
        for round_num in range(1, config.debate_rounds + 1):
            await event_callback("status", {"phase": "round", "message": f"라운드 {round_num}: 토론 진행 중..."})
            round_opinions = {}
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
                response = await call_agent(http_client, agent, prompt)
                await event_callback("opinion", {"agent": agent.name, "round": round_num, "opinion": response})
                round_opinions[agent.name] = response
            prev_opinions = round_opinions

        # 보고서 생성
        await event_callback("status", {"phase": "synthesizing", "message": "Claude가 최종 보고서 작성 중..."})

        history_text = ""
        all_opinions = {0: {h["agent"]: h["opinion"] for h in history if h["round"] == 0}}
        for r in range(1, config.debate_rounds + 1):
            all_opinions[r] = {}
        # rebuild from callbacks - use prev_opinions trail
        # Simpler: just build from what we have
        history_text += "\n## 초기 의견\n"
        for h in history:
            if h["round"] == 0:
                history_text += f"**{h['agent']}**: {h['opinion']}\n\n"

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

        await event_callback("report", {"report": report, "report_path": str(report_path)})
        await event_callback("status", {"phase": "complete", "message": "토론 완료"})


async def run_single_query(
    http_client: httpx.AsyncClient,
    agent: AgentInfo,
    topic: str,
) -> Dict:
    """단일 에이전트에게 바로 질문하고 답변을 반환합니다."""
    print(f"\n{'='*60}")
    print(f"단일 에이전트 질문: {topic}")
    print(f"담당 에이전트: {agent.name}")
    if agent.skills:
        print(f"스킬: {agent.skills}")
    if agent.data_paths:
        print(f"데이터 경로: {agent.data_paths}")
    if agent.mcp_servers:
        print(f"MCP 서버: {agent.mcp_servers}")
    print(f"{'='*60}\n")

    response = await call_agent(http_client, agent, topic)

    # 결과 저장
    output_dir = Path("./reports")
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = output_dir / f"query_{timestamp}.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(f"# 질문: {topic}\n\n")
        f.write(f"**생성일시**: {datetime.now().isoformat()}\n\n")
        f.write(f"**담당 에이전트**: {agent.name}\n\n")
        f.write("---\n\n")
        f.write(response)

    print(f"응답 저장 완료: {report_path}")
    return {
        "topic": topic,
        "mode": "single",
        "agent": agent.name,
        "response": response,
        "report_path": str(report_path),
    }


async def run_debate(
    config: OrchestratorConfig,
    topic: str,
    select_by_skill: bool = True,
) -> Dict:
    """
    에이전트 수에 따라 자동으로 모드를 결정합니다.
    - 1개: 바로 답변 (토론 없음)
    - 2개+: 토론 후 보고서 생성
    """
    history = []

    async with httpx.AsyncClient(timeout=120.0) as http_client:
        agents = config.registered_agents
        if select_by_skill and any(a.skills for a in agents):
            print("[스킬 매칭] 주제에 적합한 에이전트 선별 중...")
            agents = await select_agents_for_topic(agents, topic)
        if not agents:
            return {"error": "등록된 에이전트가 없습니다."}

        # 단일 에이전트: 토론 없이 바로 답변
        if len(agents) == 1:
            print("[단일 에이전트 모드] 토론 없이 바로 답변합니다.")
            return await run_single_query(http_client, agents[0], topic)

        # 2개 이상: 토론 모드
        print(f"\n{'='*60}")
        print(f"[토론 모드] 에이전트 {len(agents)}개 참여")
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
            "mode": "debate",
            "agents": [a.name for a in agents],
            "rounds": len(history),
            "report": report,
            "report_path": str(report_path),
            "history": history,
        }
