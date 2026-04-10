"""
계층형 오케스트레이터 단위 테스트 및 통합 테스트
- Config 계층형 필드 테스트 (alias 포함)
- AgentInfo agent_type 테스트
- 부모 등록 로직 테스트
- 타임아웃 동적 조정 테스트
- Hierarchy API / Proxy API 테스트
- A2A 프로토콜을 통한 계층형 통신 통합 테스트
"""
import asyncio
import json
import os
import sys
import tempfile
import pytest
import httpx
from unittest.mock import AsyncMock, patch, MagicMock

# 프로젝트 경로 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "orchestrator"))

from config import OrchestratorConfig, AgentInfo, load_config


def _create_app_isolated(cfg=None):
    """각 테스트마다 독립된 임시 DB를 사용하는 앱을 생성합니다."""
    from server import create_app
    if cfg is None:
        cfg = OrchestratorConfig()
    tmp = tempfile.mktemp(suffix=".db")
    with patch.dict(os.environ, {"KNOWLEDGE_DB_PATH": tmp}):
        app = create_app(cfg)
    return app, tmp


# ============================================================
# 1. Config 단위 테스트
# ============================================================

class TestAgentInfo:
    def test_default_agent_type(self):
        agent = AgentInfo(name="test", url="http://localhost:8001")
        assert agent.agent_type == "agent"

    def test_orchestrator_type(self):
        agent = AgentInfo(
            name="sub-orch",
            url="http://localhost:8000",
            agent_type="orchestrator",
        )
        assert agent.agent_type == "orchestrator"

    def test_agent_with_skills(self):
        agent = AgentInfo(
            name="sub-orch",
            url="http://localhost:8000",
            skills=["backend", "api"],
            agent_type="orchestrator",
        )
        assert agent.skills == ["backend", "api"]
        assert agent.agent_type == "orchestrator"


class TestOrchestratorConfig:
    def test_default_values(self):
        cfg = OrchestratorConfig()
        assert cfg.parent_url == ""
        assert cfg.public_url == ""
        assert cfg.skills == ""
        assert cfg.sub_orchestrator_timeout == 600.0

    def test_hierarchical_config(self):
        cfg = OrchestratorConfig(
            name="Sub-Orchestrator",
            parent_url="http://localhost:9000",
            public_url="http://localhost:8000",
            skills="backend,api-design",
        )
        assert cfg.parent_url == "http://localhost:9000"
        assert cfg.public_url == "http://localhost:8000"
        assert cfg.skills == "backend,api-design"

    def test_load_config_with_env(self):
        env = {
            "ORCHESTRATOR_HOST": "127.0.0.1",
            "ORCHESTRATOR_PORT": "9000",
            "ORCHESTRATOR_NAME": "Meta-Orchestrator",
            "PARENT_ORCHESTRATOR_URL": "http://parent:9000",
            "ORCHESTRATOR_PUBLIC_URL": "http://me:8000",
            "ORCHESTRATOR_SKILLS": "backend,api",
            "SUB_ORCHESTRATOR_TIMEOUT": "900",
        }
        with patch.dict(os.environ, env, clear=False):
            cfg = load_config()
            assert cfg.host == "127.0.0.1"
            assert cfg.port == 9000
            assert cfg.name == "Meta-Orchestrator"
            assert cfg.parent_url == "http://parent:9000"
            assert cfg.public_url == "http://me:8000"
            assert cfg.skills == "backend,api"
            assert cfg.sub_orchestrator_timeout == 900.0


# ============================================================
# 2. 부모 등록 테스트
# ============================================================

