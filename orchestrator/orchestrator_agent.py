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

from config import OrchestratorConfig, AgentInfo
from knowledge_store import KnowledgeStore
from llm_provider import create_provider, LLMProvider


_synthesizer: Optional[LLMProvider] = None


def _get_synthesizer() -> LLMProvider:
    """오케스트레이터 합성용 프로바이더를 반환합니다 (싱글톤).
    환경변수 ORCHESTRATOR_PROVIDER로 설정 가능 (기본: claude-code)"""
    global _synthesizer
    if _synthesizer is None:
        import os
        provider_name = os.environ.get("ORCHESTRATOR_PROVIDER", "claude-code")
        _synthesizer = create_provider(provider_name)
        print(f"[오케스트레이터] 합성 프로바이더: {_synthesizer.name}")
    return _synthesizer


async def normalize_topic(topic: str) -> Dict[str, any]:
    """Claude로 사용자 입력에서 정규화된 토픽과 검색 키워드를 추출합니다.

    반환:
        {
            "normalized": "API 게이트웨이 도입",
            "keywords": ["API", "게이트웨이", "마이크로서비스", "인프라"]
        }
    """
    prompt = (
        "다음 사용자 입력에서 핵심 토픽과 검색 키워드를 추출하세요.\n\n"
        f"사용자 입력: {topic}\n\n"
        "반드시 아래 JSON 형식으로만 응답하세요. 다른 텍스트 없이 JSON만:\n"
        "{\n"
        '  "normalized": "핵심 주제를 명사형으로 간결하게 (예: API 게이트웨이 도입)",\n'
        '  "keywords": ["관련", "키워드", "목록", "유의어포함"]\n'
        "}\n\n"
        "규칙:\n"
        "- normalized: 동일 주제는 항상 같은 문자열이 되도록 일관성 유지\n"
        "- keywords: 토픽과 관련된 핵심 단어 3~7개, 유의어/상위 개념 포함"
    )
    try:
        response = await synthesize_with_claude(prompt)
        match = re.search(r'\{.*?\}', response, re.DOTALL)
        if match:
            data = json.loads(match.group())
            return {
                "normalized": data.get("normalized", topic),
                "keywords": data.get("keywords", []),
            }
    except Exception as e:
        print(f"  토픽 정규화 실패 (원본 사용): {e}")
    return {"normalized": topic, "keywords": []}


async def extract_search_keywords(user_input: str) -> str:
    """Claude로 사용자 질문에서 지식 저장소 검색용 키워드를 추출합니다."""
    prompt = (
        "다음 사용자 입력에서 과거 토론 보고서를 검색할 키워드를 추출하세요.\n\n"
        f"사용자 입력: {user_input}\n\n"
        "반드시 검색에 사용할 키워드만 공백으로 구분하여 한 줄로 응답하세요.\n"
        "예시: 마이크로서비스 아키텍처 전환\n"
        "다른 설명이나 텍스트는 절대 포함하지 마세요."
    )
    try:
        response = await synthesize_with_claude(prompt)
        # 첫 줄만 사용 (불필요한 설명 제거)
        keywords = response.strip().split("\n")[0].strip()
        if keywords:
            return keywords
    except Exception:
        pass
    return user_input


