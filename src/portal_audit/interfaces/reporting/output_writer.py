"""Generate compatible audit.json and a page-first standalone report.html."""

from __future__ import annotations

import base64
import html
import json
import re
import shutil
from difflib import SequenceMatcher
from pathlib import Path

from PIL import Image, ImageDraw

from portal_audit.application.services.run_paths import page_run_relative_dir
from portal_audit.domain.models import AuditResult, Severity
from portal_audit.domain.registry import StandardsRegistry

PRICING_CHECK_IDS = {
    "price-calculation-consistency",
    "purchase-selection-state-consistency",
}


def _readable_reason(run: dict) -> str:
    reason = str(run.get("reason") or "")
    if run.get("check_spec_id") != "broken-links" or "checked_links=" not in reason:
        return reason
    counts = dict(re.findall(r"(\w+)=(\d+)", reason))
    return (f"共检查 {counts.get('checked_links', '0')} 个不同链接，确认失效 {counts.get('broken_links', '0')} 个。"
            f"另有 {counts.get('protected_or_rate_limited', '0')} 个因访问权限或频率限制无法确认，"
            f"{counts.get('transient_server_errors', '0')} 个遇到服务器暂时异常，"
            f"{counts.get('unverified_links', '0')} 个因网络请求失败未完成验证。待确认不代表链接已失效。")


def _interaction_outcome(item: dict) -> str:
    if item.get('trace', {}).get('status') == 'paused':
        return html.escape(str(item['trace'].get('termination_reason') or '已暂停：需要完成身份验证。'))
    before, after = item.get('before_snapshot') or {}, item.get('after_snapshot') or {}
    if after.get('content_ready') is False:
        return '目标正文尚未加载完成，当前截图不能代表最终页面；需要补跑确认。'
    from portal_audit.application.services.interaction_feedback import local_state_feedback
    feedback = local_state_feedback(before.get('interaction_state', {}), after.get('interaction_state', {}))
    if feedback:
        content = after.get('interaction_state', {}).get('panel_text') or ''
        return html.escape(feedback) + ("<div class='revealed-content'>" + html.escape(content) + '</div>' if content else '')
    if not after:
        return html.escape(str(item.get('trace', {}).get('termination_reason') or '未执行，暂无结果'))
    if before.get('final_url') != after.get('final_url'):
        return f"已跳转：{html.escape(str(after.get('title') or '新页面'))}<br><small>{html.escape(str(after.get('final_url') or ''))}</small>"
    old, new = before.get('body_text', '').splitlines(), after.get('body_text', '').splitlines()
    added = ['\n'.join(new[j1:j2]).strip() for op, i1, i2, j1, j2 in SequenceMatcher(None, old, new, autojunk=False).get_opcodes()
             if op in {'insert', 'replace'}]
    content = '\n'.join(x for x in added if x)
    if content:
        return "本页展开／更新内容：<div class='revealed-content'>" + html.escape(content) + "</div>"
    if old != new:
        return '本页内容已收起或移除；请查看操作后截图。'
    return '未观察到新增文本或页面跳转；请结合截图及检查结论确认。'


def _interaction_target(item: dict, index: int) -> str:
    candidate = item['candidate']
    element = candidate['element']
    name = element.get('text') or {'a': '图标／链接区域', 'button': '图标按钮', 'select': '下拉选择框'}.get(element.get('tag'), '无文本控件')
    label = f"{index}. {name}"
    context = candidate.get('surrounding_text', '').strip()
    result = '<strong>' + html.escape(label) + '</strong>'
    if context and context != name:
        result += '<details class="control-context"><summary>所在区域：' + html.escape(context[:65]) + '</summary>' + html.escape(context[:600]) + '</details>'
    path = item.get('control_screenshot')
    if path:
        result += f"<a href='{html.escape(path)}' target='_blank'><img class='control-shot' src='{html.escape(path)}' alt='{html.escape(label)}：橙框为点击位置'></a>"
    return result


def _interaction_images(item: dict) -> str:
    images = []
    for label, key in (("前", "before_screenshot"), ("后", "after_screenshot")):
        path = item.get(key)
        if path:
            escaped = html.escape(str(path))
            images.append(
                f"<a class='interaction-shot' href='{escaped}' target='_blank'>"
                f"<img src='{escaped}' alt='交互{label}截图'><span>{label}</span></a>"
            )
    return "".join(images) or "—"


def _interaction_result(item: dict, check_runs: list[dict]) -> str:
    if item.get('trace', {}).get('status') == 'paused':
        return "<span class='transition-status needs_verification'>已暂停 · 未完成检查</span><br>" + html.escape(str(item['trace'].get('termination_reason') or '需要完成身份验证'))
    candidate_id = str(item["candidate"]["candidate_id"])
    runs = [run for run in check_runs if str(run.get("invocation_id") or "").endswith(f"__{candidate_id}")]
    if not runs:
        trace = item.get("trace", {})
        if trace.get("status") == "pending":
            return "<span class='transition-status needs_verification'>待补跑</span><br>" + html.escape(str(trace.get("termination_reason") or ""))
        if trace.get("status") == "error":
            return "<span class='transition-status error'>执行失败</span><br>" + html.escape(str(trace.get("termination_reason") or ""))
        if trace.get("status") == "completed":
            return "<span class='transition-status needs_verification'>已点击，待检查</span>"
        return "<span class='transition-status skipped'>未执行</span><br>" + html.escape(str(trace.get("termination_reason") or "安全策略跳过"))
    labels = {"pass": "通过", "fail": "发现问题", "needs_verification": "待确认", "error": "执行失败"}
    overall = (
        "fail" if any(run.get("status") == "fail" for run in runs)
        else "error" if any(run.get("status") == "error" for run in runs)
        else "needs_verification" if any(run.get("status") == "needs_verification" for run in runs)
        else "pass"
    )
    rows = []
    for run in runs:
        # A successful error-page guard is implementation noise in a human
        # interaction report. Show it only when an actual error needs review.
        if (run.get('check_spec_id') == 'interaction-failure-guidance'
                or str(run.get('invocation_id') or '').startswith('interaction-failure-guidance__')) and run.get('status') == 'pass':
            continue
        status = str(run.get("status"))
        rows.append(
            f"<div><b class='{html.escape(status)}'>{labels.get(status, status)}</b> · "
            f"{html.escape(str(run.get('title') or run.get('check_spec_id')))}"
            f"<br><span>{html.escape(str(run.get('reason') or ''))}</span></div>"
            + (f"<div><span>建议：{html.escape(str(run['suggestion']))}</span></div>" if run.get('suggestion') else "")
        )
    return (
        f"<span class='transition-status {overall}'>{labels[overall]}</span>"
        f"<span class='transition-count'>（{len(rows)} 项检查）</span>"
        + "".join(rows)
    )


def _transition_issue_html(item: dict, index: int, check_runs: list[dict]) -> str:
    """Render only confirmed interaction failures in the unified issue register.

    A paused run (for example, an automation safety check) is evidence that the
    result is unknown, not evidence of a page defect. It remains in the
    interaction table, where the reviewer can see why it was not completed.
    """
    trace = item.get("trace", {})
    candidate = item["candidate"]
    if candidate.get("kind") == "quote_configuration":
        return ""
    candidate_id = str(candidate["candidate_id"])
    runs = [
        run for run in check_runs
        if str(run.get("invocation_id") or "").endswith(f"__{candidate_id}")
        and run.get("status") == "fail"
    ]
    if trace.get("status") == "paused" or not runs:
        return ""
    status = "fail"
    primary = runs[0]
    reason = str(primary.get("reason") or "")
    suggestion = str(primary.get("suggestion") or "复核此交互的目标页面与下一步操作。")
    label = str(candidate["element"].get("text") or "未命名控件")
    plan = next((name for name in ("Lite", "Standard", "Pro", "Max")
                 if name.casefold() in str(candidate.get("surrounding_text") or "").casefold()), None)
    if plan and label == "立即订阅":
        label = f"{label} · {plan}"
    title = "交互／跳转问题：" + label
    status_label = "发现问题"
    screenshot = item.get("control_screenshot") or item.get("after_screenshot")
    visual = (
        f"<a class='issue-visual' href='#interaction-{index}'><img src='{html.escape(str(screenshot))}' alt='{html.escape(label)} 的交互证据'></a>"
        if screenshot else "<a class='issue-visual empty-visual' href='#interaction-{index}'>查看交互证据</a>"
    )
    return (
        f"<article class='finding transition-finding {status}'><div class='finding-key'><span class='marker'>交互 {index}</span><span>{status_label}</span></div>"
        f"<div class='finding-body'><h3>{html.escape(title)}</h3><p>{html.escape(reason)}</p>"
        f"<dl><dt>建议</dt><dd>{html.escape(suggestion)}</dd><dt>证据</dt><dd><a href='#interaction-{index}'>查看交互的完整结果</a></dd></dl></div>{visual}</article>"
    )


