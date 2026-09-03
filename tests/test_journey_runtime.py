import base64
import json
from pathlib import Path

import pytest
from PIL import Image

from portal_audit.application.ports.auth import BrowserAuthSession
from portal_audit.application.ports.journey_browser import JourneyBrowserRun
from portal_audit.application.ports.model import ModelCompletion
from portal_audit.application.services.check_plan_builder import CheckPlanBuilder
from portal_audit.application.services.journey_checks import (
    JourneyAssessmentBuilder,
    JourneyCheckExecutor,
    JourneyCheckPlanBuilder,
    JourneyEvidenceBuilder,
)
from portal_audit.application.services.page_map_resolver import PageMapNodeResolver
from portal_audit.application.services.safety_guard import SafetyDecisionError, SafetyGuard
from portal_audit.application.services.transition_checks import (
    TransitionCheckExecutor,
    TransitionCheckPlanBuilder,
)
from portal_audit.application.use_cases.run_journey_audit import JourneyAuditRunner
from portal_audit.domain.models import (
    ActionRecord,
    ArtifactRef,
    AuditResult,
    AuthenticationSummary,
    AuthStatus,
    CheckPlan,
    CheckRun,
    CheckStatus,
    CoverageStatus,
    EvidenceElement,
    InteractiveElement,
    JourneyAuditRequest,
    JourneyDefinition,
    PageAssessment,
    PageAuditRequest,
    PageContext,
    PageMapNode,
    PageMapNodeResolution,
    PageSnapshot,
    PageTarget,
    Severity,
    TransitionDefinition,
    TransitionTrace,
)
from portal_audit.domain.registry import (
    CapabilityRegistry,
    CheckSpecRegistry,
    JourneyRegistry,
    PageMapRegistry,
    SafetyProfileRegistry,
    StandardsRegistry,
    TransitionRegistry,
)
from portal_audit.interfaces.reporting.journey_output_writer import JourneyOutputWriter
from portal_audit.skill_runtime.loader import SkillLoader

ROOT = Path(__file__).parents[1]


def journey_assets():
    standards = StandardsRegistry(ROOT / "config/standards").load()
    capabilities = CapabilityRegistry(ROOT / "config/capabilities").load()
    specs = CheckSpecRegistry(ROOT / "config/check_specs", standards, capabilities).load()
    page_maps = PageMapRegistry(ROOT / "config/page_maps").load()
    transitions = TransitionRegistry(ROOT / "config/transitions", page_maps).load()
    journeys = JourneyRegistry(ROOT / "config/journeys", page_maps, transitions).load()
    safety = SafetyProfileRegistry(ROOT / "config/safety_profiles").load()
    return specs, page_maps, transitions, journeys, safety


def transition_checkers():
    capabilities = CapabilityRegistry(ROOT / "config/capabilities").load()
    return {
        item.id: capabilities.create_checker(item.id)
        for item in capabilities.all()
        if item.kind.value == "deterministic"
        and "transition" in [scope.value for scope in item.supported_scopes]
    }


def test_page_map_resolver_ignores_console_locale_and_region():
    _, page_maps, *_ = journey_assets()
    resolution = PageMapNodeResolver(page_maps).resolve(
        "https://console.huaweicloud.com/modelarts/?locale=en-us&region=cn-east-3"
        "#/model-studio/resourcePlanManagement/purchase"
    )

    assert resolution.status == "matched"
    assert resolution.node_id == "tokenplan-purchase"


def test_page_plan_skips_transition_check_specs():
    specs, *_ = journey_assets()
    plan = CheckPlanBuilder(
        specs,
        ROOT / "config/audit_profiles",
        ROOT / "config/execution_policies",
    ).build(
        PageAuditRequest(
            url="https://example.test",
            page_surface="portal",
        ),
        PageContext(primary_journey_stage="awareness"),
    )

    assert not {
        "journey-transition-reachability",
        "entry-and-resume-continuity",
        "transaction-context-continuity",
    }.intersection(item.check_spec_id for item in plan.selected)


def test_safety_guard_blocks_prohibited_submit_action():
    _, _, transitions, _, safety = journey_assets()
    transition = transitions.get("tokenplan-awareness-to-purchase")

    with pytest.raises(SafetyDecisionError, match="prohibited term"):
        SafetyGuard().authorize(
            transition,
            safety.get("production-readonly"),
            element_text="确认购买",
            element_href="https://example.test/preview",
        )


