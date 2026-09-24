"""Local-only FastAPI control room for MetaPQP configuration and runs."""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from portal_audit.bootstrap import (
    build_comparison_audit_runner,
    build_journey_audit_runner,
    build_page_audit_runner,
)
from portal_audit.domain.models import (
    ChecklistDefinition,
    ChecklistItem,
    CheckSpec,
    ComparisonRequest,
    JourneyAuditRequest,
    PageAuditRequest,
)
from portal_audit.domain.registry import (
    CapabilityRegistry,
    ChecklistRegistry,
    CheckSpecRegistry,
    JourneyRegistry,
    PageMapRegistry,
    StandardsRegistry,
    TransitionRegistry,
)
from portal_audit.settings import Settings

STATIC_ROOT = Path(__file__).with_name("static")
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class ChecklistStore:
    """Whitelisted YAML storage for UI-managed checklists."""

    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def all(self) -> list[ChecklistDefinition]:
        return ChecklistRegistry(self.root).load().all()

    def get(self, checklist_id: str) -> ChecklistDefinition:
        return ChecklistRegistry(self.root).load().get(checklist_id)

    def create(self, payload: dict[str, Any]) -> ChecklistDefinition:
        checklist = ChecklistDefinition.model_validate({**payload, "items": []})
        self._validate_id(checklist.id)
        path = self._path(checklist.id)
        if path.exists():
            raise ValueError(f"Checklist {checklist.id} already exists")
        self._write(path, checklist)
        return checklist

    def add_item(self, checklist_id: str, payload: dict[str, Any]) -> ChecklistDefinition:
        checklist = self.get(checklist_id)
        item = ChecklistItem.model_validate(payload)
        if any(existing.id == item.id for existing in checklist.items):
            raise ValueError(f"Checklist item {item.id} already exists")
        checklist.items.append(item)
        self._write(self._path(checklist_id), checklist)
        return checklist

    def _path(self, checklist_id: str) -> Path:
        self._validate_id(checklist_id)
        return self.root / f"{checklist_id}.yaml"

    @staticmethod
    def _validate_id(value: str) -> None:
        if not ID_PATTERN.fullmatch(value):
            raise ValueError("ID must use lowercase letters, numbers and hyphens")

    @staticmethod
    def _write(path: Path, checklist: ChecklistDefinition) -> None:
        path.write_text(
            yaml.safe_dump(checklist.model_dump(mode="json"), allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )


class RunManager:
    """In-memory run status; output reports remain the durable record."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.jobs: dict[str, dict[str, Any]] = {}
        self.tasks: dict[str, asyncio.Task[None]] = {}

    def start(self, item: ChecklistItem) -> dict[str, Any]:
        job_id = f"ui-{datetime.now(UTC):%Y%m%d-%H%M%S-%f}"
        self.jobs[job_id] = {
            "id": job_id,
            "title": item.title,
            "scope": item.scope,
            "status": "queued",
            "message": "已加入本地运行队列",
            "report_url": None,
            "created_at": self._timestamp(),
            "started_at": None,
            "finished_at": None,
        }
        self.tasks[job_id] = asyncio.create_task(self._run(job_id, item))
        return self.jobs[job_id]

    def cancel(self, job_id: str) -> dict[str, Any]:
        """Request cancellation of a queued or active task in this UI process."""
        job = self.jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        if job["status"] not in {"queued", "running"}:
            return job
        task = self.tasks.get(job_id)
        if task is None or task.done():
            job.update(status="cancelled", message="检查已停止", finished_at=self._timestamp())
            return job
        job.update(status="cancelling", message="正在停止浏览器与检查任务…")
        task.cancel()
        return job

    async def _run(self, job_id: str, item: ChecklistItem) -> None:
        job = self.jobs[job_id]
        job.update(
            status="running",
            message=self._running_message(item.scope),
            started_at=self._timestamp(),
        )
        try:
            if item.scope == "page":
                assert item.target is not None
                result = await build_page_audit_runner(self.settings).run(
                    PageAuditRequest(
                        url=item.target.url,
                        product=item.target.product,
                        page_id=item.target.id,
                        page_surface=item.target.page_surface,
                        device=item.device,
                        locale=item.locale,
                        auth_mode=item.auth_mode,
                        audit_profile=item.audit_profile or "mvp",
                    )
                )
            elif item.scope == "comparison":
                assert item.target is not None
                result = await build_comparison_audit_runner(self.settings).run(
                    ComparisonRequest(
                        subject=item.target,
                        references=item.references,
                        device=item.device,
                        locale=item.locale,
                        audit_profile=item.audit_profile or "comparison-mvp",
                        execution_strategy=item.comparison_execution_strategy,
                    )
                )
            else:
                result = await build_journey_audit_runner(self.settings).run(
                    JourneyAuditRequest(
                        journey_id=item.journey_id or "",
                        url=item.target.url if item.target else None,
                        product=item.target.product if item.target else None,
                        device=item.device,
                        locale=item.locale,
                        auth_mode=item.auth_mode,
                        audit_profile=item.audit_profile or "mvp",
                        headless=self.settings.browser_headless,
                    )
                )
            output_dir = Path(result.output_dir or "").resolve()
            report = output_dir / "report.html"
            if not report.is_file():
                raise RuntimeError("检查完成，但未找到 report.html")
            relative = report.relative_to(self.settings.output_root.resolve())
            job.update(
                status="completed",
                message="检查完成",
                report_url=f"/reports/{relative.as_posix()}",
                finished_at=self._timestamp(),
            )
        except asyncio.CancelledError:
            job.update(status="cancelled", message="检查已停止", finished_at=self._timestamp())
            raise
        except Exception as error:  # noqa: BLE001 - UI jobs must surface all runner failures.
            job.update(status="failed", message=str(error), finished_at=self._timestamp())
        finally:
            self.tasks.pop(job_id, None)

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def _running_message(scope: str) -> str:
        return {
            "page": "正在采集页面证据并执行检查…",
            "transition": "正在执行阶段衔接检查…",
            "comparison": "正在采集页面证据并进行对比…",
            "journey": "正在准备并执行用户旅程…",
        }.get(scope, "正在运行检查…")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    settings.output_root.mkdir(parents=True, exist_ok=True)
    store = ChecklistStore(settings.config_root / "checklists")
    run_manager = RunManager(settings)
    app = FastAPI(title="MetaPQP 控制台", docs_url=None, redoc_url=None)
    app.state.run_manager = run_manager
    app.mount("/assets", StaticFiles(directory=STATIC_ROOT), name="assets")
    app.mount("/reports", StaticFiles(directory=settings.output_root), name="reports")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_ROOT / "index.html")

    @app.get("/api/checklists")
    def list_checklists() -> list[dict[str, Any]]:
        return [item.model_dump(mode="json") for item in store.all()]

    @app.post("/api/checklists", status_code=201)
    def create_checklist(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return store.create(payload).model_dump(mode="json")
        except (ValidationError, ValueError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post("/api/checklists/{checklist_id}/items", status_code=201)
    def add_checklist_item(checklist_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return store.add_item(checklist_id, payload).model_dump(mode="json")
        except (ValidationError, ValueError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post("/api/checklists/{checklist_id}/items/{item_id}/run", status_code=202)
    async def run_checklist_item(checklist_id: str, item_id: str) -> dict[str, Any]:
        try:
            checklist = store.get(checklist_id)
            item = next(item for item in checklist.items if item.id == item_id)
        except (ValueError, StopIteration) as error:
            raise HTTPException(status_code=404, detail="Checklist item not found") from error
        if not item.enabled:
            raise HTTPException(status_code=409, detail="Checklist item is disabled")
        return run_manager.start(item)

    @app.get("/api/runs")
    def list_runs() -> list[dict[str, Any]]:
        return list(reversed(list(run_manager.jobs.values())))

    @app.post("/api/runs/{job_id}/cancel")
    def cancel_run(job_id: str) -> dict[str, Any]:
        try:
            return run_manager.cancel(job_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Run not found") from error

    @app.get("/api/journeys")
    def list_journeys() -> list[dict[str, str]]:
        page_maps = PageMapRegistry(settings.config_root / "page_maps").load()
        journeys = JourneyRegistry(
            settings.config_root / "journeys",
            page_maps,
            TransitionRegistry(settings.config_root / "transitions", page_maps).load(),
        ).load()
        return [{"id": item.id, "title": item.title} for item in journeys.all()]

    @app.get("/api/check-specs")
    def list_check_specs() -> list[dict[str, Any]]:
        return [
            {
                "id": spec.id,
                "title": spec.title,
                "scope": spec.scope.value,
                "severity": spec.default_severity.value,
            }
            for spec in _check_spec_registry(settings).all()
        ]

    @app.get("/api/check-specs/{check_spec_id}")
    def get_check_spec(check_spec_id: str) -> dict[str, Any]:
        path = _check_spec_path(settings, check_spec_id)
        registry = _check_spec_registry(settings)
        spec = registry.get(check_spec_id)
        capabilities = CapabilityRegistry(settings.config_root / "capabilities").load().all()
        standards = StandardsRegistry(settings.config_root / "standards").load()
        evidence_names = {
            item
            for check_spec in registry.all()
            for item in check_spec.required_evidence
        }
        evidence_names.update(
            item for capability in capabilities for item in capability.required_evidence
        )
        return {
            "id": check_spec_id,
            "spec": spec.model_dump(mode="json"),
            "yaml": path.read_text(encoding="utf-8"),
            "options": {
                "capabilities": [
                    {
                        "id": item.id,
                        "type": "deterministic" if item.kind.value == "deterministic" else "model_skill",
                        "label": f"{item.id} · {'确定性检查器' if item.kind.value == 'deterministic' else '模型技能'}",
                    }
                    for item in capabilities
                ],
                "evidence": sorted(evidence_names),
                "criteria": [
                    {"id": item.id, "title": item.title, "source_id": item.source_id}
                    for item in standards.criteria.values()
                ],
            },
        }

    @app.put("/api/check-specs/{check_spec_id}")
    def update_check_spec(check_spec_id: str, payload: dict[str, Any]) -> dict[str, str]:
        path = _check_spec_path(settings, check_spec_id)
        try:
            if "spec" in payload:
                parsed = CheckSpec.model_validate(payload["spec"]).model_dump(mode="json")
                content = yaml.safe_dump(parsed, allow_unicode=True, sort_keys=False)
            else:
                content = str(payload.get("yaml", ""))
                parsed = yaml.safe_load(content)
            if not isinstance(parsed, dict) or parsed.get("id") != check_spec_id:
                raise ValueError("CheckSpec 的 ID 不能修改")
        except yaml.YAMLError as error:
            raise HTTPException(status_code=422, detail=f"YAML syntax error: {error}") from error
        except (ValidationError, ValueError) as error:
            raise HTTPException(status_code=422, detail=f"规则字段无效：{error}") from error
        original = path.read_text(encoding="utf-8")
        path.write_text(content, encoding="utf-8")
        try:
            _check_spec_registry(settings)
        except Exception as error:
            path.write_text(original, encoding="utf-8")
            raise HTTPException(status_code=422, detail=f"Configuration invalid: {error}") from error
        return {"id": check_spec_id, "message": "已保存并通过配置校验"}

    return app


def _check_spec_registry(settings: Settings) -> CheckSpecRegistry:
    standards = StandardsRegistry(settings.config_root / "standards").load()
    capabilities = CapabilityRegistry(settings.config_root / "capabilities").load()
    return CheckSpecRegistry(settings.config_root / "check_specs", standards, capabilities).load()


def _check_spec_path(settings: Settings, check_spec_id: str) -> Path:
    if not ID_PATTERN.fullmatch(check_spec_id):
        raise HTTPException(status_code=404, detail="CheckSpec not found")
    path = settings.config_root / "check_specs" / f"{check_spec_id}.yaml"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="CheckSpec not found")
    return path