def _pricing_evidence(run: dict) -> dict[str, str]:
    values = {}
    for item in run.get("evidence") or []:
        key, separator, value = str(item).partition("=")
        if separator:
            values[key] = value
    return values


def _plain_decimal(value: str) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{number:g}"


def _money(value: str) -> str:
    if not value:
        return "—"
    try:
        return f"¥{float(str(value).replace(',', '')):.2f}"
    except (TypeError, ValueError):
        return html.escape(str(value))


def _discount_label(value: str) -> str:
    plain = _plain_decimal(value)
    try:
        rate = float(value)
    except (TypeError, ValueError):
        return plain
    return f"{plain}（{rate * 10:g}折）" if rate < 1 else f"{plain}（无折扣）"


def _pricing_review(audit: dict) -> tuple[str, str]:
    """Render quote calculations separately from navigation interactions."""
    labels = {
        "pass": "金额一致",
        "fail": "金额不一致",
        "needs_verification": "信息不足",
        "error": "未执行",
    }
    rows = []
    counts = {"pass": 0, "fail": 0, "needs_verification": 0, "error": 0}
    for item in audit.get("interaction_traces", []):
        candidate = item.get("candidate") or {}
        if candidate.get("kind") != "quote_configuration":
            continue
        candidate_id = str(candidate.get("candidate_id") or "")
        candidate_runs = [
            run for run in audit.get("check_runs", [])
            if str(run.get("invocation_id") or "").endswith(f"__{candidate_id}")
        ]
        price_run = next((run for run in candidate_runs
                          if run.get("check_spec_id") == "price-calculation-consistency"), None)
        selection_run = next((run for run in candidate_runs
                              if run.get("check_spec_id") == "purchase-selection-state-consistency"), None)
        trace = item.get("trace") or {}
        status = str(price_run.get("status")) if price_run else (
            "error" if trace.get("status") == "error" else "needs_verification"
        )
        if status not in counts:
            status = "error"
        counts[status] += 1
        steps = candidate.get("configuration_steps") or []
        options = [
            str(step.get("configuration_option") or step.get("text") or "")
            for step in steps if step.get("configuration_option") or step.get("text")
        ]
        if not options:
            options = [str((candidate.get("element") or {}).get("text") or "未识别配置")]
        quote = (item.get("after_snapshot") or {}).get("quote_state") or {}
        summary = quote.get("summary") or {}
        fixed_duration = next(
            (str(value) for key, value in summary.items()
             if re.search(r"时长|周期|duration|period|term", str(key), re.IGNORECASE)),
            "",
        )
        if fixed_duration and all(fixed_duration not in option for option in options):
            options.append(fixed_duration)
        evidence = _pricing_evidence(price_run or {})
        actual = evidence.get("actual") or str(
            quote.get("total") or ""
        )
        expected = evidence.get("expected", "")
        unit_price = evidence.get("unit_price", "")
        quantity = evidence.get("quantity", "")
        discount = evidence.get("discount", "")
        unit = evidence.get("billing_unit", "月")
        if unit_price and quantity and discount and expected:
            formula = (
                f"{_money(unit_price)}/{html.escape(unit)} × "
                f"{html.escape(_plain_decimal(quantity))}{html.escape(unit)} × "
                f"{html.escape(_discount_label(discount))} = {_money(expected)}"
            )
        else:
            formula = "缺少单价、购买时长或折扣，无法列出完整算式"
        reason = str((price_run or {}).get("reason") or trace.get("termination_reason") or "尚未完成计价检查")
        if selection_run and selection_run.get("status") != "pass":
            reason += "；配置选择状态：" + str(selection_run.get("reason") or "未确认")
        amount = _money(actual)
        difference = evidence.get("difference")
        difference_text = _money(difference)
        rows.append(
            "<tr>"
            f"<td><strong>{html.escape(' × '.join(options))}</strong></td>"
            f"<td class='money'>{amount}</td>"
            f"<td><code class='price-formula'>{formula}</code></td>"
            f"<td class='money'>{difference_text}</td>"
            f"<td><span class='price-verdict {html.escape(status)}'>{labels[status]}</span>"
            f"<p>{html.escape(reason)}</p></td>"
            "</tr>"
        )
    if not rows:
        return "", ""
    summary = (
        f"共复算 {sum(counts.values())} 个配置组合："
        f"{counts['pass']} 个金额一致，{counts['fail']} 个金额不一致，"
        f"{counts['needs_verification']} 个信息不足，{counts['error']} 个未执行。"
    )
    return summary, "".join(rows)


def _page_issue_screenshot(item: dict, section: dict, audit: dict) -> str | None:
    """Return the base-page segment that contains the finding, if known."""
    locations = item.get("locations") or []
    bounds = next((location.get("bounds") or {} for location in locations if location.get("bounds")), {})
    y = bounds.get("y")
    if y is None:
        return item.get("annotated_screenshot") or section.get("annotated_screenshot")

    artifacts = (audit.get("pages") or [{}])[0].get("snapshot", {}).get("artifacts", [])
    for artifact in artifacts:
        if artifact.get("kind") != "screenshot_segment":
            continue
        metadata = artifact.get("metadata") or {}
        top, height = metadata.get("top"), metadata.get("height")
        if top is not None and height is not None and top <= y < top + height:
            path = str(artifact.get("path") or "")
            for evidence in section.get("evidence_screenshots", []):
                if path.endswith(str(evidence.get("path") or "")):
                    return evidence.get("path")
            return path or None
    return item.get("annotated_screenshot") or section.get("annotated_screenshot")