class FakeAuthProvider:
    async def prepare(self, target, mode):
        del target, mode
        return BrowserAuthSession(
            AuthenticationSummary(status=AuthStatus.AUTHENTICATED),
            storage_state={"cookies": []},
        )


def _captured_snapshot(*, page_id, url, title, body_text):
    return PageSnapshot(
        page_id=page_id,
        requested_url=url,
        final_url=url,
        title=title,
        viewport={"width": 1440, "height": 1000},
        document_size={"width": 1440, "height": 1400},
        body_text=body_text,
        evidence_elements=[
            EvidenceElement(
                element_ref="dom-content",
                tag="h1",
                text=title,
                bounds={"x": 0, "y": 120, "width": 320, "height": 40},
            )
        ],
        artifacts=[
            ArtifactRef(kind="screenshot", path="/tmp/journey-snapshot.png", media_type="image/png")
        ],
    )


class FakeJourneyBrowser:
    def __init__(self, resolver):
        self.resolver = resolver

    async def run_journey(self, *, steps, safety_profile, auth_session):
        del safety_profile, auth_session
        snapshots = [
            _captured_snapshot(
                page_id=steps[0].start_target.page_id,
                url=steps[0].start_target.url,
                title="TokenPlan",
                body_text="Token Plan 立即订阅",
            )
        ]
        traces = []
        for step in steps:
            transition = step.transition
            end = _captured_snapshot(
                page_id=step.end_target.page_id,
                url=step.end_target.url,
                title=f"TokenPlan {step.end_node.title}",
                body_text="Token Plan 套餐购买与确认",
            )
            action = ActionRecord(
                action_id=transition.id,
                action_type="click",
                risk_level=transition.risk_level,
                status="completed",
                safety_decision="allowed",
                matched_count=1,
                selected_occurrence=0,
                element_name=transition.action.target.name,
            )
            trace = TransitionTrace(
                transition_id=transition.id,
                transition_version=transition.version,
                from_node_id=transition.from_node,
                to_node_id=transition.to_node,
                start_snapshot_id=snapshots[-1].snapshot_id,
                end_snapshot_id=end.snapshot_id,
                start_url=snapshots[-1].final_url,
                end_url=end.final_url,
                action=action,
                end_resolution=PageMapNodeResolution(
                    node_id=transition.to_node,
                    node_version="1.0.0",
                    status="matched",
                ),
                safe_stop=transition.safe_stop,
                status="completed",
                termination_reason="safe_stop_reached",
            )
            snapshots.append(end)
            traces.append(trace)
        return JourneyBrowserRun(
            snapshots[0],
            snapshots[-1],
            traces[-1],
            snapshots=snapshots,
            traces=traces,
        )

    async def run_transition(self, **kwargs):
        transition = kwargs["transition"]
        start = PageSnapshot(
            page_id=kwargs["start_target"].page_id,
            requested_url=kwargs["start_target"].url,
            final_url=kwargs["start_target"].url,
            title="TokenPlan",
            viewport={"width": 1440, "height": 1000},
            body_text="Token Plan 立即订阅",
        )
        end_url = kwargs["end_target"].url
        end = PageSnapshot(
            page_id=kwargs["end_target"].page_id,
            requested_url=end_url,
            final_url=end_url,
            title="TokenPlan 购买",
            viewport={"width": 1440, "height": 1000},
            body_text="Token Plan 套餐购买",
        )
        action = ActionRecord(
            action_id=transition.id,
            action_type="click",
            risk_level=transition.risk_level,
            status="completed",
            safety_decision="allowed",
            matched_count=4,
            selected_occurrence=0,
            element_name="立即订阅",
        )
        trace = TransitionTrace(
            transition_id=transition.id,
            transition_version=transition.version,
            from_node_id=transition.from_node,
            to_node_id=transition.to_node,
            start_snapshot_id=start.snapshot_id,
            end_snapshot_id=end.snapshot_id,
            start_url=start.final_url,
            end_url=end.final_url,
            action=action,
            end_resolution=PageMapNodeResolution(
                node_id=transition.to_node,
                node_version="1.0.0",
                status="matched",
            ),
            safe_stop=transition.safe_stop,
            status="completed",
            termination_reason="safe_stop_reached",
        )
        return JourneyBrowserRun(start, end, trace)