async def _build_knowledge_context(store: KnowledgeStore, topic: str, max_reports: int = 3) -> str:
    """과거 관련 보고서를 검색하여 컨텍스트 문자열로 반환합니다.
    Claude로 검색 키워드를 추출한 뒤 FTS 검색하고, latest 버전만 반환합니다.
    """
    if not store:
        return ""

    # Claude로 검색 키워드 추출
    search_query = await extract_search_keywords(topic)
    print(f"  [지식 검색] 키워드: {search_query}")

    related = store.search_reports(search_query, limit=max_reports)
    if not related:
        return ""

    parts = ["## 과거 관련 토론 참고\n"]
    for r in related:
        date = r["created_at"][:10]
        agents = r.get("agents", "")
        version = r.get("version", 1)
        # 보고서 전문이 너무 길면 앞부분만
        summary = r["report"][:1500]
        if len(r["report"]) > 1500:
            summary += "\n... (이하 생략)"
        parts.append(
            f"### [{date}] {r['normalized_topic'] or r['topic']} (v{version})\n"
            f"참여: {agents}\n\n"
            f"{summary}\n"
        )
    return "\n".join(parts)


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
    """단일 에이전트에게 Task를 보내고 결과를 반환합니다.
    하위 오케스트레이터(agent_type='orchestrator')는 내부 토론 시간이
    필요하므로 별도 타임아웃 적용 클라이언트를 생성합니다.
    """
    try:
        # 하위 오케스트레이터는 더 긴 타임아웃 필요
        if agent.agent_type == "orchestrator":
            effective_timeout = max(timeout, 600.0)
            agent_client = httpx.AsyncClient(timeout=effective_timeout)
        else:
            agent_client = http_client
        client = A2AClient(agent_client, url=agent.url)
        response = await client.send_message(
            SendMessageRequest(
                id=str(uuid.uuid4()),
                params=MessageSendParams(message=_make_message(prompt)),
            )
        )
        # response 래퍼 풀기: SendMessageResponse.root.result → 실제 Message/Task
        root = getattr(response, "root", response)
        result = getattr(root, "result", root)

        # 재귀적으로 텍스트 추출 시도
        def try_extract(obj):
            if obj is None:
                return ""
            # parts가 있으면 텍스트 추출
            if hasattr(obj, "parts") and obj.parts:
                text = _extract_text(obj)
                if text:
                    return text
            # Task: status.message
            status = getattr(obj, "status", None)
            if status:
                msg = getattr(status, "message", None)
                if msg:
                    text = try_extract(msg)
                    if text:
                        return text
            # history
            history = getattr(obj, "history", None)
            if history:
                for h in reversed(history):
                    text = try_extract(h)
                    if text:
                        return text
            # artifacts
            artifacts = getattr(obj, "artifacts", None)
            if artifacts:
                for a in artifacts:
                    text = try_extract(a)
                    if text:
                        return text
            return ""

        text = try_extract(result)
        if text:
            return text

        return f"[{agent.name}] 응답 파싱 실패: {str(response)[:200]}"
    except Exception as e:
        return f"[{agent.name} 오류] {str(e)}"
    finally:
        # 하위 오케스트레이터용 전용 클라이언트는 닫기
        if agent.agent_type == "orchestrator" and agent_client is not http_client:
            await agent_client.aclose()


async def gather_opinions(
    http_client: httpx.AsyncClient,
    agents: List[AgentInfo],
    topic: str,
    context: str = "",
) -> Dict[str, str]:
    """모든 에이전트로부터 의견을 동시에 수집합니다. 개별 에이전트 실패는 전체를 중단하지 않습니다."""
    prompt = topic
    if context:
        prompt = f"{context}\n\n위 맥락을 참고하여 다음 주제에 대한 의견을 제시해주세요:\n{topic}"

    tasks = [call_agent(http_client, agent, prompt) for agent in agents]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    opinions = {}
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            opinions[agents[i].name] = f"[{agents[i].name} 오류] {type(result).__name__}: {result}"
            print(f"  [경고] {agents[i].name} 의견 수집 실패: {result}")
        else:
            opinions[agents[i].name] = result
    return opinions