class OutputWriter:
    def __init__(
        self,
        output_root: Path,
        *,
        model_name: str,
        model_enabled: bool,
        visual_model_name: str | None = None,
        visual_model_enabled: bool = False,
        standards: StandardsRegistry | None = None,
    ):
        self.output_root = output_root
        self.model_name = model_name
        self.model_enabled = model_enabled
        self.visual_model_name = visual_model_name
        self.visual_model_enabled = visual_model_enabled
        self.standards = standards

    def write(self, result: AuditResult) -> Path:
        run_dir = self.output_root / page_run_relative_dir(
            result.request,
            result.target,
            result.job_id,
        )
        run_dir.mkdir(parents=True, exist_ok=True)
        payload = self._audit_payload(result, run_dir)
        (run_dir / "audit.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        (run_dir / "checkplan.json").write_text(
            json.dumps(
                result.check_plan.model_dump(mode="json"),
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
        self._write_model_prompts(run_dir, result)
        (run_dir / "report.html").write_text(self._report_html(payload), encoding="utf-8")
        return run_dir

    @staticmethod
    def _write_model_prompts(run_dir: Path, result: AuditResult) -> None:
        """Write every effective model request as one reviewable document."""
        prompt_dir = run_dir / "artifacts"
        prompt_dir.mkdir(parents=True, exist_ok=True)
        calls = []
        for index, call in enumerate(result.model_calls, start=1):
            calls.append(
                {
                    "index": index,
                    "call_id": call.call_id,
                    "batch_id": call.batch_id,
                    "check_spec_ids": call.check_spec_ids,
                    "provider": call.provider,
                    "model": call.model,
                    "prompt_trace": call.prompt_trace,
                }
            )
        (prompt_dir / "model-prompts.json").write_text(
            json.dumps(
                {"job_id": result.job_id, "calls": calls},
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )

        lines = [
            "# 本次页面检查的模型调用 Prompts",
            "",
            f"任务：`{result.job_id}`  ",
            f"共记录 {len(calls)} 次模型调用。每节是实际发送给模型的 system、user 内容和 JSON 输出约束。",
            "图片不会重复嵌入文档；图片输入列出已保存截图的路径和媒体信息。",
        ]
        for call in calls:
            lines.extend(
                [
                    "",
                    f"## {call['index']}. {call['batch_id']}",
                    "",
                    f"- 检查项：`{', '.join(call['check_spec_ids'])}`",
                    f"- 模型：`{call['provider']} / {call['model']}`",
                ]
            )
            trace = call["prompt_trace"]
            if not trace:
                lines.extend(["", "本次调用未记录 request 内容（通常表示该记录来自旧版本或调用在发送前失败）。"])
                continue
            lines.extend(["", "### System", "", "~~~~text", str(trace.get("system") or ""), "~~~~"])
            for content_index, item in enumerate(trace.get("content") or [], start=1):
                if item.get("type") == "text":
                    lines.extend(["", f"### User 文本 {content_index}", "", "~~~~json", str(item.get("text") or ""), "~~~~"])
                elif item.get("type") == "image":
                    lines.extend(
                        [
                            "",
                            f"### 图片输入 {content_index}",
                            "",
                            "~~~~json",
                            json.dumps(item, ensure_ascii=False, indent=2),
                            "~~~~",
                        ]
                    )
            if schema := trace.get("response_schema"):
                lines.extend(["", "### 要求模型返回的 JSON Schema", "", "~~~~json", json.dumps(schema, ensure_ascii=False, indent=2), "~~~~"])
        (prompt_dir / "model-prompts.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _relative(self, path: str, run_dir: Path) -> str:
        candidate = Path(path)
        try:
            return str(candidate.relative_to(run_dir))
        except ValueError:
            return str(candidate)

    def _audit_payload(self, result: AuditResult, run_dir: Path) -> dict:
        assessment = result.assessment
        counts = {
            severity.value: sum(1 for item in assessment.findings if item.severity == severity)
            for severity in Severity
        }
        issues = []
        screenshot = next(
            (
                self._relative(ref.path, run_dir)
                for ref in result.snapshot.artifacts
                if ref.kind == "screenshot"
            ),
            None,
        )
        for finding in assessment.findings:
            locations = [item.model_dump(mode="json") for item in finding.locations]
            issues.append(
                {
                    "id": finding.id,
                    "section": result.context.primary_journey_stage,
                    "type": finding.check_spec_id,
                    "severity": finding.severity.value,
                    "title": finding.title,
                    "area": finding.area,
                    "page_id": finding.page_id,
                    "page_url": assessment.url,
                    "snapshot_id": finding.snapshot_id,
                    "check_run_id": finding.check_run_id,
                    "check_spec_id": finding.check_spec_id,
                    "check_spec_version": finding.check_spec_version,
                    "confidence": finding.confidence,
                    "evidence": finding.evidence,
                    "evidence_refs": finding.evidence_refs,
                    "locate": list(
                        dict.fromkeys(
                            item.text or item.selector or item.element_ref
                            for item in finding.locations
                        )
                    ),
                    "location_status": "located" if locations else "not_locatable",
                    "locations": locations,
                    "standard_refs": self._resolve_standard_refs(finding.standard_refs),
                    "suggestion_after": finding.suggestion_after,
                    "review_status": finding.review_status,
                    "verification_status": finding.verification_status,
                    "marker": len(issues) + 1,
                }
            )
        # A console application can have a nested vertical scroller.  Its
        # full-page screenshot is only the shell, while element coordinates
        # refer to content inside that scroller.  Never overlay those
        # coordinates on the shell image; the segment renderer below uses the
        # matching scroll position instead.
        has_segments = any(
            item.kind == "screenshot_segment" for item in result.snapshot.artifacts
        )
        annotated_screenshot = (
            None
            if has_segments
            else self._write_annotated_screenshot(
                run_dir,
                screenshot,
                result.snapshot.document_size or result.snapshot.viewport,
                issues,
            )
        )
        evidence_screenshots = self._evidence_screenshots(
            run_dir, result.snapshot.artifacts, issues
        )
        for issue in issues:
            issue["annotated_screenshot"] = annotated_screenshot
        coverage = {
            "status": assessment.coverage_status.value,
            "label": assessment.coverage_status.value,
            "reason": "由 CheckRun 覆盖状态计算",
        }
        section = {
            "id": assessment.page_id,
            "name": result.context.primary_journey_stage,
            "url": assessment.url,
            "title": assessment.title,
            "score": None,
            "is_compliant": not issues,
            "coverage_status": coverage,
            "screenshot": screenshot,
            "annotated_screenshot": annotated_screenshot,
            "evidence_screenshots": evidence_screenshots,
            "issue_refs": [item["id"] for item in issues],
            "check_run_refs": [run.check_run_id for run in assessment.check_runs],
            "analysis_content": "页面维度 PageAssessment 兼容投影",
            "authentication": result.snapshot.authentication.model_dump(mode="json"),
        }
        snapshot_payload = result.snapshot.model_dump(mode="json")
        snapshot_payload["evidence_summary"] = {
            "body_chars": len(result.snapshot.body_text),
            "heading_count": len(result.snapshot.headings),
            "interactive_element_count": len(result.snapshot.interactive_elements),
            "evidence_element_count": len(result.snapshot.evidence_elements),
            "console_error_count": len(result.snapshot.console_errors),
            "network_error_count": len(result.snapshot.network_errors),
            "mobile_overflow_element_count": (
                len(result.snapshot.mobile_layout.overflow_elements)
                if result.snapshot.mobile_layout
                else 0
            ),
        }
        interaction_traces = self._interaction_payload(result.interaction_traces, run_dir, result.snapshot.artifacts)
        for raw_field in (
            "body_text",
            "headings",
            "interactive_elements",
            "evidence_elements",
            "console_errors",
            "network_errors",
            "mobile_layout",
        ):
            snapshot_payload.pop(raw_field, None)
        check_runs = []
        for run in assessment.check_runs:
            run_payload = run.model_dump(mode="json")
            run_payload.pop("locations", None)
            check_runs.append(run_payload)
        return {
            "schema_version": "2.3",
            "source": result.request.source,
            "input_url": result.request.url,
            "generated_at": assessment.generated_at.isoformat(),
            "summary": {
                "score": None,
                "score_status": "experimental",
                "issue_count": len(issues),
                **counts,
            },
            "sections": [section],
            "issues": issues,
            "standards": self._standards_payload(issues),
            "model": {
                "provider": "openrouter",
                "name": self.model_name,
                "enabled": self.model_enabled,
            },
            "model_profiles": {
                "default-text": {
                    "provider": "openrouter",
                    "name": self.model_name,
                    "modalities": ["text"],
                    "enabled": self.model_enabled,
                },
                "default-vision": {
                    "provider": "google-gemini",
                    "name": self.visual_model_name,
                    "modalities": ["text", "image"],
                    "enabled": self.visual_model_enabled,
                },
            },
            "run": {
                "job_id": result.job_id,
                "type": "page",
                "status": "completed",
                "model_execution": self._model_execution_payload(result),
            },
            "asset_versions": {
                "check_plan_builder": result.check_plan.builder_version,
                "check_specs": {
                    run.check_spec_id: run.check_spec_version for run in assessment.check_runs
                },
            },
            "interaction_traces": interaction_traces,
            "pages": [
                {
                    "target": result.target.model_dump(mode="json"),
                    "snapshot": snapshot_payload,
                    "context": result.context.model_dump(mode="json"),
                }
            ],
            "page_assessments": [
                {
                    "assessment_id": assessment.assessment_id,
                    "page_id": assessment.page_id,
                    "snapshot_id": assessment.snapshot_id,
                    "url": assessment.url,
                    "title": assessment.title,
                    "coverage_status": assessment.coverage_status.value,
                    "finding_refs": [item.id for item in assessment.findings],
                    "check_run_refs": [item.check_run_id for item in assessment.check_runs],
                    "generated_at": assessment.generated_at.isoformat(),
                }
            ],
            "check_plan": result.check_plan.model_dump(mode="json"),
            "check_runs": check_runs,
            "reviews": [],
        }

    def _interaction_payload(self, traces, run_dir: Path, base_artifacts=()) -> list[dict]:
        """Copy before/after interaction screenshots into the portable Page bundle."""
        payloads = []
        target_dir = run_dir / "screenshots" / "interactions"
        for trace in traces:
            item = trace.model_dump(mode="json")
            for state, field in ((trace.before_snapshot, "before_screenshot"), (trace.after_snapshot, "after_screenshot")):
                if state is None:
                    continue
                source = next((Path(a.path) for a in state.artifacts if a.kind.endswith("screenshot") and Path(a.path).is_file()), None)
                if source is None:
                    continue
                target_dir.mkdir(parents=True, exist_ok=True)
                destination = target_dir / f"{trace.candidate.candidate_id}-{field}.png"
                shutil.copy2(source, destination)
                item[field] = self._relative(str(destination), run_dir)
            item['control_screenshot'] = self._control_screenshot(item, run_dir, base_artifacts)
            payloads.append(item)
        return payloads

    def _control_screenshot(self, item, run_dir, artifacts):
        # Prefer the viewport captured immediately after the target was scrolled
        # into view. It is the only screenshot guaranteed to share the target's
        # coordinate system in nested-scroll Console applications.
        for artifact in item.get("before_snapshot", {}).get("artifacts", []):
            viewport_bounds = (artifact.get("metadata") or {}).get("control_bounds")
            source = Path(artifact.get("path") or "")
            if viewport_bounds and source.is_file():
                return self._crop_control_screenshot(
                    source, viewport_bounds, item["candidate"]["candidate_id"], run_dir
                )
        bounds = item['candidate']['element'].get('bounds')
        if not bounds:
            return None
        choices = [a for a in artifacts if a.kind == 'screenshot_segment'
                   and a.metadata.get('top', 0) <= bounds['y']
                   and bounds['y'] + bounds['height'] <= a.metadata.get('top', 0) + a.metadata.get('height', 0)]
        if not choices:
            return None
        ref = choices[0]
        source = Path(ref.path)
        if not source.is_absolute():
            source = run_dir / source
        if not source.is_file():
            return None
        return self._crop_control_screenshot(
            source,
            {"x": bounds['x'], "y": bounds['y'] - ref.metadata.get('top', 0),
             "width": bounds['width'], "height": bounds['height']},
            item["candidate"]["candidate_id"], run_dir,
        )

    def _crop_control_screenshot(self, source, bounds, candidate_id, run_dir):
        """Create a compact, correctly aligned PNG evidence crop with an orange frame."""
        with Image.open(source) as image:
            x, y = float(bounds["x"]), float(bounds["y"])
            width, height = float(bounds["width"]), float(bounds["height"])
            left, top = max(0, int(x - 36)), max(0, int(y - 52))
            right = min(image.width, int(x + width + 36))
            bottom = min(image.height, int(y + height + 52))
            if right <= left or bottom <= top:
                return None
            crop = image.crop((left, top, right, bottom)).convert("RGB")
            draw = ImageDraw.Draw(crop)
            draw.rectangle(
                (x - left, y - top, x - left + width, y - top + height),
                outline="#f79009", width=3,
            )
            target = run_dir / "screenshots" / "interactions" / f"{candidate_id}-target.png"
            target.parent.mkdir(parents=True, exist_ok=True)
            crop.save(target, "PNG")
        return self._relative(str(target), run_dir)

    def _resolve_standard_refs(self, references) -> list[dict]:
        if self.standards is None:
            return [item.model_dump(mode="json") for item in references]
        return [self.standards.resolve(item) for item in references]

    @staticmethod
    def _standards_payload(issues: list[dict]) -> dict:
        references = [ref for issue in issues for ref in issue.get("standard_refs", [])]
        sources = {
            ref["source_id"]: {
                key: ref.get(key)
                for key in (
                    "source_id",
                    "source_name",
                    "source_type",
                    "source_version",
                    "source_url",
                )
            }
            for ref in references
            if "source_id" in ref
        }
        criteria = {
            ref["criterion_id"]: {
                key: ref.get(key)
                for key in (
                    "criterion_id",
                    "criterion_title",
                    "criterion_level",
                    "criterion_url",
                    "source_id",
                )
            }
            for ref in references
        }
        return {"sources": list(sources.values()), "criteria": list(criteria.values())}

    @staticmethod
    def _model_execution_payload(result: AuditResult) -> dict:
        def total(field: str) -> int | None:
            values = [getattr(call, field) for call in result.model_calls]
            return (
                sum(value for value in values if value is not None)
                if any(value is not None for value in values)
                else None
            )

        costs = [call.usage_details.get("cost") for call in result.model_calls]
        return {
            "call_count": len(result.model_calls),
            "prompt_tokens": total("prompt_tokens"),
            "completion_tokens": total("completion_tokens"),
            "total_tokens": total("total_tokens"),
            "latency_ms": total("latency_ms"),
            "cost": (
                sum(float(value) for value in costs if value is not None)
                if any(value is not None for value in costs)
                else None
            ),
            "prompt_document": "artifacts/model-prompts.md",
            "prompt_data": "artifacts/model-prompts.json",
            "calls": [
                call.model_dump(mode="json", exclude={"prompt_trace"})
                for call in result.model_calls
            ],
        }

    def _write_annotated_screenshot(
        self,
        run_dir: Path,
        screenshot: str | None,
        document_size: dict,
        issues: list[dict],
    ) -> str | None:
        boxes = [
            (issue, location)
            for issue in issues
            for location in issue.get("locations", [])
            if location.get("bounds")
        ]
        if not screenshot or not boxes:
            return None
        width = max(1, int(document_size.get("width", 1)))
        height = max(1, int(document_size.get("height", 1)))
        annotated = run_dir / "screenshots" / "page-annotated.svg"
        annotated.parent.mkdir(parents=True, exist_ok=True)
        screenshot_path = run_dir / screenshot
        mime_type = "image/png" if screenshot_path.suffix.lower() == ".png" else "image/jpeg"
        image_href = (
            f"data:{mime_type};base64,"
            f"{base64.b64encode(screenshot_path.read_bytes()).decode('ascii')}"
        )
        marks = []
        colors = {"p0": "#d92d20", "p1": "#e5484d", "p2": "#f79009"}
        for issue, location in boxes:
            bounds = location["bounds"]
            x = max(0, float(bounds.get("x", 0)))
            y = max(0, float(bounds.get("y", 0)))
            box_width = max(12, float(bounds.get("width", 0)))
            box_height = max(12, float(bounds.get("height", 0)))
            color = colors.get(issue["severity"], "#e5484d")
            marker = issue["marker"]
            marks.append(
                f"<g><rect x='{x:.1f}' y='{y:.1f}' width='{box_width:.1f}' "
                f"height='{box_height:.1f}' rx='5' fill='{color}' fill-opacity='.10' "
                f"stroke='{color}' stroke-width='4'/><circle cx='{x + 13:.1f}' "
                f"cy='{max(13, y + 13):.1f}' r='13' fill='{color}' stroke='white' "
                f"stroke-width='2'/><text x='{x + 13:.1f}' y='{max(18, y + 18):.1f}' "
                "text-anchor='middle' font-family='Arial,sans-serif' font-size='14' "
                f"font-weight='700' fill='white'>{marker}</text></g>"
            )
        svg = (
            f"<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}' "
            f"viewBox='0 0 {width} {height}'><image href='{image_href}' x='0' y='0' "
            f"width='{width}' height='{height}' preserveAspectRatio='none'/>{''.join(marks)}</svg>"
        )
        annotated.write_text(svg, encoding="utf-8")
        return self._relative(str(annotated), run_dir)

    def _evidence_screenshots(self, run_dir: Path, artifacts, issues: list[dict]) -> list[dict]:
        """Present long pages as readable segments and dialogs as separate states."""
        output: list[dict] = []
        for index, ref in enumerate(
            (item for item in artifacts if item.kind == "screenshot_segment"), start=1
        ):
            source = Path(ref.path)
            metadata = ref.metadata
            top = float(metadata.get("top", 0))
            width = int(metadata.get("width", 1))
            height = int(metadata.get("height", 1))
            boxes = [
                (issue, location)
                for issue in issues
                for location in issue.get("locations", [])
                if location.get("bounds")
                and top <= float(location["bounds"].get("y", 0)) < top + height
            ]
            # This is a problem evidence map, not a full-page screenshot
            # gallery. Segments without a cited issue add noise and are
            # especially misleading when a Console shell is visually fixed.
            if issues and not boxes:
                continue
            path = self._write_segment_annotation(
                run_dir, source, index, top, width, height, boxes
            ) if boxes else self._relative(str(source), run_dir)
            output.append({"path": path, "label": f"基础页面 · 区域 {index}"})
        for index, ref in enumerate(
            (item for item in artifacts if item.kind == "interaction_screenshot"), start=1
        ):
            label = str(ref.metadata.get("label") or "信息详情")
            output.append(
                {"path": self._relative(ref.path, run_dir), "label": f"展开后 · {label}"}
            )
        return output

    def _write_segment_annotation(
        self, run_dir: Path, source: Path, index: int, top: float, width: int, height: int, boxes
    ) -> str:
        target = run_dir / "screenshots" / f"page-segment-{index}-annotated.svg"
        image = base64.b64encode(source.read_bytes()).decode("ascii")
        colors = {"p0": "#d92d20", "p1": "#e5484d", "p2": "#f79009"}
        marks = []
        occupied: list[tuple[float, float, float, float]] = []
        for issue, location in sorted(
            boxes,
            key=lambda item: float(item[1]["bounds"].get("width", 0)) * float(item[1]["bounds"].get("height", 0)),
        ):
            bounds = location["bounds"]
            x = max(0, float(bounds.get("x", 0)))
            y = max(0, float(bounds.get("y", 0)) - top)
            box_width = max(12, float(bounds.get("width", 0)))
            box_height = max(12, float(bounds.get("height", 0)))
            if any(
                left <= x <= right and upper <= y <= lower
                for left, upper, right, lower in occupied
            ):
                continue
            occupied.append((x, y, x + box_width, y + box_height))
            color = colors.get(issue["severity"], "#e5484d")
            marker = issue["marker"]
            marks.append(
                f"<g><rect x='{x:.1f}' y='{y:.1f}' width='{box_width:.1f}' height='{box_height:.1f}' "
                f"rx='5' fill='{color}' fill-opacity='.10' stroke='{color}' stroke-width='4'/><circle "
                f"cx='{x + 13:.1f}' cy='{max(13, y + 13):.1f}' r='13' fill='{color}' stroke='white' "
                f"stroke-width='2'/><text x='{x + 13:.1f}' y='{max(18, y + 18):.1f}' text-anchor='middle' "
                f"font-family='Arial,sans-serif' font-size='14' font-weight='700' fill='white'>{marker}</text></g>"
            )
        target.write_text(
            f"<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}' viewBox='0 0 {width} {height}'><image href='data:image/png;base64,{image}' x='0' y='0' width='{width}' height='{height}'/>{''.join(marks)}</svg>",
            encoding="utf-8",
        )
        return self._relative(str(target), run_dir)

    def _legacy_report_html(self, audit: dict) -> str:
        section = audit["sections"][0]
        summary = audit["summary"]
        issue_rows = (
            "".join(self._finding_html(item) for item in audit["issues"])
            or "<div class='empty'>当前证据下未发现问题。</div>"
        )
        status_labels = {
            "pass": "通过",
            "fail": "发现问题",
            "needs_verification": "待确认",
            "error": "未执行",
        }
        check_rows = "".join(
            f"<tr><td>{html.escape(str(run.get('title') or run['check_spec_id']))}<br><small>{html.escape(run['check_spec_id'])}</small></td>"
            f"<td><span class='status {run['status']}'>"
            f"{html.escape(status_labels.get(run['status'], run['status']))}</span></td>"
            f"<td>{html.escape(_readable_reason(run))}</td></tr>"
            for run in audit["check_runs"]
            if run.get("check_spec_id") not in {
                "journey-transition-reachability", "entry-and-resume-continuity",
                "transaction-context-continuity", "interaction-feedback-visibility",
                "interaction-failure-guidance", "transition-intent-result-consistency",
            }
        )
        interaction_rows = "".join(
            "<tr>"
            f"<td>{_interaction_target(item, index)}</td>"
            f"<td class='transition-result'>{_interaction_result(item, audit['check_runs'])}</td>"
            f"<td>{_interaction_outcome(item)}</td>"
            f"<td>{html.escape({'navigation': '页面跳转', 'disclosure': '展开内容', 'local_state': '本页交互', 'unknown': '待确认交互'}.get(item['candidate'].get('kind'), item['candidate'].get('kind', '')))}<br>"
            f"{html.escape(str(item['candidate'].get('decision_reason') or ''))}</td>"
            f"<td>{_interaction_images(item)}</td>"
            "</tr>"
            for index, item in enumerate(audit.get("interaction_traces", []), 1)
        ) or "<tr><td colspan='5'>未采集页面交互记录，不能据此判断页面没有可点击控件。</td></tr>"
        evidence_images = section.get("evidence_screenshots", [])
        if evidence_images:
            image = "<div class='evidence-gallery'>" + "".join(
                f"<figure><figcaption>{html.escape(item['label'])}</figcaption><img src='{html.escape(item['path'])}' alt='{html.escape(item['label'])}'></figure>"
                for item in evidence_images
            ) + "</div>"
        else:
            screenshot = section.get("annotated_screenshot") or section.get("screenshot")
            image = f"<img src='{html.escape(screenshot)}' alt='带问题定位框的页面全页截图'>" if screenshot else "<div class='empty'>无截图</div>"
        return f"""<!doctype html>
<html lang='zh-CN'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>{html.escape(section["title"])} · 页面体验检查</title>
<style>
:root{{--ink:#172033;--muted:#667085;--line:#d7dde7;--paper:#fff;--wash:#f3f6fa;--navy:#173b63;--cyan:#087f8c;--amber:#b66500;--red:#b4232a;--green:#147a5c}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--wash);color:var(--ink);font-family:"IBM Plex Sans","PingFang SC","Microsoft YaHei",sans-serif;line-height:1.55}}
header{{background:var(--navy);color:#fff;padding:30px max(24px,calc((100vw - 1320px)/2)) 26px}} .eyebrow{{font:700 12px ui-monospace,monospace;letter-spacing:.12em;color:#9de0e4}}
h1{{margin:6px 0 8px;font-size:clamp(26px,4vw,44px);line-height:1.08}} .url{{color:#cbd8e6;font-size:13px;word-break:break-all}}
main{{max-width:1320px;margin:auto;padding:24px}} .metrics{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:22px}}
.metric,.panel{{background:var(--paper);border:1px solid var(--line);border-radius:10px}} .metric{{padding:16px;border-top:4px solid var(--cyan)}} .metric b{{display:block;font:700 30px ui-monospace,monospace}} .metric span{{color:var(--muted);font-size:13px}}
.page-ribbon{{display:flex;gap:14px;align-items:center;padding:16px 18px;margin-bottom:18px;background:#e7f2f4;border-left:6px solid var(--cyan)}} .page-ribbon strong{{font-size:18px}} .page-ribbon span{{color:var(--muted)}}
.grid{{display:grid;grid-template-columns:minmax(0,1.25fr) minmax(340px,.75fr);gap:20px;align-items:start}} .panel{{padding:18px;margin-bottom:18px}} h2{{font-size:19px;margin:0 0 14px}} img{{width:100%;border:1px solid var(--line);border-radius:7px}} .evidence-gallery{{display:grid;gap:16px}} .evidence-gallery figure{{margin:0}} .evidence-gallery figcaption{{font-size:13px;font-weight:700;margin:0 0 7px;color:var(--muted)}}
.finding{{border:1px solid var(--line);border-left:5px solid var(--amber);padding:15px;margin:12px 0;background:#fff}} .finding.p0,.finding.p1{{border-left-color:var(--red)}} .finding.p2{{border-left-color:var(--green)}} .finding-head{{display:flex;gap:10px;align-items:center}} .finding-head span{{font:700 12px ui-monospace,monospace;color:var(--amber)}} .finding h3{{font-size:16px;margin:0}} dl{{display:grid;grid-template-columns:58px 1fr;gap:6px 10px;font-size:13px}} dt{{color:var(--muted)}} dd{{margin:0}}
.finding-head .marker{{display:inline-grid;place-items:center;min-width:28px;height:28px;border-radius:50%;background:var(--red);color:white;font:700 13px ui-monospace,monospace}} .locate{{margin:10px 0;padding:10px;background:#fff4f3;border:1px solid #fecdca;font-size:12px}} .locate a{{color:var(--red);font-weight:700;text-decoration:none}} .locate code{{display:block;margin-top:5px;white-space:normal;word-break:break-all}}
table{{width:100%;border-collapse:collapse;font-size:13px}} th,td{{padding:10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}} th{{color:var(--muted)}} .status{{font:700 11px ui-monospace,monospace}} .pass{{color:var(--green)}} .fail{{color:var(--red)}} .needs_verification{{color:var(--amber)}} .error{{color:var(--muted)}} .empty{{padding:24px;color:var(--muted);text-align:center;border:1px dashed var(--line)}}
.interaction-shot{{display:inline-flex;position:relative;width:78px;height:52px;margin:0 4px 4px 0;overflow:hidden;border:1px solid var(--line);border-radius:4px}} .interaction-shot img{{width:100%;height:100%;object-fit:cover;border:0}} .interaction-shot span{{position:absolute;right:2px;bottom:2px;padding:0 4px;border-radius:3px;background:#172033cc;color:#fff;font-size:11px}} .table-scroll{{overflow-x:auto}} .transition-result{{min-width:260px}} .transition-result div{{margin:8px 0}} .transition-result span{{color:var(--muted);font-size:12px}} .transition-status{{display:inline-block;padding:2px 7px;border-radius:999px;font-size:12px;font-weight:700}} .transition-status.pass{{background:#e8f7ef;color:var(--green)}} .transition-status.fail,.transition-status.error{{background:#fff0ef;color:var(--red)}} .transition-status.needs_verification,.transition-status.skipped{{background:#fff7e6;color:var(--amber)}} .transition-count{{margin-left:5px;color:var(--muted);font-size:12px}}
.interaction-table{{table-layout:fixed}} .interaction-table td{{overflow-wrap:anywhere}} .interaction-table th:nth-child(1){{width:24%}} .interaction-table th:nth-child(2){{width:24%}} .interaction-table th:nth-child(3){{width:28%}} .interaction-table th:nth-child(4){{width:14%}} .interaction-table th:nth-child(5){{width:10%}} .control-shot{{display:block;width:100%;max-height:170px;object-fit:contain;margin-top:8px}} .control-context{{font-size:12px;color:var(--muted);margin-top:6px}} .revealed-content{{white-space:pre-wrap;max-height:280px;overflow:auto;margin-top:8px}} .interaction-table .transition-status{{font-size:14px;font-weight:700}} .interaction-table .transition-result{{min-width:0}}
@media(max-width:850px){{.metrics{{grid-template-columns:1fr 1fr}}.grid{{grid-template-columns:1fr}}.interaction-table{{min-width:950px}}}} @media(max-width:520px){{.metrics{{grid-template-columns:1fr}}main{{padding:14px}}}}
</style></head><body>
<header><div class='eyebrow'>PAGE ASSESSMENT · {html.escape(audit["run"]["job_id"])}</div><h1>{html.escape(section["title"])}</h1><div class='url'>{html.escape(section["url"])}</div></header>
<main><section class='metrics'><div class='metric'><b>{summary["issue_count"]}</b><span>问题总数</span></div><div class='metric'><b>{summary["p0"]}</b><span>阻断问题</span></div><div class='metric'><b>{summary["p1"]}</b><span>重要问题</span></div><div class='metric'><b>{summary["p2"]}</b><span>建议问题</span></div></section>
<div class='page-ribbon'><strong>{html.escape(section["name"])}</strong><span>{html.escape(section["coverage_status"]["status"])} · 登录状态 {html.escape(section["authentication"]["status"])} · 页面是主要结果对象</span></div>
<section class='panel'><h2>页面交互与跳转</h2><p>橙框表示点击位置；检查结论区分通过、发现问题、待确认和未执行。</p><div class='table-scroll'><table class='interaction-table'><thead><tr><th>点击对象与位置</th><th>检查结论</th><th>实际结果／展开内容</th><th>交互类型与执行说明</th><th>前后证据</th></tr></thead><tbody>{interaction_rows}</tbody></table></div></section>
<div class='grid'><div><section class='panel' id='evidence-map'><h2>问题证据地图</h2>{image}</section><section class='panel'><h2>详细检查</h2><table><thead><tr><th>检查规则</th><th>结果</th><th>依据</th></tr></thead><tbody>{check_rows}</tbody></table></section></div>
<aside><section class='panel'><h2>页面问题</h2>{issue_rows}</section><section class='panel'><h2>页面上下文</h2><pre>{html.escape(json.dumps(audit["pages"][0]["context"], ensure_ascii=False, indent=2))}</pre></section></aside></div></main></body></html>"""

    def _report_html(self, audit: dict) -> str:
        """Render a review flow: one issue register, then supporting evidence."""
        section, summary = audit["sections"][0], audit["summary"]
        status_labels = {"pass": "通过", "fail": "发现问题", "needs_verification": "待确认", "error": "未执行"}
        pricing_summary, pricing_rows = _pricing_review(audit)
        transition_issues = "".join(
            _transition_issue_html(item, index, audit["check_runs"])
            for index, item in enumerate(audit.get("interaction_traces", []), 1)
        )
        page_issues = "".join(
            self._finding_html(item, _page_issue_screenshot(item, section, audit))
            for item in audit["issues"]
        )
        all_issues = page_issues + transition_issues or "<div class='empty'>当前证据下未发现需要处理的问题。</div>"
        issue_count = len(audit["issues"]) + sum(bool(_transition_issue_html(item, index, audit["check_runs"])) for index, item in enumerate(audit.get("interaction_traces", []), 1))
        transition_failures = sum(
            "finding transition-finding fail" in _transition_issue_html(item, index, audit["check_runs"])
            for index, item in enumerate(audit.get("interaction_traces", []), 1)
        )
        important_count = summary["p1"] + transition_failures
        suggestion_count = summary["p2"]
        check_rows = "".join(
            f"<tr><td>{html.escape(str(run.get('title') or run['check_spec_id']))}<br><small>{html.escape(run['check_spec_id'])}</small></td>"
            f"<td><span class='status {run['status']}'>{html.escape(status_labels.get(run['status'], run['status']))}</span></td>"
            f"<td>{html.escape(_readable_reason(run))}</td></tr>"
            for run in audit["check_runs"] if run.get("check_spec_id") not in {
                "journey-transition-reachability", "entry-and-resume-continuity", "transaction-context-continuity",
                "interaction-feedback-visibility", "interaction-failure-guidance", "transition-intent-result-consistency",
                *PRICING_CHECK_IDS,
            }
        )
        interaction_rows = "".join(
            "<tr id='interaction-" + str(index) + "'>"
            f"<td>{_interaction_target(item, index)}</td>"
            f"<td class='transition-result'>{_interaction_result(item, audit['check_runs'])}</td>"
            f"<td>{_interaction_outcome(item)}</td>"
            f"<td>{html.escape({'navigation': '页面跳转', 'disclosure': '展开内容', 'local_state': '本页交互', 'unknown': '待确认交互'}.get(item['candidate'].get('kind'), item['candidate'].get('kind', '')))}<br>{html.escape(str(item['candidate'].get('decision_reason') or ''))}</td>"
            f"<td>{_interaction_images(item)}</td></tr>"
            for index, item in enumerate(audit.get("interaction_traces", []), 1)
            if item.get("candidate", {}).get("kind") != "quote_configuration"
        ) or "<tr><td colspan='5'>未采集页面交互记录。</td></tr>"
        evidence_images = section.get("evidence_screenshots", [])
        if evidence_images:
            evidence = "<div class='evidence-gallery'>" + "".join(
                f"<figure><figcaption>{html.escape(item['label'])}</figcaption><img src='{html.escape(item['path'])}' alt='{html.escape(item['label'])}'></figure>"
                for item in evidence_images
            ) + "</div>"
        else:
            screenshot = section.get("annotated_screenshot") or section.get("screenshot")
            evidence = f"<img src='{html.escape(screenshot)}' alt='页面证据截图'>" if screenshot else "<div class='empty'>无截图</div>"
        return f"""<!doctype html>
<html lang='zh-CN'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>{html.escape(section['title'])} · 页面体验检查</title><style>
:root{{--ink:#182636;--muted:#64748b;--line:#dce5ec;--paper:#fff;--ground:#f4f7f8;--navy:#173b63;--teal:#087e8b;--amber:#a55e00;--red:#bb2a36;--green:#147a5c}} *{{box-sizing:border-box}} html{{scroll-behavior:smooth;scroll-padding-top:24px}} body{{margin:0;background:var(--ground);color:var(--ink);font-family:"PingFang SC","Noto Sans SC",sans-serif;line-height:1.6}} a{{color:#076f7a}} .masthead{{background:var(--navy);color:#fff;padding:30px max(28px,calc((100vw - 1420px)/2)) 28px}} .eyebrow{{font:700 12px ui-monospace,monospace;letter-spacing:.12em;color:#a7e1e4}} h1{{margin:5px 0;font-size:clamp(28px,4vw,44px);line-height:1.14}} .url{{color:#d5e3ef;font-size:13px;word-break:break-all}} .report-shell{{max-width:1420px;margin:0 auto;padding:24px 28px 60px;display:grid;grid-template-columns:205px minmax(0,1fr);gap:26px}} .side-nav{{position:sticky;top:20px;align-self:start;padding:15px 0;border-left:2px solid #c8d9df}} .side-nav a{{display:block;padding:7px 14px;color:var(--muted);text-decoration:none;font-size:13px}} .side-nav a:hover,.side-nav a:focus{{color:var(--teal);font-weight:700;outline:none}} .side-nav .nav-title{{padding:0 14px 8px;font:700 11px ui-monospace,monospace;letter-spacing:.1em;color:var(--teal)}} .content{{min-width:0}} .overview{{display:grid;grid-template-columns:1.4fr repeat(3,.55fr);gap:10px;margin-bottom:20px}} .summary-lead,.metric,.panel{{background:var(--paper);border:1px solid var(--line);border-radius:10px}} .summary-lead{{padding:17px 20px;border-left:5px solid var(--teal)}} .summary-lead b{{display:block;font-size:18px}} .summary-lead span,.metric span{{font-size:13px;color:var(--muted)}} .metric{{padding:13px 15px}} .metric b{{display:block;font:700 28px ui-monospace,monospace}} .panel{{padding:22px;margin-bottom:20px}} h2{{margin:0 0 5px;font-size:21px}} .section-note{{margin:0 0 16px;color:var(--muted);font-size:13px}} .finding-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:12px}} .finding{{border:1px solid var(--line);border-left:5px solid var(--amber);padding:15px;background:#fff}} .finding.p0,.finding.p1,.finding.fail{{border-left-color:var(--red)}} .finding.p2,.finding.needs_verification{{border-left-color:var(--amber)}} .finding-head{{display:flex;gap:9px;align-items:center}} .finding-head .marker{{display:inline-grid;place-items:center;min-width:34px;height:26px;padding:0 6px;border-radius:14px;background:var(--red);color:#fff;font:700 11px ui-monospace,monospace}} .finding-head span{{font:700 11px ui-monospace,monospace;color:var(--amber)}} .finding h3{{margin:0;font-size:16px;line-height:1.35}} .finding p{{font-size:14px}} .finding dl{{display:grid;grid-template-columns:42px 1fr;gap:5px 10px;font-size:13px;margin:11px 0 0}} dt{{color:var(--muted)}} dd{{margin:0}} .locate{{margin:10px 0;padding:8px 10px;background:#fdf4ef;border:1px solid #f2d1c4;font-size:12px}} .locate a{{font-weight:700;text-decoration:none}} .locate code{{display:block;margin-top:4px;word-break:break-all;white-space:normal}} table{{width:100%;border-collapse:collapse;font-size:13px}} th,td{{padding:11px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}} th{{color:var(--muted);font-weight:700}} .table-scroll{{overflow:auto}} .status{{font:700 12px ui-monospace,monospace}} .pass{{color:var(--green)}} .fail{{color:var(--red)}} .needs_verification{{color:var(--amber)}} .error{{color:var(--muted)}} .empty{{padding:24px;color:var(--muted);text-align:center;border:1px dashed var(--line)}} .interaction-table{{min-width:1040px;table-layout:fixed}} .interaction-table th:nth-child(1){{width:25%}} .interaction-table th:nth-child(2){{width:25%}} .interaction-table th:nth-child(3){{width:26%}} .interaction-table th:nth-child(4){{width:14%}} .interaction-table th:nth-child(5){{width:10%}} .interaction-table tr:target{{background:#fff9e9}} .transition-result div{{margin:7px 0}} .transition-result span{{font-size:12px;color:var(--muted)}} .transition-status{{display:inline-block;padding:2px 7px;border-radius:999px;font-size:12px;font-weight:700}} .transition-status.pass{{background:#e8f7ef}} .transition-status.fail,.transition-status.error{{background:#fff0ef}} .transition-status.needs_verification,.transition-status.skipped{{background:#fff7e6}} .transition-count{{margin-left:5px;color:var(--muted);font-size:12px}} .control-shot{{display:block;width:100%;max-height:170px;object-fit:contain;margin-top:8px;border:1px solid var(--line);border-radius:5px}} .control-context{{font-size:12px;color:var(--muted);margin-top:6px}} .interaction-shot{{display:inline-flex;position:relative;width:78px;height:52px;margin:0 4px 4px 0;overflow:hidden;border:1px solid var(--line);border-radius:4px}} .interaction-shot img{{width:100%;height:100%;object-fit:cover;border:0}} .interaction-shot span{{position:absolute;right:2px;bottom:2px;padding:0 4px;border-radius:3px;background:#172033cc;color:#fff;font-size:11px}} .revealed-content{{white-space:pre-wrap;max-height:280px;overflow:auto;margin-top:8px}} .support-grid{{display:grid;grid-template-columns:minmax(0,1.25fr) minmax(300px,.75fr);gap:20px}} .evidence-gallery{{display:grid;gap:16px}} .evidence-gallery figure{{margin:0}} .evidence-gallery figcaption{{font-size:13px;font-weight:700;margin-bottom:7px;color:var(--muted)}} img{{max-width:100%;border:1px solid var(--line);border-radius:7px}} pre{{margin:0;overflow:auto;background:#f6f8fa;padding:13px;font-size:12px}} @media(max-width:900px){{.report-shell{{display:block;padding:16px}} .side-nav{{position:sticky;top:0;z-index:2;display:flex;overflow:auto;background:var(--ground);border-left:0;border-bottom:1px solid var(--line);margin-bottom:16px;padding:8px 0}} .side-nav .nav-title{{display:none}} .side-nav a{{white-space:nowrap;padding:6px 10px}} .overview{{grid-template-columns:1fr 1fr}} .summary-lead{{grid-column:1/-1}} .support-grid{{grid-template-columns:1fr}}}} @media(max-width:520px){{.masthead{{padding:24px 16px}} .finding-grid,.overview{{grid-template-columns:1fr}} .panel{{padding:16px}}}}
</style><style>
/* The issue register is deliberately a scanable, one-row-per-item review list. */
.finding-list{{display:grid;gap:10px}}
.finding{{display:grid;grid-template-columns:66px minmax(0,1fr) 250px;gap:16px;align-items:start;padding:16px;border-left-width:5px}}
.finding-key{{display:grid;gap:5px;align-content:start;font:700 11px ui-monospace,monospace;color:var(--amber)}}
.finding-key .marker{{display:inline-grid;place-items:center;min-width:44px;width:max-content;height:26px;padding:0 7px;border-radius:14px;background:var(--red);color:#fff}}
.finding-body{{min-width:0}} .finding-body h3{{margin:0;font-size:16px;line-height:1.35}} .finding-body p{{margin:10px 0;font-size:14px}}
.finding-body .locate{{margin:10px 0}} .finding-body dl{{margin-top:10px}}
.issue-visual{{display:block;min-height:112px;background:#f6f8fa;border:1px solid var(--line);border-radius:7px;overflow:hidden;color:var(--teal);font-size:13px;text-decoration:none}}
.issue-visual img{{display:block;width:100%;height:166px;object-fit:cover;border:0;border-radius:0}}
.empty-visual{{display:grid;place-items:center;padding:12px;text-align:center}}
.support-grid{{display:block}} #checks table{{table-layout:fixed}} #checks th:nth-child(1){{width:28%}} #checks th:nth-child(2){{width:14%}} #checks td{{overflow-wrap:anywhere;word-break:break-word}}
.pricing-table{{min-width:980px;table-layout:fixed}} .pricing-table th:nth-child(1){{width:20%}} .pricing-table th:nth-child(2){{width:11%}} .pricing-table th:nth-child(3){{width:30%}} .pricing-table th:nth-child(4){{width:10%}} .pricing-table th:nth-child(5){{width:29%}} .pricing-table .money{{font:700 13px ui-monospace,SFMono-Regular,Consolas,monospace;white-space:nowrap}} .price-formula{{display:inline-block;padding:7px 9px;background:#edf6f7;border-left:3px solid var(--teal);color:#164e58;font:700 13px/1.45 ui-monospace,SFMono-Regular,Consolas,monospace;white-space:nowrap}} .price-verdict{{display:inline-block;padding:3px 8px;border-radius:999px;font-size:12px;font-weight:700}} .price-verdict.pass{{background:#e8f7ef;color:var(--green)}} .price-verdict.fail,.price-verdict.error{{background:#fff0ef;color:var(--red)}} .price-verdict.needs_verification{{background:#fff7e6;color:var(--amber)}} .pricing-table td:last-child p{{margin:7px 0 0;color:var(--muted);font-size:12px}}
@media(max-width:760px){{.finding{{grid-template-columns:58px minmax(0,1fr)}} .issue-visual{{grid-column:2;max-width:300px}}}}
</style></head><body><header class='masthead'><div class='eyebrow'>PAGE REVIEW · {html.escape(audit['run']['job_id'])}</div><h1>{html.escape(section['title'])}</h1><div class='url'>{html.escape(section['url'])}</div></header><div class='report-shell'><nav class='side-nav' aria-label='报告导航'><div class='nav-title'>报告导航</div><a href='#overview'>总览</a><a href='#issues'>所有问题</a>{"<a href='#pricing'>计价核验</a>" if pricing_rows else ""}<a href='#interactions'>交互与跳转</a><a href='#evidence'>证据地图</a><a href='#checks'>详细检查</a></nav><main class='content'><section class='overview' id='overview'><div class='summary-lead'><b>{issue_count} 个待处理事项</b><span>{html.escape(section['name'])} · 覆盖状态 {html.escape(section['coverage_status']['status'])} · 登录状态 {html.escape(section['authentication']['status'])}</span></div><div class='metric'><b>{summary['p0']}</b><span>阻断问题</span></div><div class='metric'><b>{important_count}</b><span>重要问题</span></div><div class='metric'><b>{suggestion_count}</b><span>建议／待确认</span></div></section><section class='panel' id='issues'><h2>所有问题</h2><p class='section-note'>页面检查与交互／跳转问题按行集中展示；计价问题统一放在“计价核验”表中。</p><div class='finding-list'>{all_issues}</div></section>{f"<section class='panel' id='pricing'><h2>计价核验</h2><p class='section-note'>{html.escape(pricing_summary)} 每行列出页面金额、独立复算过程和差额。</p><div class='table-scroll'><table class='pricing-table'><thead><tr><th>配置组合</th><th>页面金额</th><th>复算过程</th><th>差额</th><th>结论与说明</th></tr></thead><tbody>{pricing_rows}</tbody></table></div></section>" if pricing_rows else ""}<section class='panel' id='interactions'><h2>页面交互与跳转</h2><p class='section-note'>橙框标识点击位置；购买配置卡片已移至“计价核验”，此处仅保留其他交互记录。</p><div class='table-scroll'><table class='interaction-table'><thead><tr><th>点击对象与位置</th><th>检查结论</th><th>实际结果／展开内容</th><th>交互类型与执行说明</th><th>前后证据</th></tr></thead><tbody>{interaction_rows}</tbody></table></div></section><div class='support-grid'><section class='panel' id='evidence'><h2>问题证据地图</h2>{evidence}</section><section class='panel' id='checks'><h2>详细检查</h2><table><thead><tr><th>检查规则</th><th>结果</th><th>依据</th></tr></thead><tbody>{check_rows}</tbody></table></section></div></main></div></body></html>"""

    @staticmethod
    def _finding_html(item: dict, screenshot: str | None = None) -> str:
        locate_values = item.get("locate", [])
        locate = (
            "<a href='#evidence'>在截图中查看定位框</a>"
            + "".join(f"<code>{html.escape(value)}</code>" for value in locate_values[:3])
            if locate_values
            else "缺失型或技术型问题：当前没有可框选的页面元素。"
        )
        standards = OutputWriter._standard_refs_html(item.get("standard_refs", []))
        verification = (
            "待人工确认" if item.get("verification_status") == "pending" else "已复核"
        )
        visual = (
            f"<a class='issue-visual' href='#evidence'><img src='{html.escape(str(screenshot))}' alt='{html.escape(item['title'])} 的页面证据'></a>"
            if screenshot else "<a class='issue-visual empty-visual' href='#evidence'>查看页面证据</a>"
        )
        return (
            f"<article class='finding {item['severity']}'><div class='finding-key'>"
            f"<span class='marker'>{item['marker']}</span><span>{html.escape(item['severity'].upper())}</span></div>"
            f"<div class='finding-body'><h3>{html.escape(item['title'])}</h3><div class='locate'>{locate}</div>"
            f"<p>{html.escape(item['evidence'])}</p><dl><dt>规范</dt>"
            f"<dd>{standards}</dd><dt>建议</dt>"
            f"<dd>{html.escape(item['suggestion_after'])}</dd><dt>置信度</dt>"
            f"<dd>{item['confidence']:.0%}</dd><dt>状态</dt>"
            f"<dd>{verification}</dd></dl></div>{visual}</article>"
        )

    @staticmethod
    def _standard_refs_html(references: list[dict]) -> str:
        if not references:
            return "未映射规范来源"
        relation_labels = {
            "implements": "直接实现",
            "partial_coverage": "部分覆盖",
            "supports": "提供支持证据",
            "inspired_by": "参考",
        }
        rows = []
        for ref in references:
            source = ref.get("source_name") or ref.get("source_id", "规范来源")
            criterion = ref.get("criterion_title") or ref.get("criterion_id", "")
            criterion_code = str(ref.get("criterion_id", "")).split("/", 1)[-1]
            level = f" · {ref['criterion_level']}级" if ref.get("criterion_level") else ""
            relation = relation_labels.get(ref.get("relation", ""), ref.get("relation", ""))
            rows.append(
                f"<div><strong>{html.escape(source)}</strong> · "
                f"{html.escape(criterion_code)} {html.escape(criterion)}{level} · "
                f"{html.escape(relation)}</div>"
            )
        return "".join(rows)