class FakePagePipeline:
    async def audit_snapshot(self, *, request, target, snapshot, job_id):
        context = PageContext(primary_journey_stage=request.journey_stage or "unknown")
        assessment = PageAssessment(
            page_id=target.page_id,
            snapshot_id=snapshot.snapshot_id,
            url=snapshot.final_url,
            title=snapshot.title,
            context=context,
            coverage_status=CoverageStatus.VERIFIED,
        )
        return AuditResult(
            job_id=job_id,
            request=request,
            target=target,
            snapshot=snapshot,
            context=context,
            check_plan=CheckPlan(profile="mvp"),
            assessment=assessment,
            output_dir=f"/tmp/{job_id}",
        )


class FakeJourneyWriter:
    def __init__(self, root):
        self.root = root

    def write(self, result):
        path = self.root / result.job_id
        path.mkdir()
        return path


class DisabledModel:
    enabled = False


class SparseConflictModel:
    enabled = True

    async def complete_json(self, request):
        payload = json.loads(request.content[0].text)
        return ModelCompletion(
            content={
                "results": [
                    {
                        "invocation_id": item["invocation_id"],
                        "status": (
                            "fail"
                            if item["check_spec_id"]
                            == "cross-stage-commercial-terms-consistency"
                            else "pass"
                        ),
                        "reason": "发现疑似差异",
                        "evidence": ["只有一侧证据"],
                        "suggestion": "修改价格",
                        "confidence": 0.95,
                    }
                    for item in payload["invocations"]
                ]
            },
            provider="fake",
            model="fake-model",
        )


def test_journey_plan_reuses_one_spec_across_adjacent_node_pairs():
    specs, _, _, journeys, _ = journey_assets()
    journey = journeys.get("tokenplan-awareness-purchase-preview")
    evidence = JourneyEvidenceBuilder().build(
        journey,
        [
            _page_result("stage-a", "感知"),
            _page_result("stage-b", "购买"),
            _page_result("stage-c", "确认"),
        ],
    )
    plan = JourneyCheckPlanBuilder(specs, ROOT / "config/audit_profiles").build(
        journey,
        evidence,
    )

    commercial = [
        item for item in plan.invocations
        if item.check_spec_id == "cross-stage-commercial-terms-consistency"
    ]
    assert [item.subject_node_ids for item in commercial] == [
        ["stage-a", "stage-b"],
        ["stage-b", "stage-c"],
    ]


def test_journey_evidence_separates_decision_guidance_from_selection_state():
    _, _, _, journeys, _ = journey_assets()
    journey = journeys.get("tokenplan-awareness-purchase-preview")
    evidence = JourneyEvidenceBuilder().build(
        journey,
        [
            _page_result(
                "stage-a",
                "感知",
                body="Lite\n最受欢迎\nStandard\n高性价比\n¥149/月",
            ),
            _page_result(
                "stage-b",
                "购买",
                body="Lite\nStandard\n¥149/月\nPro",
            ),
        ],
    )

    awareness, purchase = evidence.nodes
    assert any(
        "最受欢迎" in item.value and "Standard" in item.value
        for item in awareness.facts["decision_guidance"]
    )
    assert purchase.facts["decision_guidance"] == []
    assert awareness.facts["selection_state"] == []


def test_journey_evidence_keeps_more_than_twelve_facts_and_source_refs():
    _, _, _, journeys, _ = journey_assets()
    journey = journeys.get("tokenplan-awareness-purchase-preview")
    result = _page_result(
        "stage-a",
        "感知",
        body="\n".join(f"套餐 {index} 价格 {index} 元/月" for index in range(1, 16)),
    )
    result.snapshot.evidence_elements = [
        EvidenceElement(
            element_ref=f"price-{index}",
            tag="p",
            text=f"套餐 {index} 价格 {index} 元/月",
        )
        for index in range(1, 16)
    ]

    evidence = JourneyEvidenceBuilder().build(journey, [result])
    facts = evidence.nodes[0].facts["commercial_terms"]

    assert len(facts) == 15
    assert facts[-1].value == "套餐 15 价格 15 元/月"
    assert "price-15" in facts[-1].source_element_refs
    assert evidence.nodes[0].content_excerpt.endswith("套餐 15 价格 15 元/月")