async def synthesize_with_claude(prompt: str, timeout: float = 120.0) -> str:
    """LLM 프로바이더로 내용을 합성합니다. timeout 초과 시 에러 대신 폴백 메시지를 반환합니다."""
    provider = _get_synthesizer()
    return await provider.synthesize(prompt, timeout=timeout)


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
    has_sub_orchestrators = any(
        a.agent_type == "orchestrator" for a in config.registered_agents
    )
    base_timeout = config.sub_orchestrator_timeout if has_sub_orchestrators else 120.0

    async with httpx.AsyncClient(timeout=base_timeout) as http_client:
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
            try:
                response = await call_agent(http_client, agent, topic)
            except Exception as e:
                response = f"[{agent.name} 오류] {type(e).__name__}: {e}"
                print(f"  [경고] 라운드 0 - {agent.name} 실패: {e}")
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
                try:
                    response = await call_agent(http_client, agent, prompt)
                except Exception as e:
                    response = f"[{agent.name} 오류] {type(e).__name__}: {e}"
                    print(f"  [경고] 라운드 {round_num} - {agent.name} 실패: {e}")
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
    knowledge_store: Optional[KnowledgeStore] = None,
) -> Dict:
    """
    에이전트 수에 따라 자동으로 모드를 결정합니다.
    - 1개: 바로 답변 (토론 없음)
    - 2개+: 토론 후 보고서 생성
    knowledge_store가 있으면 과거 관련 보고서를 컨텍스트로 주입합니다.
    """
    history = []

    # 토픽 정규화 (Claude)
    topic_info = {"normalized": topic, "keywords": []}
    if knowledge_store:
        print("[토픽 정규화] Claude로 토픽 추출 중...")
        topic_info = await normalize_topic(topic)
        print(f"  정규화: {topic_info['normalized']}")
        print(f"  키워드: {topic_info['keywords']}")

        # 동일 토픽 기존 보고서 확인
        existing = knowledge_store.find_by_normalized_topic(topic_info["normalized"])
        if existing:
            print(f"  기존 보고서 발견 (v{existing['version']}) → 완료 후 supersede 예정")

    # 과거 관련 보고서 검색
    knowledge_context = await _build_knowledge_context(knowledge_store, topic)
    if knowledge_context:
        print(f"[지식 저장소] 관련 과거 보고서를 컨텍스트에 포함합니다")

    # 하위 오케스트레이터가 포함되어 있으면 타임아웃 확장
    has_sub_orchestrators = any(
        a.agent_type == "orchestrator" for a in config.registered_agents
    )
    base_timeout = config.sub_orchestrator_timeout if has_sub_orchestrators else 120.0

    async with httpx.AsyncClient(timeout=base_timeout) as http_client:
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

        # 라운드 0: 초기 의견 수집 (과거 지식 컨텍스트 포함)
        print("[라운드 0] 초기 의견 수집 중...")
        initial_opinions = await gather_opinions(
            http_client, agents, topic, context=knowledge_context,
        )
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

            results = await asyncio.gather(*tasks, return_exceptions=True)
            for i, agent in enumerate(agents):
                if isinstance(results[i], Exception):
                    debate_opinions[agent.name] = f"[{agent.name} 오류] {type(results[i]).__name__}: {results[i]}"
                    print(f"  [경고] {agent.name} 토론 실패: {results[i]}")
                else:
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

        # 과거 참조가 있으면 보고서 프롬프트에도 포함
        knowledge_note = ""
        if knowledge_context:
            knowledge_note = (
                f"\n\n참고: 이 토론에는 과거 관련 토론 결과가 컨텍스트로 제공되었습니다. "
                f"과거 결론과 이번 토론의 진전 사항을 비교하여 서술해주세요.\n"
            )

        report_prompt = (
            f"다음은 '{topic}'에 대한 멀티 에이전트 토론 내용입니다.\n\n"
            f"{history_text}\n\n"
            f"위 토론 내용을 바탕으로 다음 구조의 보고서를 작성해주세요:\n"
            f"1. 핵심 요약\n"
            f"2. 주요 합의 사항\n"
            f"3. 쟁점 및 다양한 관점\n"
            f"4. 결론 및 권고사항\n"
            f"{knowledge_note}"
        )

        report = await synthesize_with_claude(report_prompt)

        # 보고서 저장 (파일)
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

        # 보고서 저장 (지식 저장소 - 버전 관리 포함)
        if knowledge_store:
            report_id = knowledge_store.save_report(
                topic=topic,
                normalized_topic=topic_info["normalized"],
                report=report,
                mode="debate",
                agents=[a.name for a in agents],
                report_path=str(report_path),
                keywords=topic_info["keywords"],
            )
            saved = knowledge_store.get_report(report_id)
            print(f"[지식 저장소] 보고서 저장 완료 (v{saved['version'] if saved else '?'})")

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
