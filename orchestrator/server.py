"""
오케스트레이터 A2A 서버
- A2A 프로토콜로 외부에서 토론 요청을 받습니다
- 내부적으로 등록된 에이전트들에게 Task를 분배합니다
- REST API로도 직접 호출 가능합니다
"""
import asyncio
import glob as globmod
import json
import os
import sys
import httpx
import uvicorn

from a2a.server.apps import A2AStarletteApplication
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentCard,
    AgentSkill,
    AgentCapabilities,
    Message,
    Part,
    Role,
    TextPart,
)
from a2a.utils import new_agent_text_message
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route, Mount
from starlette.staticfiles import StaticFiles
from starlette.responses import StreamingResponse, HTMLResponse

from config import load_config, OrchestratorConfig
from orchestrator_agent import run_debate, run_debate_streaming, select_agents_for_topic, call_agent


def _extract_user_text(context: RequestContext) -> str:
    try:
        msg = context.message
        for part in msg.parts:
            root = getattr(part, "root", part)
            if hasattr(root, "text"):
                return root.text
    except Exception:
        pass
    return ""


class OrchestratorExecutor(AgentExecutor):
    def __init__(self, config: OrchestratorConfig):
        self.config = config

    async def execute(self, context: RequestContext, event_queue: asyncio.Queue) -> None:
        user_text = _extract_user_text(context)
        if not user_text:
            await event_queue.enqueue_event(
                new_agent_text_message("토론 주제를 입력해주세요.")
            )
            return

        try:
            result = await run_debate(self.config, user_text)
            report = result.get("report", "보고서 생성 실패")
            agents_used = ", ".join(result.get("agents", []))
            final_msg = (
                f"## 토론 완료\n\n"
                f"**주제**: {user_text}\n"
                f"**참여 에이전트**: {agents_used}\n"
                f"**보고서 저장 위치**: {result.get('report_path', 'N/A')}\n\n"
                f"---\n\n{report}"
            )
            await event_queue.enqueue_event(new_agent_text_message(final_msg))
        except Exception as e:
            await event_queue.enqueue_event(
                new_agent_text_message(f"오류 발생: {str(e)}")
            )

    async def cancel(self, context: RequestContext, event_queue: asyncio.Queue) -> None:
        await event_queue.enqueue_event(new_agent_text_message("작업이 취소되었습니다."))


def build_agent_card(config: OrchestratorConfig) -> AgentCard:
    return AgentCard(
        name=config.name,
        description=config.description,
        url=f"http://{config.host}:{config.port}/",
        version="1.0.0",
        defaultInputModes=["text"],
        defaultOutputModes=["text"],
        capabilities=AgentCapabilities(streaming=True),
        skills=[
            AgentSkill(
                id="debate",
                name="멀티 에이전트 토론",
                description=(
                    "여러 에이전트가 주어진 주제에 대해 토론하고 "
                    "최종 보고서를 생성합니다."
                ),
                tags=["debate", "multi-agent", "analysis"],
                examples=[
                    "AI 윤리에 대한 다양한 관점을 토론해주세요",
                    "클라우드 vs 온프레미스 아키텍처의 장단점을 분석해주세요",
                ],
            )
        ],
    )