async def test_journey_executor_downgrades_conflict_without_two_sided_evidence():
    specs, _, _, journeys, _ = journey_assets()
    journey = journeys.get("tokenplan-awareness-purchase-preview")
    evidence = JourneyEvidenceBuilder().build(
        journey,
        [_page_result("stage-a", "感知"), _page_result("stage-b", "购买")],
    )
    plan = JourneyCheckPlanBuilder(specs, ROOT / "config/audit_profiles").build(
        journey,
        evidence,
    )
    runs, calls = await JourneyCheckExecutor(
        specs,
        SparseConflictModel(),
        SkillLoader(ROOT / "skills"),
    ).execute(plan, evidence)

    commercial = next(
        item for item in runs
        if item.check_spec_id == "cross-stage-commercial-terms-consistency"
    )
    assert commercial.status == "needs_verification"
    assert commercial.suggestion is None
    assert len(calls) == 1


def test_journey_writer_only_creates_annotated_screenshot_for_failure(tmp_path):
    source = tmp_path / "source.png"
    Image.new("RGB", (1000, 1200), "white").save(source)
    page_result = _page_result("stage-a", "感知")
    page_result.snapshot.document_size = {"width": 1000, "height": 1200}
    page_result.snapshot.artifacts = [
        ArtifactRef(kind="screenshot", path=str(source), media_type="image/png")
    ]
    page_result.snapshot.evidence_elements = [
        EvidenceElement(
            element_ref="offer-badge",
            tag="span",
            text="最受欢迎",
            bounds={"x": 420, "y": 310, "width": 90, "height": 28},
        )
    ]
    comparison_page = _page_result(
        "stage-b",
        "购买",
        body="Lite\n立即订阅\n最受欢迎\nStandard\n¥149/月\n立即订阅",
    )
    comparison_page.snapshot.document_size = {"width": 1000, "height": 1200}
    comparison_page.snapshot.artifacts = [
        ArtifactRef(kind="screenshot", path=str(source), media_type="image/png")
    ]
    comparison_page.snapshot.interactive_elements = [
        InteractiveElement(
            element_ref="lite-action",
            tag="button",
            text="立即订阅",
            bounds={"x": 100, "y": 500, "width": 160, "height": 36},
        ),
        InteractiveElement(
            element_ref="standard-action",
            tag="button",
            text="立即订阅",
            bounds={"x": 340, "y": 500, "width": 160, "height": 36},
        ),
    ]
    failed = CheckRun(
        check_spec_id="cross-stage-decision-guidance-continuity",
        check_spec_version="1.0.0",
        status=CheckStatus.FAIL,
        title="跨阶段决策引导连续性",
        reason="stage-a 的 Standard 套餐有“最受欢迎”标识，下一阶段缺失",
        severity=Severity.P2,
        evidence=[
            "stage-a 页面在 Standard 套餐上标注了“最受欢迎”",
            "stage-b 页面展示 Standard 套餐但未包含“最受欢迎”标识",
        ],
        executor_id="journey-model",
        subject_node_ids=["stage-a", "stage-b"],
    )
    writer = JourneyOutputWriter(tmp_path)

    screenshots = writer._write_issue_screenshots(
        tmp_path / "journey-run",
        failed,
        [page_result, comparison_page],
    )

    assert len(screenshots) == 2
    assert all(
        (tmp_path / "journey-run" / item["path"]).is_file()
        for item in screenshots
    )
    assert screenshots[0]["locations"][0]["text"] == "最受欢迎"
    assert screenshots[1]["locations"][0]["element_ref"] == "standard-action"
    assert screenshots[0]["precision"] == "element"
    assert screenshots[1]["precision"] == "comparison"

    passed = failed.model_copy(update={"status": CheckStatus.PASS})
    assert writer._write_issue_screenshots(
        tmp_path / "journey-run",
        passed,
        [page_result, comparison_page],
    ) == []


