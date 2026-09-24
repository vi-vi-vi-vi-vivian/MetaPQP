from pathlib import Path
from shutil import copytree

from fastapi.testclient import TestClient

from portal_audit.interfaces.web.app import RunManager, create_app
from portal_audit.settings import Settings

ROOT = Path(__file__).parents[1]


def test_web_ui_can_create_and_read_runnable_checklists(tmp_path):
    settings = Settings(
        config_root=tmp_path / "config",
        output_root=tmp_path / "output",
        data_root=tmp_path / "data",
        skills_root=ROOT / "skills",
    )
    client = TestClient(create_app(settings))

    assert client.get("/").status_code == 200
    created = client.post(
        "/api/checklists",
        json={"id": "demo-checklist", "title": "演示清单", "description": "测试"},
    )
    assert created.status_code == 201

    item = client.post(
        "/api/checklists/demo-checklist/items",
        json={
            "id": "demo-page",
            "title": "演示页面",
            "scope": "page",
            "target": {
                "id": "demo-target",
                "product": "Demo",
                "url": "https://example.test",
                "page_surface": "portal",
            },
            "device": "desktop",
            "locale": "zh-CN",
            "auth_mode": "off",
        },
    )
    assert item.status_code == 201

    checklists = client.get("/api/checklists").json()
    assert checklists[0]["items"][0]["scope"] == "page"


def test_web_ui_rejects_invalid_checklist_ids(tmp_path):
    settings = Settings(config_root=tmp_path / "config", output_root=tmp_path / "output")
    client = TestClient(create_app(settings))

    response = client.post("/api/checklists", json={"id": "../unsafe", "title": "Unsafe"})

    assert response.status_code == 422


def test_web_ui_starts_a_run_from_the_async_request_loop(tmp_path, monkeypatch):
    settings = Settings(config_root=tmp_path / "config", output_root=tmp_path / "output")
    client = TestClient(create_app(settings))
    client.post("/api/checklists", json={"id": "demo", "title": "Demo"})
    client.post(
        "/api/checklists/demo/items",
        json={
            "id": "page", "title": "Page", "scope": "page",
            "target": {
                "id": "target", "product": "Demo", "url": "https://example.test",
                "page_surface": "portal",
            },
        },
    )
    monkeypatch.setattr(
        RunManager,
        "start",
        lambda _self, _item: {
            "id": "ui-test", "title": "Page", "status": "queued",
            "message": "等待启动", "report_url": None,
        },
    )

    response = client.post("/api/checklists/demo/items/page/run")

    assert response.status_code == 202
    assert response.json()["id"] == "ui-test"


def test_web_ui_can_cancel_an_active_run(tmp_path):
    class PendingTask:
        def __init__(self):
            self.cancelled = False

        def done(self):
            return False

        def cancel(self):
            self.cancelled = True

    settings = Settings(config_root=tmp_path / "config", output_root=tmp_path / "output")
    app = create_app(settings)
    run_manager = app.state.run_manager
    task = PendingTask()
    run_manager.jobs["ui-active"] = {
        "id": "ui-active",
        "title": "正在运行的检查",
        "scope": "page",
        "status": "running",
        "message": "正在采集页面证据并执行检查…",
        "report_url": None,
        "created_at": "2026-09-17T00:00:00+00:00",
        "started_at": "2026-09-17T00:00:00+00:00",
        "finished_at": None,
    }
    run_manager.tasks["ui-active"] = task  # type: ignore[assignment]
    client = TestClient(app)

    response = client.post("/api/runs/ui-active/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "cancelling"
    assert task.cancelled is True


def test_web_ui_reads_and_validates_structured_check_spec_edits(tmp_path):
    config_root = tmp_path / "config"
    copytree(ROOT / "config", config_root)
    settings = Settings(
        config_root=config_root,
        output_root=tmp_path / "output",
        data_root=tmp_path / "data",
        skills_root=ROOT / "skills",
    )
    client = TestClient(create_app(settings))

    response = client.get("/api/check-specs/broken-links")

    assert response.status_code == 200
    payload = response.json()
    assert payload["spec"]["title"]
    assert payload["options"]["capabilities"]
    assert "interactive_elements" in payload["options"]["evidence"]

    saved = client.put(
        "/api/check-specs/broken-links",
        json={"spec": payload["spec"]},
    )

    assert saved.status_code == 200
    assert "通过配置校验" in saved.json()["message"]
