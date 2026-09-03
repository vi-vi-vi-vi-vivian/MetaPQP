"""Run a non-mutating subject/reference comparison sequentially."""
from __future__ import annotations

from portal_audit.application.services.comparison_checks import (
    ComparisonAssessmentBuilder,
    ComparisonCheckExecutor,
    ComparisonCheckPlanBuilder,
    ComparisonEvidenceBuilder,
)
from portal_audit.application.services.evidence_gate import (
    PageEvidenceCaptureError,
    PageEvidenceGate,
)
from portal_audit.application.services.progress import ProgressReporter
from portal_audit.application.services.run_ids import new_job_id
from portal_audit.application.services.run_paths import comparison_capture_relative_dir
from portal_audit.domain.models import (
    AuthMode,
    ComparisonPageCapture,
    ComparisonRequest,
    ComparisonResult,
    PageTarget,
)
from portal_audit.domain.registry import ComparisonProfileRegistry


class ComparisonAuditRunner:
    def __init__(self, *, baseline, profiles: ComparisonProfileRegistry, evidence_builder: ComparisonEvidenceBuilder, plan_builder: ComparisonCheckPlanBuilder, executor: ComparisonCheckExecutor, assessment_builder: ComparisonAssessmentBuilder, output_writer, progress: ProgressReporter | None = None, evidence_gate: PageEvidenceGate | None = None):
        self.baseline, self.profiles, self.evidence_builder, self.plan_builder, self.executor, self.assessment_builder, self.output_writer = baseline, profiles, evidence_builder, plan_builder, executor, assessment_builder, output_writer
        self.progress = progress or ProgressReporter()
        self.evidence_gate = evidence_gate or PageEvidenceGate()

    async def run(self, request: ComparisonRequest) -> ComparisonResult:
        profile = self.profiles.get(request.comparison_profile_id)
        progress = self.progress
        started_at = progress.task_start(
            "MetaPQP 竞品对比检查开始",
            (
                f"本产品：{request.subject.product}",
                f"参考产品：{', '.join(item.product for item in request.references)}",
                f"场景：{request.device} · {request.locale}",
            ),
        )
        job_id = new_job_id()

        async def capture(target, role: str) -> ComparisonPageCapture:
            page_target = PageTarget(
                page_id=target.id,
                url=target.url,
                source="web",
                product=target.product,
                page_surface=target.page_surface,
                device=request.device,
                locale=request.locale,
            )
            run_id = str(
                comparison_capture_relative_dir(
                    request.comparison_profile_id,
                    job_id,
                    role,
                    page_target,
                )
            )
            snapshot = await self.baseline.collect(page_target, run_id, AuthMode.OFF)
            self.evidence_gate.ensure(page_target, snapshot)
            return ComparisonPageCapture(target=page_target, snapshot=snapshot)

        # One browser page at a time: stable on macOS and comparison does not benefit from parallel capture.
        subject_started_at = progress.stage_start("1/5 采集本产品页面", "正在采集本产品的对比证据……")
        subject = await capture(request.subject, "subject")
        progress.stage_complete(subject_started_at, (f"已完成：{subject.target.product or subject.target.page_id}",))
        references_started_at = progress.stage_start("2/5 采集参考产品页面", "正在逐个采集参考产品的对比证据……")
        references = []
        for index, target in enumerate(request.references, start=1):
            references.append(await capture(target, f"reference-{index}"))
        progress.stage_complete(references_started_at, (f"已完成：{len(references)} 个参考页面",))
        evidence_started_at = progress.stage_start("3/5 建立对比证据", "正在整理双方可定位的页面内容……")
        try:
            for result in [subject, *references]:
                self.evidence_gate.ensure(result.target, result.snapshot)
        except PageEvidenceCaptureError as error:
            progress.warning("对比页面采集不完整，对比检查已停止", (str(error),))
            raise
        evidence = self.evidence_builder.build(subject, references)
        progress.stage_complete(
            evidence_started_at,
            (f"本产品元素：{len(evidence.subject.elements)} 个", f"参考页面：{len(evidence.references)} 个"),
        )
        check_started_at = progress.stage_start("4/5 执行对比规则", "正在寻找可迁移的体验改进机会……")
        plan = self.plan_builder.build(request.audit_profile, profile.dimensions, evidence)
        check_runs, details, model_calls = await self.executor.execute(plan, evidence)
        assessment = self.assessment_builder.build(check_runs, details, model_calls)
        progress.stage_complete(
            check_started_at,
            (
                f"已检查：{len(check_runs)} 条 · 可改进：{sum(item.status.value == 'fail' for item in check_runs)} 条",
                f"通过：{sum(item.status.value == 'pass' for item in check_runs)} 条",
            ),
        )
        result = ComparisonResult(job_id=job_id, request=request, comparison_profile=profile, subject_capture=subject, reference_captures=references, comparison_evidence=evidence, comparison_check_plan=plan, assessment=assessment)
        report_started_at = progress.stage_start("5/5 生成对比报告", "正在生成问题说明与局部截图对照……")
        result.output_dir = str(self.output_writer.write(result))
        progress.stage_complete(report_started_at, (f"报告：{result.output_dir}",))
        progress.task_complete("竞品对比检查完成", started_at)
        return result