def test_journey_writer_embeds_page_reports_and_evidence_for_portable_html(tmp_path):
    page_dir = tmp_path / "page-report"
    page_dir.mkdir()
    (page_dir / "screenshots").mkdir()
    (page_dir / "screenshots" / "page.svg").write_text(
        "<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8"
    )
    (page_dir / "report.html").write_text(
        "<img src='screenshots/page.svg'><a href='screenshots/page.svg'>open</a>",
        encoding="utf-8",
    )
    run_dir = tmp_path / "journey-run"
    (run_dir / "screenshots").mkdir(parents=True)
    Image.new("RGB", (12, 12), "white").save(run_dir / "screenshots" / "issue.png")
    payload = {
        "pages": [{"output_dir": str(page_dir)}],
        "journey_check_runs": [
            {"evidence_screenshots": [{"path": "screenshots/issue.png"}]}
        ],
    }

    embedded = JourneyOutputWriter(tmp_path)._standalone_payload(payload, run_dir)

    page_report = embedded["pages"][0]["embedded_report"]
    decoded_report = base64.b64decode(page_report.split(",", 1)[1]).decode("utf-8")
    assert "data:image/svg+xml;base64," in decoded_report
    assert "screenshots/page.svg" not in decoded_report
    assert embedded["journey_check_runs"][0]["evidence_screenshots"][0]["data_uri"].startswith(
        "data:image/png;base64,"
    )


def test_journey_report_has_sidebar_and_issue_deep_link():
    issue = {
        "check_spec_id": "cross-stage-decision-guidance-continuity",
        "invocation_id": "decision-guidance__stage-a--stage-b",
        "status": "fail",
        "title": "跨阶段决策引导连续性",
        "reason": "前序页面存在推荐标识，后序页面缺失。",
        "evidence": ["stage-a 有标识", "stage-b 未包含标识"],
        "suggestion": "保持推荐标识连续。",
        "subject_node_ids": ["stage-a", "stage-b"],
        "standard_refs": [],
        "evidence_screenshots": [],
    }
    report = JourneyOutputWriter._report_html(
        {
            "job_id": "job-1",
            "journey": {"title": "测试旅程", "goal": "验证跨阶段连续性"},
            "status": "completed",
            "coverage_status": "verified",
            "termination_reason": "safe_stop_reached",
            "transition_trace": {
                "safe_stop": "target_loaded",
                "from_node_id": "stage-a",
                "to_node_id": "stage-b",
                "end_url": "https://example.test/b",
                "action": {
                    "element_name": "继续",
                    "matched_count": 1,
                    "selected_occurrence": 0,
                    "safety_decision": "allowed",
                },
            },
            "transition_traces": [],
            "transition_check_runs": [],
            "journey_check_runs": [issue],
            "journey_assessment": {"issue_count": 1},
            "pages": [],
        }
    )

    anchor = "check-decision-guidance__stage-a--stage-b"
    assert "<aside class='sidebar'>" in report
    assert "href='#issues'" in report
    assert f"href='#{anchor}'" in report
    assert f"id='{anchor}'" in report


def _page_result(node_id, title, body=None):
    snapshot = PageSnapshot(
        page_id=node_id,
        requested_url=f"https://example.test/{node_id}",
        final_url=f"https://example.test/{node_id}",
        title=title,
        viewport={"width": 1440, "height": 1000},
        body_text=body or f"{title} 产品价格与规格",
    )
    context = PageContext(primary_journey_stage=node_id)
    target = PageTarget(
        page_id=node_id,
        url=snapshot.final_url,
        source="web",
        device="desktop",
        locale="zh-CN",
        page_map_node_id=node_id,
    )
    return AuditResult(
        job_id=node_id,
        request=PageAuditRequest(url=snapshot.final_url),
        target=target,
        snapshot=snapshot,
        context=context,
        check_plan=CheckPlan(profile="mvp"),
        assessment=PageAssessment(
            page_id=node_id,
            snapshot_id=snapshot.snapshot_id,
            url=snapshot.final_url,
            title=title,
            context=context,
            coverage_status=CoverageStatus.VERIFIED,
        ),
    )


async def test_supervised_single_transition_journey_runs_to_safe_stop(tmp_path):
    specs, page_maps, transitions, journeys, safety = journey_assets()
    resolver = PageMapNodeResolver(page_maps)
    runner = JourneyAuditRunner(
        page_pipeline=FakePagePipeline(),
        page_maps=page_maps,
        transitions=transitions,
        journeys=journeys,
        safety_profiles=safety,
        resolver=resolver,
        auth_provider=FakeAuthProvider(),
        browser_factory=lambda headless: FakeJourneyBrowser(resolver),
        transition_plan_builder=TransitionCheckPlanBuilder(
            specs,
            ROOT / "config/audit_profiles",
        ),
        transition_executor=TransitionCheckExecutor(specs, transition_checkers()),
        journey_evidence_builder=JourneyEvidenceBuilder(),
        journey_plan_builder=JourneyCheckPlanBuilder(
            specs,
            ROOT / "config/audit_profiles",
        ),
        journey_executor=JourneyCheckExecutor(
            specs,
            DisabledModel(),
            SkillLoader(ROOT / "skills"),
        ),
        journey_assessment_builder=JourneyAssessmentBuilder(),
        output_writer=FakeJourneyWriter(tmp_path),
    )

    result = await runner.run(
        JourneyAuditRequest(
            journey_id="tokenplan-awareness-purchase-preview",
            headless=True,
        )
    )

    assert result.status == "completed"
    assert result.termination_reason == "safe_stop_reached"
    assert len(result.page_results) == 2
    assert [item.status for item in result.transition_check_runs] == ["pass", "pass", "pass"]
    assert len(result.journey_check_runs) == 9
    assert {item.status for item in result.journey_check_runs} == {"error"}