# REST API: 에이전트 등록
async def register_agent(request: Request) -> JSONResponse:
    cfg: OrchestratorConfig = request.app.state.config
    try:
        body = await request.json()
        name = body.get("name")
        url = body.get("url")
        description = body.get("description", "")
        skills = body.get("skills", [])
        data_paths = body.get("data_paths", [])
        mcp_servers = body.get("mcp_servers", [])
        if not name or not url:
            return JSONResponse({"error": "name과 url은 필수입니다"}, status_code=400)

        # 중복 체크
        for agent in cfg.registered_agents:
            if agent.name == name:
                agent.url = url
                agent.description = description
                agent.skills = skills
                agent.data_paths = data_paths
                agent.mcp_servers = mcp_servers
                return JSONResponse({
                    "message": f"에이전트 '{name}' 업데이트 완료",
                    "url": url, "skills": skills,
                    "data_paths": data_paths, "mcp_servers": mcp_servers,
                })

        from config import AgentInfo
        cfg.registered_agents.append(AgentInfo(
            name=name, url=url, description=description,
            skills=skills, data_paths=data_paths, mcp_servers=mcp_servers,
        ))
        return JSONResponse({
            "message": f"에이전트 '{name}' 등록 완료",
            "url": url, "skills": skills,
            "data_paths": data_paths, "mcp_servers": mcp_servers,
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# REST API: 등록된 에이전트 목록
async def list_agents(request: Request) -> JSONResponse:
    cfg: OrchestratorConfig = request.app.state.config
    return JSONResponse({
        "agents": [
            {
                "name": a.name, "url": a.url, "description": a.description,
                "skills": a.skills, "data_paths": a.data_paths, "mcp_servers": a.mcp_servers,
            }
            for a in cfg.registered_agents
        ]
    })


# REST API: 토론 직접 시작
async def start_debate(request: Request) -> JSONResponse:
    cfg: OrchestratorConfig = request.app.state.config
    try:
        body = await request.json()
        topic = body.get("topic")
        if not topic:
            return JSONResponse({"error": "topic은 필수입니다"}, status_code=400)
        result = await run_debate(cfg, topic)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# REST API: 스킬 기반 단일 쿼리 (가장 적합한 에이전트 1개에 요청)
async def skill_query(request: Request) -> JSONResponse:
    cfg: OrchestratorConfig = request.app.state.config
    try:
        body = await request.json()
        topic = body.get("topic")
        if not topic:
            return JSONResponse({"error": "topic은 필수입니다"}, status_code=400)

        agents = cfg.registered_agents
        if not agents:
            return JSONResponse({"error": "등록된 에이전트가 없습니다"}, status_code=400)

        # 스킬 매칭으로 최적 에이전트 선택
        selected = await select_agents_for_topic(agents, topic, min_agents=1)
        best_agent = selected[0]

        async with httpx.AsyncClient(timeout=120.0) as http_client:
            result = await call_agent(http_client, best_agent, topic)

        return JSONResponse({
            "topic": topic,
            "selected_agent": best_agent.name,
            "all_candidates": [a.name for a in selected],
            "response": result,
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# REST API: 에이전트 헬스체크
async def healthcheck_agents(request: Request) -> JSONResponse:
    cfg: OrchestratorConfig = request.app.state.config
    results = []
    async with httpx.AsyncClient(timeout=5.0) as http_client:
        for agent in cfg.registered_agents:
            try:
                resp = await http_client.get(f"{agent.url}/.well-known/agent.json")
                results.append({
                    "name": agent.name,
                    "url": agent.url,
                    "status": "online" if resp.status_code == 200 else f"error ({resp.status_code})",
                    "ok": resp.status_code == 200,
                })
            except Exception as e:
                results.append({
                    "name": agent.name,
                    "url": agent.url,
                    "status": f"offline ({type(e).__name__})",
                    "ok": False,
                })
    return JSONResponse({"agents": results})


# REST API: 토론 내역 (reports 폴더의 파일 목록 + 내용)
async def list_reports(request: Request) -> JSONResponse:
    cfg: OrchestratorConfig = request.app.state.config
    output_dir = cfg.output_dir
    if not os.path.isdir(output_dir):
        return JSONResponse({"reports": []})

    files = sorted(globmod.glob(os.path.join(output_dir, "*.md")), reverse=True)
    reports = []
    for f in files[:20]:  # 최근 20개
        fname = os.path.basename(f)
        try:
            with open(f, "r", encoding="utf-8") as fh:
                content = fh.read()
            # 파일명에서 타입과 타임스탬프 추출
            rtype = "debate" if fname.startswith("report_") else "query"
            reports.append({
                "filename": fname,
                "type": rtype,
                "content": content,
                "size": len(content),
            })
        except Exception:
            reports.append({"filename": fname, "type": "unknown", "content": "", "size": 0})
    return JSONResponse({"reports": reports})


# SSE 스트리밍 토론
async def stream_debate(request: Request):
    cfg: OrchestratorConfig = request.app.state.config
    topic = request.query_params.get("topic", "")
    if not topic:
        return JSONResponse({"error": "topic 파라미터가 필요합니다"}, status_code=400)

    async def event_generator():
        queue = asyncio.Queue()

        async def callback(event_type: str, data: dict):
            await queue.put((event_type, data))

        async def run():
            try:
                await run_debate_streaming(cfg, topic, callback)
            except Exception as e:
                await queue.put(("error", {"message": str(e)}))
            finally:
                await queue.put(None)  # sentinel

        task = asyncio.create_task(run())

        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                event_type, data = item
                yield f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            task.cancel()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# 대시보드 페이지
async def dashboard(request: Request):
    import os
    html_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
    with open(html_path, "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())


def create_app(config: OrchestratorConfig) -> Starlette:
    executor = OrchestratorExecutor(config)
    agent_card = build_agent_card(config)
    handler = DefaultRequestHandler(
        agent_executor=executor,
        task_store=InMemoryTaskStore(),
    )
    a2a_app = A2AStarletteApplication(
        agent_card=agent_card,
        http_handler=handler,
    )

    # A2A 앱에 REST 라우트 추가
    extra_routes = [
        Route("/dashboard", dashboard, methods=["GET"]),
        Route("/stream/debate", stream_debate, methods=["GET"]),
        Route("/agents/register", register_agent, methods=["POST"]),
        Route("/agents", list_agents, methods=["GET"]),
        Route("/agents/health", healthcheck_agents, methods=["GET"]),
        Route("/reports", list_reports, methods=["GET"]),
        Route("/debate", start_debate, methods=["POST"]),
        Route("/query", skill_query, methods=["POST"]),
    ]

    app = Starlette(
        routes=[
            *extra_routes,
            Mount("/", app=a2a_app.build()),
        ]
    )
    app.state.config = config
    return app


def main():
    config = load_config()
    print(f"오케스트레이터 시작: http://{config.host}:{config.port}")
    print(f"등록된 에이전트: {[a.name for a in config.registered_agents]}")
    app = create_app(config)
    uvicorn.run(app, host=config.host, port=config.port, log_level="info")


if __name__ == "__main__":
    main()
