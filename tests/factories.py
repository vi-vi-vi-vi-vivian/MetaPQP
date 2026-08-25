from pathlib import Path

from portal_audit.domain.models import (
    AuditResult,
    CheckPlan,
    CoverageStatus,
    PageAssessment,
    PageAuditRequest,
    PageContext,
    PageSnapshot,
    PageTarget,
)


def make_result(*, job_id: str = "audit-test", artifact_root: Path | None = None) -> AuditResult:
    request = PageAuditRequest(url="https://example.test/product/demo", product="demo")
    target = PageTarget(
        page_id="page-demo",
        url=request.url,
        source="web",
        product="demo",
        device="desktop",
        locale="zh-CN",
    )
    snapshot = PageSnapshot(
        page_id=target.page_id,
        requested_url=request.url,
        final_url=request.url,
        title="Demo Product",
        http_status=200,
        viewport={"width": 1440, "height": 1000},
        body_text="产品优势 立即订阅",
    )
    if artifact_root is not None:
        from portal_audit.domain.models import ArtifactRef

        screenshot = (
            artifact_root
            / "web"
            / "demo"
            / "page-demo"
            / "desktop"
            / "zh-CN"
            / job_id
            / "screenshots"
            / "page.png"
        )
        screenshot.parent.mkdir(parents=True, exist_ok=True)
        screenshot.write_bytes(b"png")
        snapshot.artifacts.append(
            ArtifactRef(kind="screenshot", path=str(screenshot), media_type="image/png")
        )
    context = PageContext(
        primary_journey_stage="awareness",
        page_archetypes=["product_landing"],
        features=["purchase_entry"],
    )
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
    )