async def test_supervised_multi_transition_journey_reuses_adjacent_checks(tmp_path):
    specs, page_maps, transitions, journeys, safety = journey_assets()
    confirmation = PageMapNode(
        id="tokenplan-confirmation",
        version="1.0.0",
        title="TokenPlan 确认页",
        entry_url="https://example.test/tokenplan/confirmation",
        url_patterns=["https://example.test/tokenplan/confirmation"],
        expected_primary_stage="order",
        expected_surface="console",
        auth_required=True,
        product="tokenplan",
    )
    page_maps._nodes[confirmation.id] = confirmation
    second_transition = TransitionDefinition.model_validate(
        {
            "id": "tokenplan-purchase-to-confirmation",
            "version": "1.0.0",
            "title": "TokenPlan 购买到确认",
            "from": "tokenplan-purchase",
            "to": "tokenplan-confirmation",
            "action": {"target": {"role": "button", "name": "下一步"}},
            "end_condition": {"page_map_node": "tokenplan-confirmation"},
            "risk_level": "confirmation_only",
            "safe_stop": "confirmation_page_loaded",
        }
    )
    transitions._transitions[second_transition.id] = second_transition
    multi_journey = JourneyDefinition(
        id="tokenplan-three-node-preview",
        version="1.0.0",
        title="TokenPlan 三节点预览",
        goal="验证多段 Journey",
        start="tokenplan-awareness",
        transitions=[
            "tokenplan-awareness-to-purchase",
            "tokenplan-purchase-to-confirmation",
        ],
        safety_profile="production-readonly-depth-2",
    )
    journeys._journeys[multi_journey.id] = multi_journey
    safety._profiles[multi_journey.safety_profile] = safety.get(
        "production-readonly"
    ).model_copy(
        update={"id": multi_journey.safety_profile, "max_transition_depth": 2}
    )
    resolver = PageMapNodeResolver(page_maps)
    runner = JourneyAuditRunner(
        page_pipeline=FakePagePipeline(),
        page_maps=page_maps,
        transitions=transitions,
        journeys=journeys,
        safety_profiles=safety,
        resolver=resolver,
        auth_provider=FakeAuthProvider(),
        browser_factory=lambda headless: FakeJourneyBrowser(resolver),
        transition_plan_builder=TransitionCheckPlanBuilder(
            specs,
            ROOT / "config/audit_profiles",
        ),
        transition_executor=TransitionCheckExecutor(specs, transition_checkers()),
        journey_evidence_builder=JourneyEvidenceBuilder(),
        journey_plan_builder=JourneyCheckPlanBuilder(
            specs,
            ROOT / "config/audit_profiles",
        ),
        journey_executor=JourneyCheckExecutor(
            specs,
            DisabledModel(),
            SkillLoader(ROOT / "skills"),
        ),
        journey_assessment_builder=JourneyAssessmentBuilder(),
        output_writer=FakeJourneyWriter(tmp_path),
    )

    result = await runner.run(
        JourneyAuditRequest(journey_id=multi_journey.id, headless=True)
    )

    assert result.status == "completed"
    assert len(result.transition_traces) == 2
    assert len(result.page_results) == 3
    commercial = [
        item
        for item in result.journey_check_plan.invocations
        if item.check_spec_id == "cross-stage-commercial-terms-consistency"
    ]
    assert [item.subject_node_ids for item in commercial] == [
        ["tokenplan-awareness", "tokenplan-purchase"],
        ["tokenplan-purchase", "tokenplan-confirmation"],
    ]
