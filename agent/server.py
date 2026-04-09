"""
에이전트 A2A 서버
- A2A 프로토콜로 오케스트레이터의 Task를 받아 처리합니다
- Claude Agent SDK (구독)으로 LLM 처리
- 시작 시 오케스트레이터에 자동 등록
"""
import asyncio
import sys
import httpx
import uvicorn

from a2a.server.apps import A2AStarletteApplication
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCard, AgentSkill, AgentCapabilities
from a2a.utils import new_agent_text_message

from config import AgentConfig, load_config
from claude_agent import process_with_claude


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


class ClaudeAgentExecutor(AgentExecutor):
    def __init__(self, config: AgentConfig):
        self.config = config

    async def execute(self, context: RequestContext, event_queue: asyncio.Queue) -> None:
        user_text = _extract_user_text(context)
        if not user_text:
            await event_queue.put(new_agent_text_message("질문을 입력해주세요."))
            return

        await event_queue.put(new_agent_text_message("처리 중입니다..."))

        result = await process_with_claude(user_text, self.config)
        await event_queue.put(new_agent_text_message(result))

    async def cancel(self, context: RequestContext, event_queue: asyncio.Queue) -> None:
        await event_queue.put(new_agent_text_message("작업이 취소되었습니다."))


def build_agent_card(config: AgentConfig) -> AgentCard:
    public_url = config.public_url or f"http://{config.host}:{config.port}"
    return AgentCard(
        name=config.name,
        description=config.description,
        url=f"{public_url}/",
        version="1.0.0",
        defaultInputModes=["text"],
        defaultOutputModes=["text"],
        capabilities=AgentCapabilities(streaming=True),
        skills=[
            AgentSkill(
                id="analyze",
                name="데이터 분석 및 의견 제시",
                description=(
                    "로컬 데이터를 기반으로 주어진 주제에 대한 "
                    "분석과 의견을 제시합니다."
                ),
                tags=["analysis", "data", "opinion"],
                examples=[
                    "이 주제에 대한 당신의 견해는?",
                    "데이터를 분석하고 인사이트를 제공해주세요",
                ],
            )
        ],
    )


async def register_with_orchestrator(config: AgentConfig) -> None:
    """오케스트레이터에 이 에이전트를 등록합니다."""
    if not config.orchestrator_url:
        return

    public_url = config.public_url or f"http://localhost:{config.port}"
    payload = {
        "name": config.name,
        "url": public_url,
        "description": config.description,
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{config.orchestrator_url}/agents/register",
                json=payload,
            )
            if resp.status_code == 200:
                print(f"오케스트레이터 등록 완료: {config.orchestrator_url}")
            else:
                print(f"등록 실패 (HTTP {resp.status_code}): {resp.text}")
    except Exception as e:
        print(f"오케스트레이터 연결 실패 (나중에 수동 등록 필요): {e}")


def main():
    config = load_config()
    public_url = config.public_url or f"http://localhost:{config.port}"
    print(f"에이전트 시작: {public_url}")
    print(f"에이전트 이름: {config.name}")
    print(f"데이터 디렉토리: {config.data_dir}")

    executor = ClaudeAgentExecutor(config)
    agent_card = build_agent_card(config)
    handler = DefaultRequestHandler(
        agent_executor=executor,
        task_store=InMemoryTaskStore(),
    )
    a2a_app = A2AStarletteApplication(
        agent_card=agent_card,
        http_handler=handler,
    )

    app = a2a_app.build()

    # 시작 시 오케스트레이터 등록
    asyncio.get_event_loop().run_until_complete(register_with_orchestrator(config))

    uvicorn.run(app, host=config.host, port=config.port, log_level="info")


if __name__ == "__main__":
    main()