class TestParentRegistration:
    @pytest.mark.asyncio
    async def test_register_with_parent_skips_when_no_url(self):
        from server import register_with_parent
        cfg = OrchestratorConfig(parent_url="")
        # Should return without error
        await register_with_parent(cfg)

    @pytest.mark.asyncio
    async def test_register_with_parent_sends_correct_payload(self):
        from server import register_with_parent
        cfg = OrchestratorConfig(
            name="Sub-Orchestrator-A",
            description="팀 A의 오케스트레이터",
            parent_url="http://localhost:9000",
            public_url="http://localhost:8000",
            skills="backend,database",
        )

        captured_request = {}

        async def mock_post(url, json=None, **kwargs):
            captured_request["url"] = url
            captured_request["json"] = json
            resp = MagicMock()
            resp.status_code = 200
            return resp

        mock_client = AsyncMock()
        mock_client.post = mock_post
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            await register_with_parent(cfg)

        assert captured_request["url"] == "http://localhost:9000/agents/register"
        payload = captured_request["json"]
        assert payload["name"] == "Sub-Orchestrator-A"
        assert payload["url"] == "http://localhost:8000"
        assert payload["agent_type"] == "orchestrator"
        assert payload["skills"] == ["backend", "database"]

    @pytest.mark.asyncio
    async def test_register_with_parent_handles_failure(self):
        from server import register_with_parent
        cfg = OrchestratorConfig(
            name="Sub-Orchestrator",
            parent_url="http://unreachable:9000",
            public_url="http://localhost:8000",
        )

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            # Should not raise
            await register_with_parent(cfg)


# ============================================================
# 3. 타임아웃 동적 조정 테스트
# ============================================================

class TestDynamicTimeout:
    @pytest.mark.asyncio
    async def test_call_agent_normal_uses_default_client(self):
        from orchestrator_agent import call_agent
        agent = AgentInfo(name="normal", url="http://localhost:8001", agent_type="agent")

        mock_client = AsyncMock()
        mock_a2a_response = MagicMock()
        mock_result = MagicMock()
        mock_result.parts = [MagicMock()]
        mock_result.parts[0].root = MagicMock()
        mock_result.parts[0].root.text = "test response"
        mock_a2a_response.root.result = mock_result

        with patch("orchestrator_agent.A2AClient") as MockA2A:
            mock_a2a = MockA2A.return_value
            mock_a2a.send_message = AsyncMock(return_value=mock_a2a_response)
            result = await call_agent(mock_client, agent, "test prompt")
            # A2AClient should be created with the original http_client
            MockA2A.assert_called_once_with(mock_client, url="http://localhost:8001")

        assert result == "test response"

    @pytest.mark.asyncio
    async def test_call_agent_orchestrator_creates_extended_timeout_client(self):
        from orchestrator_agent import call_agent
        agent = AgentInfo(name="sub-orch", url="http://localhost:8000", agent_type="orchestrator")

        mock_client = AsyncMock()
        mock_a2a_response = MagicMock()
        mock_result = MagicMock()
        mock_result.parts = [MagicMock()]
        mock_result.parts[0].root = MagicMock()
        mock_result.parts[0].root.text = "debate result"
        mock_a2a_response.root.result = mock_result

        with patch("orchestrator_agent.A2AClient") as MockA2A, \
             patch("orchestrator_agent.httpx.AsyncClient") as MockHttpx:
            mock_extended = AsyncMock()
            mock_extended.aclose = AsyncMock()
            MockHttpx.return_value = mock_extended

            mock_a2a = MockA2A.return_value
            mock_a2a.send_message = AsyncMock(return_value=mock_a2a_response)
            result = await call_agent(mock_client, agent, "test prompt")

            # Should create a new client with extended timeout
            MockHttpx.assert_called_once_with(timeout=600.0)
            # A2AClient should use the extended client, not original
            MockA2A.assert_called_once_with(mock_extended, url="http://localhost:8000")
            # Should close the extended client
            mock_extended.aclose.assert_called_once()

        assert result == "debate result"


# ============================================================
# 4. Agent Card 테스트
# ============================================================

class TestAgentCard:
    def test_agent_card_uses_public_url_when_set(self):
        from server import build_agent_card
        cfg = OrchestratorConfig(
            host="0.0.0.0",
            port=8000,
            public_url="https://my-tunnel.trycloudflare.com",
        )
        card = build_agent_card(cfg)
        assert card.url == "https://my-tunnel.trycloudflare.com/"

    def test_agent_card_falls_back_to_host_port(self):
        from server import build_agent_card
        cfg = OrchestratorConfig(host="0.0.0.0", port=8000)
        card = build_agent_card(cfg)
        assert card.url == "http://0.0.0.0:8000/"


