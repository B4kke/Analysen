"""Investigation state, queue lifecycle and provenance read-model contracts."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

pytest_plugins = ("tests.integration.test_research_loop",)

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL is required for integration tests",
)


def _coverage(detail: dict, module: str = "BUSINESS_ROLES") -> dict:
    return next(item["coverage"] for item in detail["modules"] if item["module"] == module)


async def _detail(http, investigation_id: str) -> dict:
    response = await http.get(f"/api/v1/investigations/{investigation_id}")
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
async def state_client(loop_client, tmp_path, monkeypatch):
    """Give each state test an isolated raw store and config cache."""
    monkeypatch.setenv("RAW_EVIDENCE_DIR", str(tmp_path / "raw"))
    from apps.api.app.core import config

    config.get_settings.cache_clear()
    try:
        yield loop_client, tmp_path
    finally:
        config.get_settings.cache_clear()


async def _fixture_document(state_client, monkeypatch, nonce: str):
    """Fetch through DocumentFetcher with an in-process HTTP transport."""
    import httpx

    from apps.api.app.core import config
    from apps.api.app.repositories import web_document_ingest
    from apps.api.app.services import document_fetcher
    from apps.api.app.services.document_fetcher import DocumentFetcher, FetchConfig

    tmp_path = state_client[1]
    source_yaml = tmp_path / f"sources-{nonce}.yaml"
    source_yaml.write_text(
        "sources:\n  fixture-web:\n    enabled: true\n    access: PUBLIC_WEB\n"
        "    evidence_tier: 2\n    base_url: http://fixture.test\n    license: test-fixture\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SOURCE_CONFIG_PATH", str(source_yaml))
    config.get_settings.cache_clear()

    async def handler(request: httpx.Request) -> httpx.Response:
        body = f"fixture-original-{nonce}".encode()
        return httpx.Response(
            200,
            headers={"content-type": "text/plain"},
            content=body,
            request=request,
        )

    async def allow_fixture(_url: str) -> None:
        return None

    monkeypatch.setattr(document_fetcher, "validate_public_http_url", allow_fixture)
    monkeypatch.setattr(web_document_ingest, "validate_public_http_url", allow_fixture)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    fetcher = DocumentFetcher(
        FetchConfig(obey_robots=False, rate_limit_per_domain=100), client=client
    )
    result = await fetcher.fetch_raw(f"http://fixture.test/doc?nonce={nonce}")
    await fetcher.__aexit__(None, None, None)
    return result


async def _brreg_pass(state_client, payload: dict):
    (http, created, factory), _tmp_path = state_client
    from tests.integration.test_research_loop import (
        _admit_brreg_lead,
        _create_company,
        _fake_fetch,
        _run_pass,
    )

    investigation_id = await _create_company(http, created)
    lead_id = await _admit_brreg_lead(http, investigation_id)
    fetch, calls = _fake_fetch(payload)
    summary = await _run_pass(factory, investigation_id, fetch)
    return http, factory, investigation_id, lead_id, calls, summary


async def test_fresh_investigation_is_not_started_with_zero_read_model_counts(state_client) -> None:
    from tests.integration.test_research_loop import _create_company

    (http, created, factory), _tmp_path = state_client
    investigation_id = await _create_company(http, created)
    async with factory() as session:
        await session.execute(
            text(
                "UPDATE investigation_modules SET coverage = CAST(:coverage AS jsonb) "
                "WHERE investigation_id = :id"
            ),
            {
                "id": investigation_id,
                "coverage": json.dumps(
                    {
                        "providers": [],
                        "query_classes": [],
                        "query_count": 0,
                        "document_count": 0,
                        "gaps": [],
                        "unavailable_sources": [],
                    }
                ),
            },
        )
        await session.commit()
    detail = await _detail(http, investigation_id)

    assert detail["research"]["status"] == "NOT_STARTED"
    assert detail["document_count"] == 0
    assert detail["evidence_count"] == 0
    assert _coverage(detail) == {
        "providers": [],
        "query_classes": [],
        "query_count": 0,
        "document_count": 0,
        "gaps": [],
        "unavailable_sources": [],
        "endpoints": [],
        "candidate_count": 0,
        "located_count": 0,
        "concordance_count": 0,
        "fulltext_count": 0,
        "restricted_count": 0,
        "fetched_count": 0,
        "time_from": None,
        "time_to": None,
    }


async def test_real_typed_brreg_pass_exposes_job_provenance_and_raw_snapshot(state_client) -> None:
    from tests.integration.test_research_loop import _create_company

    payload = {
        "organisasjonsnummer": "974760673",
        "navn": "State Probe AS",
        "organisasjonsform": {"kode": "AS", "beskrivelse": "Aksjeselskap"},
        "fixture_nonce": str(uuid4()),
    }
    http, factory, investigation_id, lead_id, calls, summary = await _brreg_pass(
        state_client, payload
    )
    assert summary["executed"] == 1
    assert calls == ["974760673"]
    detail = await _detail(http, investigation_id)
    assert detail["research"]["status"] == "COMPLETED"
    assert detail["research"]["summary"] == summary
    assert detail["research"]["job_id"]
    assert detail["document_count"] == 1
    assert detail["evidence_count"] >= 1
    assert detail["leads"][0]["id"] == lead_id
    assert detail["leads"][0]["status"] == "COMPLETED"
    assert _coverage(detail)["document_count"] == 1

    evidence_id = detail["claims"][0]["evidence"][0]["evidence_id"]
    raw = await http.get(f"/api/v1/investigations/{investigation_id}/evidence/{evidence_id}/raw")
    assert raw.status_code == 200, raw.text
    assert (
        raw.content
        == json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    )
    assert raw.headers["content-type"].startswith("application/octet-stream")
    assert raw.headers["content-disposition"].startswith("attachment;")
    assert raw.headers["x-content-type-options"] == "nosniff"

    (http_state, created_state, _factory_state), _tmp_path = state_client
    foreign_id = await _create_company(http_state, created_state)
    missing = await http.get(f"/api/v1/investigations/{foreign_id}/evidence/{evidence_id}/raw")
    assert missing.status_code == 404
    # Keep the factory reference alive until all read-model requests complete.
    assert factory is not None


async def test_enqueue_failure_is_503_and_retry_is_allowed(state_client, monkeypatch) -> None:
    from tests.integration.test_research_loop import _create_company

    (http, created, _factory), _tmp_path = state_client
    investigation_id = await _create_company(http, created)
    from apps.worker.app import tasks

    monkeypatch.setattr(
        tasks.run_research_pass_actor,
        "send",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("broker down")),
    )
    failed = await http.post(f"/api/v1/investigations/{investigation_id}/research/run")
    assert failed.status_code == 503
    detail = await _detail(http, investigation_id)
    assert detail["research"]["status"] == "FAILED"
    assert detail["research"]["error_code"] == "enqueue_failed"

    sent: list[str] = []
    monkeypatch.setattr(
        tasks.run_research_pass_actor, "send", lambda *_a, job_id, **_k: sent.append(job_id)
    )
    retried = await http.post(f"/api/v1/investigations/{investigation_id}/research/run")
    assert retried.status_code == 202
    assert sent == [retried.json()["job_id"]]


async def test_duplicate_queue_request_returns_409_and_sends_once(
    state_client, monkeypatch
) -> None:
    from tests.integration.test_research_loop import _create_company

    (http, created, _factory), _tmp_path = state_client
    investigation_id = await _create_company(http, created)
    sent: list[str] = []
    from apps.worker.app import tasks

    monkeypatch.setattr(
        tasks.run_research_pass_actor, "send", lambda *_a, job_id, **_k: sent.append(job_id)
    )
    first = await http.post(f"/api/v1/investigations/{investigation_id}/research/run")
    second = await http.post(f"/api/v1/investigations/{investigation_id}/research/run")
    assert first.status_code == 202
    assert second.status_code == 409
    assert len(sent) == 1


async def test_actual_worker_can_commit_before_late_enqueue_audit(
    state_client, monkeypatch
) -> None:
    from apps.worker.app import tasks
    from tests.integration.test_research_loop import _admit_brreg_lead, _create_company

    (http, created, _factory), _tmp_path = state_client
    investigation_id = await _create_company(http, created)
    await _admit_brreg_lead(http, investigation_id)

    from apps.api.app.sources.base import SourceRecord

    class FixtureBrregAdapter:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def fetch(self, orgnr: str) -> SourceRecord:
            return SourceRecord(
                source_id="brreg_entities",
                external_id=orgnr,
                source_url=f"https://data.brreg.no/enhetsregisteret/api/enheter/{orgnr}",
                payload={
                    "organisasjonsnummer": orgnr,
                    "navn": "Threaded Worker Fixture AS",
                    "organisasjonsform": {"kode": "AS", "beskrivelse": "Aksjeselskap"},
                },
            )

    monkeypatch.setattr(tasks, "BrregAdapter", FixtureBrregAdapter)
    # Hermetic planner: this test asserts exact pass counts, so the live NIM
    # planner stays disabled even when .env provides a key.
    monkeypatch.setenv("NIM_API_KEY", "")
    from apps.api.app.core import config

    config.get_settings.cache_clear()
    with ThreadPoolExecutor(max_workers=1) as executor:

        def send(_investigation_id: str, *, job_id: str) -> None:
            future = executor.submit(
                tasks.run_research_pass_actor, _investigation_id, job_id=job_id
            )
            future.result()

        monkeypatch.setattr(tasks.run_research_pass_actor, "send", send)
        response = await http.post(f"/api/v1/investigations/{investigation_id}/research/run")
    assert response.status_code == 202
    body = response.json()
    detail = await _detail(http, investigation_id)
    assert detail["research"]["status"] == "COMPLETED"
    assert detail["research"]["job_id"] == body["job_id"]
    assert detail["research"]["summary"]["executed"] == 1
    assert detail["document_count"] == 1
    assert detail["evidence_count"] >= 1

    async with _factory() as session:
        events = (
            (
                await session.execute(
                    text(
                        "SELECT event_type FROM audit_log WHERE investigation_id = :id ORDER BY id"
                    ),
                    {"id": investigation_id},
                )
            )
            .scalars()
            .all()
        )
    assert events[-1] == "RESEARCH_PASS_ENQUEUED"
    assert events.index("RESEARCH_PASS_COMPLETED") < events.index("RESEARCH_PASS_ENQUEUED")


async def test_detail_snapshot_does_not_mix_pre_and_post_worker_rows(
    state_client, monkeypatch
) -> None:
    from apps.api.app.repositories import investigations as investigation_repository
    from apps.api.app.sources.base import SourceRecord
    from apps.worker.app import tasks
    from tests.integration.test_research_loop import _admit_brreg_lead, _create_company

    (http, created, factory), _tmp_path = state_client
    investigation_id = await _create_company(http, created)
    await _admit_brreg_lead(http, investigation_id)

    class FixtureBrregAdapter:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def fetch(self, orgnr: str) -> SourceRecord:
            return SourceRecord(
                source_id="brreg_entities",
                external_id=orgnr,
                source_url=f"https://data.brreg.no/enhetsregisteret/api/enheter/{orgnr}",
                payload={
                    "organisasjonsnummer": orgnr,
                    "navn": "Snapshot Race Fixture AS",
                    "organisasjonsform": {"kode": "AS", "beskrivelse": "Aksjeselskap"},
                    "fixture_nonce": str(uuid4()),
                },
            )

    monkeypatch.setattr(tasks, "BrregAdapter", FixtureBrregAdapter)
    # Hermetic planner: this test asserts exact worker-path counts, so the
    # live NIM planner stays disabled even when .env provides a key.
    monkeypatch.setenv("NIM_API_KEY", "")
    from apps.api.app.core import config

    config.get_settings.cache_clear()
    sent: list[str] = []
    monkeypatch.setattr(
        tasks.run_research_pass_actor,
        "send",
        lambda _iid, *, job_id, **_kwargs: sent.append(job_id),
    )
    queued = await http.post(f"/api/v1/investigations/{investigation_id}/research/run")
    assert queued.status_code == 202
    job_id = queued.json()["job_id"]

    real_get_modules = investigation_repository.get_modules
    first_modules_call = True
    with ThreadPoolExecutor(max_workers=1) as executor:

        def run_worker() -> None:
            future = executor.submit(tasks.run_research_pass_actor, investigation_id, job_id=job_id)
            future.result()

        async def get_modules_during_snapshot(session, iid):
            nonlocal first_modules_call
            if first_modules_call:
                first_modules_call = False
                run_worker()
            return await real_get_modules(session, iid)

        monkeypatch.setattr(investigation_repository, "get_modules", get_modules_during_snapshot)
        initial = await _detail(http, investigation_id)

    assert initial["research"]["status"] == "ENQUEUED"
    assert initial["claims"] == []
    assert initial["document_count"] == 0
    assert initial["evidence_count"] == 0
    assert sent == [job_id]

    final = await _detail(http, investigation_id)
    assert final["research"]["status"] == "COMPLETED"
    assert final["research"]["job_id"] == job_id
    assert final["claims"]
    assert final["document_count"] == 1
    assert final["evidence_count"] >= 1
    async with factory() as session:
        events = (
            (
                await session.execute(
                    text(
                        "SELECT event_type FROM audit_log WHERE investigation_id = :id ORDER BY id"
                    ),
                    {"id": investigation_id},
                )
            )
            .scalars()
            .all()
        )
    assert events[-1] == "RESEARCH_PASS_COMPLETED"
    assert events.index("RESEARCH_PASS_ENQUEUED") < events.index("RESEARCH_PASS_STARTED")


async def test_pass_failure_is_persisted_without_exception_text_and_source_failure_is_counted(
    state_client, monkeypatch
) -> None:
    from apps.api.app.services import research_loop
    from apps.api.app.services.research_loop import run_research_pass
    from tests.integration.test_research_loop import (
        _admit_brreg_lead,
        _create_company,
        _fake_fetch,
    )

    (http, created, factory), _tmp_path = state_client
    investigation_id = await _create_company(http, created)
    await _admit_brreg_lead(http, investigation_id)
    with monkeypatch.context() as patch:
        patch.setattr(
            research_loop,
            "select_next",
            lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("secret inner failure")),
        )
        with pytest.raises(RuntimeError, match="secret inner failure"):
            async with factory() as session:
                from apps.api.app.services.lead_executor import ExecutorTools

                tools = ExecutorTools(brreg_fetch=_fake_fetch({})[0])
                await run_research_pass(session, UUID(investigation_id), tools)
    detail = await _detail(http, investigation_id)
    assert detail["research"]["status"] == "FAILED"
    assert detail["research"]["error_code"] == "research_pass_failed"
    assert detail["research"]["error_message"] is None

    fresh_id = await _create_company(http, created)
    lead_id = await _admit_brreg_lead(http, fresh_id)

    async def source_error(_orgnr: str):
        raise ConnectionError("fixture source failure")

    async with factory() as session:
        from apps.api.app.services.lead_executor import ExecutorTools

        summary = await run_research_pass(
            session, UUID(fresh_id), ExecutorTools(brreg_fetch=source_error)
        )
    assert summary["failed"] == 1
    assert summary["executed"] == 0
    detail = await _detail(http, fresh_id)
    assert detail["research"]["status"] == "COMPLETED"
    assert detail["leads"][0]["id"] == lead_id
    assert detail["leads"][0]["status"] == "FAILED"

    activity_id = await _create_company(http, created)
    proposed = await http.post(
        f"/api/v1/investigations/{activity_id}/leads",
        json={
            "lead_type": "unsupported_fixture_lead",
            "value": {"orgnr": "974760673"},
            "reason": "Exercise terminal direct lead failure",
            "priority": 0.4,
            "depth": 0,
            "scope_area": "BUSINESS_ROLES",
            "trigger_type": "WEAK_SOURCE_ONLY",
            "information_need": "Exercise direct failure state",
            "relation_depth": 0,
        },
    )
    assert proposed.status_code == 201, proposed.text
    failed_lead = proposed.json()["lead_id"]
    executed = await http.post(f"/api/v1/investigations/{activity_id}/leads/{failed_lead}/execute")
    assert executed.status_code == 200, executed.text
    assert executed.json()["status"] == "FAILED"
    activity_detail = await _detail(http, activity_id)
    assert activity_detail["research"]["status"] == "ACTIVITY_RECORDED"


async def test_direct_document_and_evidence_are_activity_without_claim(
    state_client, monkeypatch
) -> None:
    from apps.api.app.repositories.web_document_ingest import persist_web_document
    from tests.integration.test_research_loop import _create_company

    (http, created, factory), _tmp_path = state_client
    investigation_id = await _create_company(http, created)
    from apps.api.app.domain.models import SourceRegistryRecord

    nonce = str(uuid4())
    result = await _fixture_document(state_client, monkeypatch, nonce)
    source = SourceRegistryRecord(
        id="fixture-web",
        name="fixture",
        evidence_tier=2,
        access_class="PUBLIC_WEB",
        base_url="http://fixture.test",
        license="test-fixture",
    )
    async with factory() as session:
        _document_id, evidence_id = await persist_web_document(
            session, UUID(investigation_id), source, result
        )
        await session.commit()
    detail = await _detail(http, investigation_id)
    assert detail["research"]["status"] == "ACTIVITY_RECORDED"
    assert detail["document_count"] == 1
    assert detail["evidence_count"] == 1
    assert detail["claims"] == []
    assert evidence_id


@pytest.mark.parametrize("state", ["missing", "corrupt", "escape"])
async def test_raw_missing_or_corrupt_blob_returns_410(
    state_client, monkeypatch, state: str
) -> None:
    from apps.api.app.domain.models import SourceRegistryRecord
    from apps.api.app.repositories.web_document_ingest import persist_web_document
    from tests.integration.test_research_loop import _create_company

    (http, created, factory), tmp_path = state_client
    investigation_id = await _create_company(http, created)
    result = await _fixture_document(state_client, monkeypatch, str(uuid4()))
    source = SourceRegistryRecord(
        id="fixture-web",
        name="fixture",
        evidence_tier=2,
        access_class="PUBLIC_WEB",
        base_url="http://fixture.test",
        license="test-fixture",
    )
    async with factory() as session:
        document_id, evidence_id = await persist_web_document(
            session, UUID(investigation_id), source, result
        )
        await session.commit()
    raw_path = tmp_path / "raw" / result.metadata["raw_storage_key"]
    if state == "missing":
        raw_path.unlink()
    elif state == "corrupt":
        raw_path.write_bytes(b"corrupt fixture bytes")
    else:
        async with factory() as session:
            await session.execute(
                text("UPDATE documents SET raw_storage_key = '../../escape' WHERE id = :id"),
                {"id": document_id},
            )
            await session.commit()
    response = await http.get(
        f"/api/v1/investigations/{investigation_id}/evidence/{evidence_id}/raw"
    )
    assert response.status_code == 410
