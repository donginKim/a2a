"""
오케스트레이터 A2A 서버
- A2A 프로토콜로 외부에서 토론 요청을 받습니다
- 내부적으로 등록된 에이전트들에게 Task를 분배합니다
- REST API로도 직접 호출 가능합니다
"""
import asyncio
import json
import sys
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

from config import load_config, OrchestratorConfig
from orchestrator_agent import run_debate


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
            await event_queue.put(
                new_agent_text_message("토론 주제를 입력해주세요.")
            )
            return

        await event_queue.put(
            new_agent_text_message(f"토론을 시작합니다: '{user_text}'")
        )

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
            await event_queue.put(new_agent_text_message(final_msg))
        except Exception as e:
            await event_queue.put(
                new_agent_text_message(f"오류 발생: {str(e)}")
            )

    async def cancel(self, context: RequestContext, event_queue: asyncio.Queue) -> None:
        await event_queue.put(new_agent_text_message("작업이 취소되었습니다."))


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
        if not name or not url:
            return JSONResponse({"error": "name과 url은 필수입니다"}, status_code=400)

        # 중복 체크
        for agent in cfg.registered_agents:
            if agent.name == name:
                agent.url = url
                agent.description = description
                return JSONResponse({"message": f"에이전트 '{name}' 업데이트 완료", "url": url})

        from config import AgentInfo
        cfg.registered_agents.append(AgentInfo(name=name, url=url, description=description))
        return JSONResponse({"message": f"에이전트 '{name}' 등록 완료", "url": url})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# REST API: 등록된 에이전트 목록
async def list_agents(request: Request) -> JSONResponse:
    cfg: OrchestratorConfig = request.app.state.config
    return JSONResponse({
        "agents": [
            {"name": a.name, "url": a.url, "description": a.description}
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
        Route("/agents/register", register_agent, methods=["POST"]),
        Route("/agents", list_agents, methods=["GET"]),
        Route("/debate", start_debate, methods=["POST"]),
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