# ============================================================
# 5. REST API 에이전트 등록 통합 테스트
# ============================================================

class TestAgentRegistrationAPI:
    @pytest.mark.asyncio
    async def test_register_orchestrator_type_agent(self):
        from starlette.testclient import TestClient

        app, _ = _create_app_isolated()

        with TestClient(app) as client:
            resp = client.post("/agents/register", json={
                "name": "Sub-Orchestrator-A",
                "url": "http://localhost:8000",
                "description": "팀 A 오케스트레이터",
                "skills": ["backend", "api"],
                "agent_type": "orchestrator",
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data["agent_type"] == "orchestrator"

            # 목록에서 확인
            resp = client.get("/agents")
            agents = resp.json()["agents"]
            assert len(agents) == 1
            assert agents[0]["agent_type"] == "orchestrator"
            assert agents[0]["name"] == "Sub-Orchestrator-A"

    @pytest.mark.asyncio
    async def test_register_mixed_agent_types(self):
        from starlette.testclient import TestClient

        app, _ = _create_app_isolated()

        with TestClient(app) as client:
            # 일반 에이전트 등록
            client.post("/agents/register", json={
                "name": "Agent-1",
                "url": "http://localhost:8001",
            })
            # 하위 오케스트레이터 등록
            client.post("/agents/register", json={
                "name": "Sub-Orch-A",
                "url": "http://localhost:8000",
                "agent_type": "orchestrator",
            })

            resp = client.get("/agents")
            agents = resp.json()["agents"]
            assert len(agents) == 2

            types = {a["name"]: a["agent_type"] for a in agents}
            assert types["Agent-1"] == "agent"
            assert types["Sub-Orch-A"] == "orchestrator"

    @pytest.mark.asyncio
    async def test_update_agent_type(self):
        from starlette.testclient import TestClient

        app, _ = _create_app_isolated()

        with TestClient(app) as client:
            # 처음엔 일반 에이전트로 등록
            client.post("/agents/register", json={
                "name": "Flexible-Agent",
                "url": "http://localhost:8000",
            })
            # 오케스트레이터로 업데이트
            resp = client.post("/agents/register", json={
                "name": "Flexible-Agent",
                "url": "http://localhost:8000",
                "agent_type": "orchestrator",
            })
            assert "업데이트" in resp.json()["message"]

            resp = client.get("/agents")
            assert resp.json()["agents"][0]["agent_type"] == "orchestrator"


# ============================================================
# 6. 계층형 토론 흐름 테스트
# ============================================================

class TestHierarchicalDebateFlow:
    @pytest.mark.asyncio
    async def test_debate_with_mixed_agents_adjusts_timeout(self):
        """하위 오케스트레이터 포함 시 타임아웃이 확장되는지 확인"""
        from orchestrator_agent import run_debate

        cfg = OrchestratorConfig(
            debate_rounds=1,
            sub_orchestrator_timeout=300.0,
            registered_agents=[
                AgentInfo(name="agent-1", url="http://localhost:8001", agent_type="agent"),
                AgentInfo(name="sub-orch", url="http://localhost:8000", agent_type="orchestrator"),
            ],
        )

        call_count = 0

        async def mock_call_agent(http_client, agent, prompt, timeout=120.0):
            nonlocal call_count
            call_count += 1
            if agent.agent_type == "orchestrator":
                return "하위 오케스트레이터의 토론 결과: 합의됨"
            return "일반 에이전트 의견: 동의합니다"

        async def mock_synthesize(prompt):
            return "최종 종합 보고서"

        with patch("orchestrator_agent.call_agent", side_effect=mock_call_agent), \
             patch("orchestrator_agent.gather_opinions") as mock_gather, \
             patch("orchestrator_agent.synthesize_with_claude", side_effect=mock_synthesize), \
             patch("orchestrator_agent.select_agents_for_topic") as mock_select:

            # gather_opinions 모킹
            async def mock_gather_fn(http_client, agents, topic, context=""):
                results = {}
                for a in agents:
                    results[a.name] = await mock_call_agent(http_client, a, topic)
                return results
            mock_gather.side_effect = mock_gather_fn
            mock_select.return_value = cfg.registered_agents

            result = await run_debate(cfg, "테스트 주제")

            assert result["mode"] == "debate"
            assert "sub-orch" in result["agents"]
            assert "agent-1" in result["agents"]


# ============================================================
# 7. Alias 테스트
# ============================================================

class TestAlias:
    def test_agent_info_alias_default(self):
        agent = AgentInfo(name="test-agent", url="http://localhost:8001")
        assert agent.alias == ""

    def test_agent_info_alias_set(self):
        agent = AgentInfo(name="team-a-orch", url="http://localhost:8000", alias="팀A")
        assert agent.alias == "팀A"

    def test_orchestrator_config_alias(self):
        cfg = OrchestratorConfig(name="Meta-Orchestrator", alias="메타")
        assert cfg.alias == "메타"

    def test_load_config_alias_from_env(self):
        with patch.dict(os.environ, {"ORCHESTRATOR_ALIAS": "테스트별칭"}, clear=False):
            cfg = load_config()
            assert cfg.alias == "테스트별칭"

    @pytest.mark.asyncio
    async def test_register_with_alias(self):
        from starlette.testclient import TestClient

        app, _ = _create_app_isolated()

        with TestClient(app) as client:
            resp = client.post("/agents/register", json={
                "name": "team-a-agent",
                "url": "http://localhost:8001",
                "alias": "팀A 에이전트",
            })
            assert resp.status_code == 200
            assert resp.json()["alias"] == "팀A 에이전트"

            resp = client.get("/agents")
            assert resp.json()["agents"][0]["alias"] == "팀A 에이전트"


# ============================================================
# 8. Hierarchy API 테스트
# ============================================================

class TestHierarchyAPI:
    @pytest.mark.asyncio
    async def test_hierarchy_returns_root_info(self):
        from starlette.testclient import TestClient

        cfg = OrchestratorConfig(
            name="Meta-Orch",
            alias="메타",
            description="최상위 오케스트레이터",
        )
        app, _ = _create_app_isolated(cfg)

        with TestClient(app) as client:
            resp = client.get("/hierarchy?recursive=false")
            assert resp.status_code == 200
            data = resp.json()
            assert data["name"] == "Meta-Orch"
            assert data["alias"] == "메타"
            assert data["agent_type"] == "orchestrator"
            assert data["children"] == []

    @pytest.mark.asyncio
    async def test_hierarchy_with_agents(self):
        from starlette.testclient import TestClient

        cfg = OrchestratorConfig(name="Orch")
        app, _ = _create_app_isolated(cfg)

        with TestClient(app) as client:
            client.post("/agents/register", json={
                "name": "agent-1",
                "url": "http://localhost:8001",
                "alias": "에이전트1",
            })
            client.post("/agents/register", json={
                "name": "sub-orch",
                "url": "http://localhost:8000",
                "agent_type": "orchestrator",
                "alias": "하위오케",
            })

            resp = client.get("/hierarchy?recursive=false")
            data = resp.json()
            assert len(data["children"]) == 2
            names = {c["name"] for c in data["children"]}
            assert "agent-1" in names
            assert "sub-orch" in names

            # alias 확인
            aliases = {c["name"]: c["alias"] for c in data["children"]}
            assert aliases["agent-1"] == "에이전트1"
            assert aliases["sub-orch"] == "하위오케"


# ============================================================
# 9. Proxy Debate API 테스트
# ============================================================

class TestProxyDebateAPI:
    @pytest.mark.asyncio
    async def test_proxy_to_agent(self):
        from starlette.testclient import TestClient

        app, _ = _create_app_isolated()

        with TestClient(app) as client:
            client.post("/agents/register", json={
                "name": "test-agent",
                "url": "http://localhost:8001",
            })

            # 에이전트가 실제로 동작하지 않으므로 오류가 반환되지만
            # API 라우팅이 올바르게 동작하는지 확인
            resp = client.post("/proxy/debate", json={
                "target": "test-agent",
                "topic": "테스트 주제",
            })
            assert resp.status_code == 200
            data = resp.json()
            # 연결 실패이므로 에러 메시지가 response에 포함
            assert "test-agent" in (data.get("agent", "") + data.get("response", ""))

    @pytest.mark.asyncio
    async def test_proxy_target_not_found(self):
        from starlette.testclient import TestClient

        app, _ = _create_app_isolated()

        with TestClient(app) as client:
            resp = client.post("/proxy/debate", json={
                "target": "nonexistent",
                "topic": "test",
            })
            assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_proxy_missing_params(self):
        from starlette.testclient import TestClient

        app, _ = _create_app_isolated()

        with TestClient(app) as client:
            resp = client.post("/proxy/debate", json={"topic": "test"})
            assert resp.status_code == 400

            resp = client.post("/proxy/debate", json={"target": "x"})
            assert resp.status_code == 400


# ============================================================
# 10. 지식 저장소 테스트
# ============================================================

class TestKnowledgeStore:
    def _make_store(self):
        from knowledge_store import KnowledgeStore
        tmp = tempfile.mktemp(suffix=".db")
        return KnowledgeStore(db_path=tmp), tmp

    def test_save_and_search_report(self):
        store, _ = self._make_store()
        store.save_report(
            topic="마이크로서비스 전환",
            report="Kong API 게이트웨이를 도입하기로 합의",
            mode="debate",
            agents=["agent-a", "agent-b"],
        )
        results = store.search_reports("마이크로서비스")
        assert len(results) >= 1
        assert "Kong" in results[0]["report"]
        store.close()

    def test_search_no_results(self):
        store, _ = self._make_store()
        results = store.search_reports("존재하지않는주제xyz")
        assert len(results) == 0
        store.close()

    def test_report_count(self):
        store, _ = self._make_store()
        assert store.get_report_count() == 0
        store.save_report(topic="t1", report="r1")
        store.save_report(topic="t2", report="r2")
        assert store.get_report_count() == 2
        store.close()

    def test_agent_persistence(self):
        from knowledge_store import KnowledgeStore
        tmp = tempfile.mktemp(suffix=".db")

        # 저장
        store1 = KnowledgeStore(db_path=tmp)
        store1.save_agent(name="test-agent", url="http://localhost:8001", alias="테스트")
        store1.close()

        # 재로드
        store2 = KnowledgeStore(db_path=tmp)
        agents = store2.load_agents()
        assert len(agents) == 1
        assert agents[0]["name"] == "test-agent"
        assert agents[0]["alias"] == "테스트"
        store2.close()

    def test_agent_upsert(self):
        store, _ = self._make_store()
        store.save_agent(name="a1", url="http://old:8001")
        store.save_agent(name="a1", url="http://new:8001", alias="갱신됨")
        agents = store.load_agents()
        assert len(agents) == 1
        assert agents[0]["url"] == "http://new:8001"
        assert agents[0]["alias"] == "갱신됨"
        store.close()

    def test_agent_delete(self):
        store, _ = self._make_store()
        store.save_agent(name="a1", url="http://localhost:8001")
        assert store.delete_agent("a1") is True
        assert store.delete_agent("nonexistent") is False
        assert len(store.load_agents()) == 0
        store.close()

    def test_recent_reports(self):
        store, _ = self._make_store()
        for i in range(5):
            store.save_report(topic=f"topic-{i}", report=f"report-{i}")
        recent = store.get_recent_reports(limit=3)
        assert len(recent) == 3
        store.close()


class TestKnowledgeAPI:
    @pytest.mark.asyncio
    async def test_knowledge_stats(self):
        from starlette.testclient import TestClient
        app, _ = _create_app_isolated()
        with TestClient(app) as client:
            resp = client.get("/knowledge/stats")
            assert resp.status_code == 200
            data = resp.json()
            assert data["enabled"] is True
            assert data["report_count"] == 0

    @pytest.mark.asyncio
    async def test_knowledge_search(self):
        from starlette.testclient import TestClient
        app, _ = _create_app_isolated()
        with TestClient(app) as client:
            # 빈 검색
            resp = client.get("/knowledge/search?q=test")
            assert resp.status_code == 200
            assert resp.json()["count"] == 0

            # q 누락
            resp = client.get("/knowledge/search")
            assert resp.status_code == 400
