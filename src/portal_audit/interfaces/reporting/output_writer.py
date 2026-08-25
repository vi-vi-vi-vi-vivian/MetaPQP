"""Generate compatible audit.json and a page-first standalone report.html."""

from __future__ import annotations

import base64
import html
import json
from pathlib import Path

from portal_audit.application.services.run_paths import page_run_relative_dir
from portal_audit.domain.models import AuditResult, Severity
from portal_audit.domain.registry import StandardsRegistry


class OutputWriter:
    def __init__(
        self,
        output_root: Path,
        *,
        model_name: str,
        model_enabled: bool,
        standards: StandardsRegistry | None = None,
    ):
        self.output_root = output_root
        self.model_name = model_name
        self.model_enabled = model_enabled
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
        (run_dir / "report.html").write_text(self._report_html(payload), encoding="utf-8")
        return run_dir

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
                    "marker": len(issues) + 1,
                }
            )
        annotated_screenshot = self._write_annotated_screenshot(
            run_dir,
            screenshot,
            result.snapshot.document_size or result.snapshot.viewport,
            issues,
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
            "calls": [call.model_dump(mode="json") for call in result.model_calls],
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

    def _report_html(self, audit: dict) -> str:
        section = audit["sections"][0]
        summary = audit["summary"]
        issue_rows = (
            "".join(self._finding_html(item) for item in audit["issues"])
            or "<div class='empty'>当前证据下未发现问题。</div>"
        )
        check_rows = "".join(
            f"<tr><td>{html.escape(run['check_spec_id'])}</td><td><span class='status {run['status']}'>{html.escape(run['status'])}</span></td><td>{html.escape(run['reason'])}</td></tr>"
            for run in audit["check_runs"]
        )
        screenshot = section.get("annotated_screenshot") or section.get("screenshot")
        image = (
            f"<img src='{html.escape(screenshot)}' alt='带问题定位框的页面全页截图'>"
            if screenshot
            else "<div class='empty'>无截图</div>"
        )
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
.grid{{display:grid;grid-template-columns:minmax(0,1.25fr) minmax(340px,.75fr);gap:20px;align-items:start}} .panel{{padding:18px;margin-bottom:18px}} h2{{font-size:19px;margin:0 0 14px}} img{{width:100%;border:1px solid var(--line);border-radius:7px}}
.finding{{border:1px solid var(--line);border-left:5px solid var(--amber);padding:15px;margin:12px 0;background:#fff}} .finding.p0,.finding.p1{{border-left-color:var(--red)}} .finding.p2{{border-left-color:var(--green)}} .finding-head{{display:flex;gap:10px;align-items:center}} .finding-head span{{font:700 12px ui-monospace,monospace;color:var(--amber)}} .finding h3{{font-size:16px;margin:0}} dl{{display:grid;grid-template-columns:58px 1fr;gap:6px 10px;font-size:13px}} dt{{color:var(--muted)}} dd{{margin:0}}
.finding-head .marker{{display:inline-grid;place-items:center;min-width:28px;height:28px;border-radius:50%;background:var(--red);color:white;font:700 13px ui-monospace,monospace}} .locate{{margin:10px 0;padding:10px;background:#fff4f3;border:1px solid #fecdca;font-size:12px}} .locate a{{color:var(--red);font-weight:700;text-decoration:none}} .locate code{{display:block;margin-top:5px;white-space:normal;word-break:break-all}}
table{{width:100%;border-collapse:collapse;font-size:13px}} th,td{{padding:10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}} th{{color:var(--muted)}} .status{{font:700 11px ui-monospace,monospace}} .pass{{color:var(--green)}} .fail{{color:var(--red)}} .needs_verification{{color:var(--amber)}} .empty{{padding:24px;color:var(--muted);text-align:center;border:1px dashed var(--line)}}
@media(max-width:850px){{.metrics{{grid-template-columns:1fr 1fr}}.grid{{grid-template-columns:1fr}}}} @media(max-width:520px){{.metrics{{grid-template-columns:1fr}}main{{padding:14px}}}}
</style></head><body>
<header><div class='eyebrow'>PAGE ASSESSMENT · {html.escape(audit["run"]["job_id"])}</div><h1>{html.escape(section["title"])}</h1><div class='url'>{html.escape(section["url"])}</div></header>
<main><section class='metrics'><div class='metric'><b>{summary["issue_count"]}</b><span>问题总数</span></div><div class='metric'><b>{summary["p0"]}</b><span>阻断问题</span></div><div class='metric'><b>{summary["p1"]}</b><span>重要问题</span></div><div class='metric'><b>{summary["p2"]}</b><span>建议问题</span></div></section>
<div class='page-ribbon'><strong>{html.escape(section["name"])}</strong><span>{html.escape(section["coverage_status"]["status"])} · 登录状态 {html.escape(section["authentication"]["status"])} · 页面是主要结果对象</span></div>
<div class='grid'><div><section class='panel' id='evidence-map'><h2>问题证据地图</h2>{image}</section><section class='panel'><h2>详细检查</h2><table><thead><tr><th>检查规则</th><th>结果</th><th>依据</th></tr></thead><tbody>{check_rows}</tbody></table></section></div>
<aside><section class='panel'><h2>页面问题</h2>{issue_rows}</section><section class='panel'><h2>页面上下文</h2><pre>{html.escape(json.dumps(audit["pages"][0]["context"], ensure_ascii=False, indent=2))}</pre></section></aside></div></main></body></html>"""

    @staticmethod
    def _finding_html(item: dict) -> str:
        locate_values = item.get("locate", [])
        locate = (
            "<a href='#evidence-map'>在截图中查看定位框</a>"
            + "".join(f"<code>{html.escape(value)}</code>" for value in locate_values[:3])
            if locate_values
            else "缺失型或技术型问题：当前没有可框选的页面元素。"
        )
        standards = OutputWriter._standard_refs_html(item.get("standard_refs", []))
        return (
            f"<article class='finding {item['severity']}'><div class='finding-head'>"
            f"<span class='marker'>{item['marker']}</span><span>{html.escape(item['severity'].upper())}</span>"
            f"<h3>{html.escape(item['title'])}</h3></div><div class='locate'>{locate}</div>"
            f"<p>{html.escape(item['evidence'])}</p><dl><dt>规范</dt>"
            f"<dd>{standards}</dd><dt>建议</dt>"
            f"<dd>{html.escape(item['suggestion_after'])}</dd><dt>置信度</dt>"
            f"<dd>{item['confidence']:.0%}</dd></dl></article>"
        )

    @staticmethod
    def _standard_refs_html(references: list[dict]) -> str:
        if not references:
            return "未映射规范来源"
        labels = {
            "external_standard": "外部标准",
            "external_heuristic": "可用性启发式",
            "internal_guidance": "内部检查建议",
            "organization_standard": "组织设计规范",
        }
        rows = []
        for ref in references:
            source_type = ref.get("source_type")
            category = labels.get(source_type, "规范引用")
            criterion = ref.get("criterion_title") or ref.get("criterion_id", "")
            relation = ref.get("relation", "")
            rows.append(
                f"<div><strong>{html.escape(category)}</strong> · "
                f"{html.escape(criterion)} · {html.escape(relation)}</div>"
            )
        return "".join(rows)
