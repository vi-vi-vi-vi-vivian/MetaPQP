"""Write a compact Journey bundle and standalone HTML report."""

from __future__ import annotations

import base64
import html
import json
import mimetypes
import os
import re
from pathlib import Path

from PIL import Image, ImageDraw

from portal_audit.domain.models import CheckStatus, JourneyAuditResult


class JourneyOutputWriter:
    def __init__(self, output_root: Path, check_specs=None, standards=None):
        self.output_root = output_root
        self.check_specs = check_specs
        self.standards = standards

    def write(self, result: JourneyAuditResult) -> Path:
        run_dir = (
            self.output_root
            / "journeys"
            / _safe_segment(result.journey.id)
            / _safe_segment(result.job_id)
        )
        run_dir.mkdir(parents=True, exist_ok=True)
        pages = [
            {
                "page_id": item.target.page_id,
                "node_id": item.target.page_map_node_id,
                "url": item.snapshot.final_url,
                "title": item.snapshot.title,
                "coverage_status": item.assessment.coverage_status.value,
                "issue_count": len(item.assessment.findings),
                "output_dir": item.output_dir,
                "report": os.path.relpath(
                    str(Path(item.output_dir or "") / "report.html"),
                    run_dir,
                ),
            }
            for item in result.page_results
        ]
        journey_check_runs = []
        for run in result.journey_check_runs:
            run_payload = self._journey_run_payload(run)
            run_payload["evidence_screenshots"] = self._write_issue_screenshots(
                run_dir,
                run,
                result.page_results,
            )
            journey_check_runs.append(run_payload)
        payload = {
            "schema_version": "1.0",
            "job_id": result.job_id,
            "request": result.request.model_dump(mode="json"),
            "journey": result.journey.model_dump(mode="json"),
            "status": result.status.value,
            "coverage_status": result.coverage_status.value,
            "termination_reason": result.termination_reason,
            "transition_trace": result.transition_trace.model_dump(mode="json"),
            "transition_traces": [
                item.model_dump(mode="json")
                for item in (result.transition_traces or [result.transition_trace])
            ],
            "transition_check_runs": [
                item.model_dump(mode="json") for item in result.transition_check_runs
            ],
            "journey_evidence": (
                result.journey_evidence.model_dump(mode="json")
                if result.journey_evidence else None
            ),
            "journey_check_plan": (
                result.journey_check_plan.model_dump(mode="json")
                if result.journey_check_plan else None
            ),
            "journey_check_runs": journey_check_runs,
            "journey_assessment": (
                result.journey_assessment.model_dump(mode="json")
                if result.journey_assessment else None
            ),
            "journey_model_calls": [
                item.model_dump(mode="json") for item in result.journey_model_calls
            ],
            "pages": pages,
        }
        (run_dir / "audit.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        (run_dir / "report.html").write_text(
            self._report_html(self._standalone_payload(payload, run_dir)),
            encoding="utf-8",
        )
        return run_dir

    def bundle_existing(self, run_dir: Path) -> Path:
        """Rewrite an already generated Journey report as one portable HTML file.

        This is intentionally based on ``audit.json`` so historic Journey
        results can be made portable without rerunning browser or model checks.
        The original Page report directories must still be available when this
        method is called; afterwards the Journey ``report.html`` is standalone.
        """
        payload = json.loads((run_dir / "audit.json").read_text(encoding="utf-8"))
        report_path = run_dir / "report.html"
        report_path.write_text(
            self._report_html(self._standalone_payload(payload, run_dir)),
            encoding="utf-8",
        )
        return report_path

    def _standalone_payload(self, payload: dict, run_dir: Path) -> dict:
        """Embed local screenshots and Page reports without changing audit.json."""
        embedded = json.loads(json.dumps(payload, ensure_ascii=False))
        for page in embedded.get("pages", []):
            report_path = Path(page.get("output_dir") or "") / "report.html"
            if report_path.is_file():
                page["embedded_report"] = _as_data_uri(
                    self._inline_report_images(report_path),
                    "text/html",
                )
        for run in embedded.get("journey_check_runs", []):
            for screenshot in run.get("evidence_screenshots", []):
                source = run_dir / str(screenshot.get("path") or "")
                if source.is_file():
                    screenshot["data_uri"] = _file_data_uri(source)
        return embedded

    @staticmethod
    def _inline_report_images(report_path: Path) -> bytes:
        """Replace local image references in a Page report with data URIs."""
        document = report_path.read_text(encoding="utf-8")

        def replace(match: re.Match[str]) -> str:
            attribute, quote, value = match.group(1), match.group(2), match.group(3)
            if value.startswith(("data:", "http://", "https://", "#", "/")):
                return match.group(0)
            asset = report_path.parent / value
            if not asset.is_file() or asset.suffix.lower() not in {
                ".svg", ".png", ".jpg", ".jpeg", ".webp", ".gif",
            }:
                return match.group(0)
            return f"{attribute}={quote}{_file_data_uri(asset)}{quote}"

        inlined = re.sub(
            r"\b(src|href)\s*=\s*(['\"])([^'\"]+)\2",
            replace,
            document,
            flags=re.IGNORECASE,
        )
        return inlined.encode("utf-8")

    def _journey_run_payload(self, run) -> dict:
        payload = run.model_dump(mode="json")
        payload["standard_refs"] = []
        if self.check_specs is not None and self.standards is not None:
            spec = self.check_specs.get(run.check_spec_id)
            payload["standard_refs"] = [
                self.standards.resolve(reference) for reference in spec.standard_refs
            ]
        return payload

    def _write_issue_screenshots(self, run_dir: Path, run, page_results) -> list[dict]:
        """Write annotated crops only for confirmed cross-stage issues."""
        if run.status != CheckStatus.FAIL:
            return []

        page_by_node = {
            item.target.page_map_node_id: item
            for item in page_results
            if item.target.page_map_node_id
        }
        screenshots: list[dict] = []
        screenshot_dir = run_dir / "screenshots"
        for node_id in run.subject_node_ids:
            page_result = page_by_node.get(node_id)
            if page_result is None:
                continue
            locations = self._locate_issue_evidence(run, node_id, page_result.snapshot)
            source = next(
                (
                    Path(artifact.path)
                    for artifact in page_result.snapshot.artifacts
                    if artifact.kind == "screenshot" and Path(artifact.path).is_file()
                ),
                None,
            )
            if source is None:
                continue

            screenshot_dir.mkdir(parents=True, exist_ok=True)
            output = screenshot_dir / (
                f"{_safe_segment(run.check_spec_id)}-{_safe_segment(node_id)}.png"
            )
            absence = self._node_describes_absence(run, node_id)
            precision = "comparison" if absence and locations else (
                "element" if locations else "context"
            )
            written = (
                self._annotate_crop(
                    source,
                    output,
                    locations,
                    page_result.snapshot.document_size,
                    draw_annotations=not absence,
                )
                if locations
                else self._write_context_screenshot(source, output)
            )
            if not written:
                continue
            screenshots.append(
                {
                    "node_id": node_id,
                    "path": os.path.relpath(output, run_dir),
                    "caption": (
                        f"{page_result.snapshot.title}：缺失对照区域"
                        if absence and locations
                        else f"{page_result.snapshot.title}：问题证据位置"
                        if locations
                        else f"{page_result.snapshot.title}：问题对照页面上下文"
                    ),
                    "precision": precision,
                    "locations": locations,
                }
            )
        return screenshots

    @staticmethod
    def _node_describes_absence(run, node_id: str) -> bool:
        evidence = "\n".join(
            str(value)
            for value in run.evidence
            if node_id.casefold() in str(value).casefold()
        )
        absence_terms = (
            "未包含",
            "未展示",
            "未提供",
            "未保留",
            "未出现",
            "不存在",
            "缺失",
            "消失",
            "去除",
            "没有",
            "absent",
            "missing",
            "removed",
        )
        folded = evidence.casefold()
        return any(term.casefold() in folded for term in absence_terms)

    @staticmethod
    def _locate_issue_evidence(run, node_id: str, snapshot) -> list[dict]:
        node_evidence = [
            str(value)
            for value in run.evidence
            if node_id.casefold() in str(value).casefold()
        ]
        evidence = node_evidence or [str(value) for value in run.evidence]
        narrative = "\n".join([run.reason, *evidence])
        quoted = {
            value.strip()
            for value in re.findall(r"[“‘\"']([^”’\"']{2,40})[”’\"']", narrative)
        }
        generic_terms = {
            "页面",
            "产品",
            "套餐",
            "购买",
            "订阅",
            "开通",
            "使用",
            "阶段",
            "page",
            "product",
            "plan",
            "purchase",
        }
        identifiers = {
            value
            for value in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", narrative)
            if value.casefold() not in generic_terms
        }
        ranked: list[tuple[int, int, dict]] = []
        for element in snapshot.evidence_elements:
            if not element.bounds:
                continue
            candidates = [
                element.text.strip(),
                element.accessible_name.strip(),
                element.surrounding_text.strip(),
            ]
            candidates = [value for value in candidates if len(value) >= 2]
            if not candidates:
                continue
            score = 0
            best_text = candidates[0]
            for value in candidates:
                candidate_score = 0
                if value in narrative and value.casefold() not in generic_terms:
                    candidate_score = max(
                        candidate_score,
                        8 + min(len(value), 30),
                    )
                for phrase in quoted:
                    if phrase == value:
                        candidate_score = max(
                            candidate_score,
                            100 + min(len(phrase), 30),
                        )
                    elif phrase in value or value in phrase:
                        candidate_score = max(
                            candidate_score,
                            35 + min(len(phrase), 30),
                        )
                for identifier in identifiers:
                    if identifier.casefold() in value.casefold():
                        candidate_score = max(
                            candidate_score,
                            25 + min(len(identifier), 20),
                        )
                if candidate_score > score:
                    score = candidate_score
                    best_text = value
            if score == 0:
                continue
            bounds = {key: float(value) for key, value in element.bounds.items()}
            ranked.append(
                (
                    score,
                    len(best_text),
                    {
                        "element_ref": element.element_ref,
                        "text": best_text[:120],
                        "bounds": bounds,
                    },
                )
            )

        selected: list[dict] = []
        seen_bounds: set[tuple[int, int, int, int]] = set()
        ordered = sorted(
            ranked,
            key=lambda item: (item[0], item[1]),
            reverse=True,
        )
        exact_evidence_found = bool(ordered and ordered[0][0] >= 100)
        for score, _, location in ordered:
            if exact_evidence_found and score < 100:
                continue
            bounds = location["bounds"]
            key = tuple(
                round(bounds.get(name, 0)) for name in ("x", "y", "width", "height")
            )
            if key in seen_bounds:
                continue
            seen_bounds.add(key)
            selected.append(location)
            if len(selected) == 2:
                break
        if not selected:
            nearby_action = JourneyOutputWriter._locate_nearby_action(
                snapshot,
                [
                    *sorted(quoted, key=narrative.find),
                    *sorted(identifiers, key=narrative.find),
                ],
            )
            if nearby_action:
                selected.append(nearby_action)
        return selected

    @staticmethod
    def _locate_nearby_action(snapshot, anchor_terms: list[str]) -> dict | None:
        """Map text-only evidence to the nearest following repeated page action."""
        lines = [
            re.sub(r"\s+", " ", value).strip()
            for value in re.split(r"[\n\r]+", snapshot.body_text)
            if value.strip()
        ]
        actions = [
            item
            for item in snapshot.interactive_elements
            if item.bounds and item.text.strip()
        ]
        if not lines or not actions:
            return None
        for anchor_term in anchor_terms:
            for anchor_index, line in enumerate(lines):
                if anchor_term.casefold() not in line.casefold():
                    continue
                for line_index in range(
                    anchor_index + 1,
                    min(len(lines), anchor_index + 17),
                ):
                    action_text = lines[line_index]
                    matches = [item for item in actions if item.text.strip() == action_text]
                    if not matches:
                        continue
                    occurrence = sum(
                        value == action_text for value in lines[: line_index + 1]
                    ) - 1
                    action = matches[min(max(occurrence, 0), len(matches) - 1)]
                    return {
                        "element_ref": action.element_ref or "interactive-action",
                        "text": action.text[:120],
                        "bounds": {
                            key: float(value)
                            for key, value in (action.bounds or {}).items()
                        },
                    }
        return None

    @staticmethod
    def _write_context_screenshot(source: Path, output: Path) -> bool:
        try:
            with Image.open(source) as source_image:
                image = source_image.convert("RGB")
        except (OSError, ValueError):
            return False
        if image.width > 1600:
            ratio = 1600 / image.width
            image = image.resize((1600, max(1, round(image.height * ratio))))
        output.parent.mkdir(parents=True, exist_ok=True)
        image.save(output, format="PNG", optimize=True)
        return True

    @staticmethod
    def _annotate_crop(
        source: Path,
        output: Path,
        locations: list[dict],
        document_size: dict[str, int],
        *,
        draw_annotations: bool = True,
    ) -> bool:
        try:
            with Image.open(source) as source_image:
                image = source_image.convert("RGB")
        except (OSError, ValueError):
            return False

        document_width = max(int(document_size.get("width") or image.width), 1)
        document_height = max(int(document_size.get("height") or image.height), 1)
        scale_x = image.width / document_width
        scale_y = image.height / document_height
        boxes: list[tuple[int, int, int, int]] = []
        for location in locations:
            bounds = location["bounds"]
            left = max(0, round(bounds.get("x", 0) * scale_x))
            top = max(0, round(bounds.get("y", 0) * scale_y))
            right = min(
                image.width,
                round((bounds.get("x", 0) + bounds.get("width", 0)) * scale_x),
            )
            bottom = min(
                image.height,
                round((bounds.get("y", 0) + bounds.get("height", 0)) * scale_y),
            )
            if right > left and bottom > top:
                boxes.append((left, top, right, bottom))
        if not boxes:
            return False

        padding_x = max(100, round(image.width * 0.08))
        padding_y = max(260, round(min(image.height, 1600) * 0.18))
        crop_box = (
            max(0, min(box[0] for box in boxes) - padding_x),
            max(0, min(box[1] for box in boxes) - padding_y),
            min(image.width, max(box[2] for box in boxes) + padding_x),
            min(image.height, max(box[3] for box in boxes) + padding_y),
        )
        crop = image.crop(crop_box)
        if draw_annotations:
            draw = ImageDraw.Draw(crop)
            stroke = max(3, round(crop.width / 300))
            marker_radius = max(12, round(crop.width / 45))
            for index, box in enumerate(boxes, start=1):
                translated = (
                    box[0] - crop_box[0],
                    box[1] - crop_box[1],
                    box[2] - crop_box[0],
                    box[3] - crop_box[1],
                )
                draw.rounded_rectangle(
                    translated,
                    radius=6,
                    outline="#e02020",
                    width=stroke,
                )
                center = (
                    max(marker_radius, translated[0]),
                    max(marker_radius, translated[1]),
                )
                marker = (
                    center[0] - marker_radius,
                    center[1] - marker_radius,
                    center[0] + marker_radius,
                    center[1] + marker_radius,
                )
                draw.ellipse(marker, fill="#e02020")
                draw.text(
                    center,
                    str(index),
                    fill="white",
                    anchor="mm",
                    stroke_width=1,
                    stroke_fill="white",
                )
        output.parent.mkdir(parents=True, exist_ok=True)
        crop.save(output, format="PNG", optimize=True)
        return True

    @staticmethod
    def _report_html(payload: dict) -> str:
        status_labels = {
            "pass": "通过",
            "fail": "发现问题",
            "not_applicable": "不适用",
            "needs_verification": "待确认",
            "error": "未执行",
        }
        coverage_labels = {
            "verified": "完整覆盖",
            "partially_verified": "部分覆盖",
            "not_verified": "未覆盖",
        }
        run_status_labels = {
            "completed": "已完成",
            "partial": "部分完成",
            "failed": "执行失败",
        }
        journey_runs = payload["journey_check_runs"]
        issue_runs = [item for item in journey_runs if item["status"] == "fail"]
        other_runs = [item for item in journey_runs if item["status"] != "fail"]
        page_cards = "".join(
            _page_card(item, index)
            for index, item in enumerate(payload["pages"], start=1)
        )
        embedded_page_reports = "".join(
            _embedded_page_report(item, index)
            for index, item in enumerate(payload["pages"], start=1)
            if item.get("embedded_report")
        )
        issue_cards = "".join(
            _journey_check_card(item, status_labels, expanded=True)
            for item in issue_runs
        ) or (
            "<div class='empty-state'><span class='empty-mark'>✓</span>"
            "<div><strong>没有确认的跨阶段问题</strong>"
            "<p>当前证据下未发现达到报告门槛的一致性问题。</p></div></div>"
        )
        check_cards = "".join(
            _journey_check_card(item, status_labels, expanded=False)
            for item in other_runs
        )
        transition_cards = "".join(
            _transition_check_card(item, status_labels)
            for item in payload["transition_check_runs"]
        )
        trace = payload["transition_trace"]
        action_cards = "".join(
            _action_card(item, index)
            for index, item in enumerate(
                payload.get("transition_traces", [trace]),
                start=1,
            )
        )
        journey_assessment = payload.get("journey_assessment") or {}
        issue_nav = "".join(
            f"<a class='sub-link' href='#{_check_anchor(item)}'>"
            f"{html.escape(item['title'])}</a>"
            for item in issue_runs
        )
        safe_stop = f"{payload['termination_reason']} · {trace['safe_stop']}"
        coverage = coverage_labels.get(
            payload["coverage_status"],
            payload["coverage_status"],
        )
        return f"""<!doctype html>
<html lang='zh-CN'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><link rel='icon' href='data:,'>
<title>{html.escape(payload['journey']['title'])} · Journey Audit</title>
<style>
:root{{--ink:#142036;--ink-2:#30415d;--muted:#6d788b;--line:#dbe2ec;--line-2:#edf1f6;--paper:#fff;--wash:#f4f7fb;--navy:#0e2442;--blue:#246bfd;--blue-soft:#eaf1ff;--green:#147a5c;--green-soft:#e8f5ef;--amber:#a85c00;--amber-soft:#fff4df;--red:#c52935;--red-soft:#fff0f1;--shadow:0 16px 44px rgba(24,45,78,.08)}}
*{{box-sizing:border-box}}html{{scroll-behavior:smooth}}body{{margin:0;background:var(--wash);color:var(--ink);font-family:"Avenir Next","PingFang SC","Microsoft YaHei",sans-serif;line-height:1.65;-webkit-font-smoothing:antialiased}}a{{color:inherit}}button,summary,a{{outline-offset:4px}}:focus-visible{{outline:3px solid rgba(36,107,253,.42)}}
.app-shell{{min-height:100vh}}.sidebar{{position:fixed;inset:0 auto 0 0;width:276px;background:var(--navy);color:#dce8f8;padding:28px 22px 24px;display:flex;flex-direction:column;z-index:20;overflow-y:auto}}.brand{{display:flex;align-items:center;gap:12px;padding:0 8px 26px;border-bottom:1px solid rgba(255,255,255,.12)}}.brand-mark{{width:34px;height:34px;border:1px solid rgba(255,255,255,.35);display:grid;place-items:center;font:800 13px ui-monospace,SFMono-Regular,monospace;letter-spacing:-.08em}}.brand strong{{display:block;color:#fff;font-size:15px}}.brand span{{font:600 10px ui-monospace,SFMono-Regular,monospace;letter-spacing:.12em;color:#8eafd6}}.nav-label{{margin:25px 10px 8px;font:700 10px ui-monospace,SFMono-Regular,monospace;letter-spacing:.16em;color:#7192ba}}.nav-link,.sub-link{{display:flex;align-items:center;gap:10px;border-radius:8px;text-decoration:none;color:#b9cbe2;transition:background .18s,color .18s,transform .18s}}.nav-link{{padding:10px 12px;font-size:14px;font-weight:650}}.nav-link::before{{content:"";width:6px;height:6px;border:1px solid #7192ba;border-radius:50%}}.nav-link:hover,.nav-link.active{{background:rgba(255,255,255,.09);color:#fff;transform:translateX(2px)}}.nav-link.active::before{{border-color:#71a2ff;background:#71a2ff;box-shadow:0 0 0 4px rgba(113,162,255,.15)}}.sub-link{{margin-left:20px;padding:7px 10px;font-size:12px;line-height:1.35;border-left:1px solid #385778;border-radius:0}}.sub-link:hover{{color:#fff;border-color:#78a5ff}}.sidebar-foot{{margin-top:auto;padding:20px 9px 2px;color:#7896ba;font:600 10px/1.6 ui-monospace,SFMono-Regular,monospace;word-break:break-all}}
.content{{margin-left:276px;min-width:0}}main{{max-width:1320px;margin:auto;padding:46px 52px 80px}}section{{scroll-margin-top:26px}}.hero{{position:relative;background:var(--paper);border:1px solid var(--line);box-shadow:var(--shadow);padding:38px 42px 34px;margin-bottom:22px;overflow:hidden}}.hero::before{{content:"";position:absolute;left:0;top:0;bottom:0;width:6px;background:var(--blue)}}.kicker{{font:750 11px ui-monospace,SFMono-Regular,monospace;letter-spacing:.14em;color:var(--blue);text-transform:uppercase}}h1{{max-width:850px;margin:10px 0 12px;font-size:clamp(30px,4vw,54px);line-height:1.08;letter-spacing:-.04em}}.hero-goal{{max-width:760px;margin:0;color:var(--ink-2);font-size:16px}}.run-line{{display:flex;flex-wrap:wrap;gap:9px 22px;margin-top:28px;padding-top:20px;border-top:1px solid var(--line-2);color:var(--muted);font:600 11px ui-monospace,SFMono-Regular,monospace}}.run-line strong{{color:var(--ink-2)}}
.stats{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:42px}}.stat{{background:var(--paper);border:1px solid var(--line);padding:18px 20px}}.stat-label{{color:var(--muted);font-size:12px}}.stat-value{{display:block;margin-top:6px;font-size:24px;line-height:1.2;font-weight:760;letter-spacing:-.03em}}.stat-value.risk{{color:var(--red)}}
.section-head{{display:flex;justify-content:space-between;align-items:end;gap:24px;margin:0 0 16px}}.section-head h2{{margin:0;font-size:24px;letter-spacing:-.025em}}.section-head p{{max-width:620px;margin:0;color:var(--muted);font-size:13px}}.section-index{{font:700 11px ui-monospace,SFMono-Regular,monospace;color:var(--blue);letter-spacing:.1em}}.report-section{{margin-top:42px}}
.pages{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}}.page-card{{position:relative;background:var(--paper);border:1px solid var(--line);padding:24px;min-height:210px;display:flex;flex-direction:column;transition:transform .18s,box-shadow .18s}}.page-card:hover{{transform:translateY(-2px);box-shadow:var(--shadow)}}.page-number{{position:absolute;right:20px;top:16px;color:#d8e2f0;font:800 34px/1 ui-monospace,SFMono-Regular,monospace}}.page-stage{{color:var(--blue);font:750 10px ui-monospace,SFMono-Regular,monospace;letter-spacing:.1em;text-transform:uppercase}}.page-card h3{{margin:12px 48px 8px 0;font-size:19px}}.url{{margin:0 0 16px;color:var(--muted);font:500 11px/1.55 ui-monospace,SFMono-Regular,monospace;word-break:break-all}}.page-meta{{display:flex;gap:8px;margin-top:auto}}.mini-chip,.node-chip{{display:inline-flex;align-items:center;border:1px solid var(--line);background:#f8fafc;color:var(--ink-2);border-radius:999px;padding:4px 9px;font-size:11px}}.page-link{{margin-top:18px;color:var(--blue);font-size:13px;font-weight:750;text-decoration:none}}button.page-link{{border:0;background:transparent;padding:0;text-align:left;cursor:pointer}}.page-link:hover{{text-decoration:underline}}
.route-list{{background:var(--paper);border:1px solid var(--line)}}.route-row{{display:grid;grid-template-columns:54px minmax(180px,.8fr) 36px minmax(220px,1.2fr) 150px;gap:14px;align-items:center;padding:18px 20px;border-bottom:1px solid var(--line-2)}}.route-row:last-child{{border-bottom:0}}.route-index{{font:750 11px ui-monospace,SFMono-Regular,monospace;color:var(--blue)}}.route-node strong{{display:block;font-size:14px}}.route-node span{{display:block;color:var(--muted);font-size:11px;word-break:break-all}}.route-arrow{{color:#8ca0b9;font-size:20px}}.route-safe{{justify-self:end;color:var(--green);font-size:12px;font-weight:750}}
.issue-stack,.check-stack{{display:grid;gap:14px}}.check-card{{background:var(--paper);border:1px solid var(--line);border-left:4px solid #9aabc1;padding:0;scroll-margin-top:26px}}article.check-card{{padding:26px 28px}}.check-card.fail{{border-left-color:var(--red);box-shadow:0 14px 40px rgba(197,41,53,.08)}}.check-card.pass{{border-left-color:var(--green)}}.check-card.needs_verification{{border-left-color:var(--amber)}}.check-top{{display:flex;justify-content:space-between;gap:18px;align-items:flex-start}}.check-title{{margin:0;font-size:18px;letter-spacing:-.015em}}.check-subjects{{display:flex;flex-wrap:wrap;align-items:center;gap:6px;margin-top:9px;color:var(--muted);font-size:11px}}.status{{display:inline-flex;align-items:center;white-space:nowrap;border-radius:999px;padding:5px 10px;font:750 11px ui-monospace,SFMono-Regular,monospace}}.status.pass{{background:var(--green-soft);color:var(--green)}}.status.fail,.status.error{{background:var(--red-soft);color:var(--red)}}.status.needs_verification{{background:var(--amber-soft);color:var(--amber)}}.status.not_applicable{{background:#edf1f6;color:#637087}}.reason{{margin:20px 0 0;font-size:15px;color:var(--ink-2)}}.evidence-list{{margin:16px 0 0;padding:0;list-style:none;display:grid;gap:8px}}.evidence-list li{{position:relative;padding-left:18px;color:var(--ink-2);font-size:13px}}.evidence-list li::before{{content:"";position:absolute;left:1px;top:.7em;width:6px;height:6px;background:var(--blue)}}.standard-line{{margin-top:20px;padding-top:14px;border-top:1px solid var(--line-2);color:var(--muted);font-size:11px}}.suggestion{{margin:18px 0 0;padding:14px 16px;background:var(--blue-soft);border-left:3px solid var(--blue);color:#183f85;font-size:13px}}.suggestion strong{{display:block;margin-bottom:3px;color:#12326c}}details.check-card summary{{list-style:none;cursor:pointer;padding:18px 22px}}details.check-card summary::-webkit-details-marker{{display:none}}details.check-card summary .check-top{{align-items:center}}.detail-body{{padding:0 22px 20px;border-top:1px solid var(--line-2)}}
.evidence-board{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1px;margin:24px 0 0;background:var(--line);border:1px solid var(--line)}}.journey-shot{{position:relative;margin:0;background:#f8fafc;min-width:0}}.journey-shot a{{display:block;background:#eef2f7;overflow:hidden}}.journey-shot img{{display:block;width:100%;height:360px;object-fit:contain;background:#f8fafc;transition:transform .2s}}.journey-shot a:hover img{{transform:scale(1.012)}}.journey-shot figcaption{{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:12px 14px;background:#fff;color:var(--ink-2);font-size:12px}}.shot-kind{{color:var(--red);font:750 10px ui-monospace,SFMono-Regular,monospace;letter-spacing:.08em}}.journey-shot.comparison .shot-kind{{color:var(--muted)}}.empty-state{{display:flex;gap:16px;align-items:center;background:var(--paper);border:1px solid var(--line);padding:24px}}.empty-state p{{margin:4px 0 0;color:var(--muted);font-size:13px}}.empty-mark{{display:grid;place-items:center;width:38px;height:38px;background:var(--green-soft);color:var(--green);border-radius:50%;font-weight:800}}.page-report-dialog{{width:min(1240px,94vw);height:min(90vh,1000px);padding:0;border:0;border-radius:14px;box-shadow:0 28px 80px rgba(15,31,54,.38)}}.page-report-dialog::backdrop{{background:rgba(15,31,54,.58)}}.page-report-dialog header{{display:flex;justify-content:space-between;align-items:center;padding:12px 16px;background:#fff;border-bottom:1px solid var(--line)}}.page-report-dialog header strong{{font-size:14px}}.page-report-dialog button{{border:1px solid var(--line);background:#fff;border-radius:7px;padding:7px 10px;cursor:pointer}}.page-report-dialog iframe{{display:block;width:100%;height:calc(100% - 50px);border:0;background:#fff}}
@media(max-width:1080px){{.sidebar{{width:230px}}.content{{margin-left:230px}}main{{padding:36px 30px 70px}}.stats{{grid-template-columns:repeat(2,1fr)}}.route-row{{grid-template-columns:40px 1fr 28px 1fr}}.route-safe{{display:none}}}}
@media(max-width:760px){{html{{scroll-padding-top:74px}}.sidebar{{position:sticky;top:0;width:100%;height:auto;padding:12px 14px;overflow-x:auto;display:block}}.brand,.nav-label,.sub-link,.sidebar-foot{{display:none}}.sidebar nav{{display:flex;gap:4px;min-width:max-content}}.nav-link{{display:inline-flex;padding:8px 10px}}.content{{margin-left:0}}main{{padding:22px 16px 56px}}.hero{{padding:28px 24px}}.stats,.pages,.evidence-board{{grid-template-columns:1fr}}.section-head{{display:block}}.section-head p{{margin-top:6px}}.route-row{{grid-template-columns:32px 1fr;gap:8px}}.route-arrow,.route-row>.route-node:nth-of-type(2){{display:none}}article.check-card{{padding:22px 20px}}.journey-shot img{{height:auto;max-height:420px}}}}
@media(prefers-reduced-motion:reduce){{html{{scroll-behavior:auto}}*{{transition:none!important}}}}
</style></head><body>
<div class='app-shell'><aside class='sidebar'><div class='brand'><div class='brand-mark'>MP</div><div><strong>Journey Audit</strong><span>METAPQP · REVIEW</span></div></div><nav aria-label='报告导航'><div class='nav-label'>REPORT</div><a class='nav-link active' href='#overview'>运行总览</a><a class='nav-link' href='#pages'>检查页面</a><a class='nav-link' href='#route'>旅程路径</a><a class='nav-link' href='#issues'>问题与证据</a>{issue_nav}<a class='nav-link' href='#checks'>其他检查</a><a class='nav-link' href='#transition'>Transition</a></nav><div class='sidebar-foot'>JOB<br>{html.escape(payload['job_id'])}</div></aside>
<div class='content'><main><section id='overview' class='hero'><div class='kicker'>Supervised Journey / Audit Report</div><h1>{html.escape(payload['journey']['title'])}</h1><p class='hero-goal'>{html.escape(payload['journey']['goal'])}</p><div class='run-line'><span>运行 <strong>{html.escape(run_status_labels.get(payload['status'], payload['status']))}</strong></span><span>安全停止 <strong>{html.escape(safe_stop)}</strong></span></div></section>
<div class='stats' aria-label='运行摘要'><div class='stat'><span class='stat-label'>跨阶段问题</span><strong class='stat-value risk'>{journey_assessment.get('issue_count', 0)}</strong></div><div class='stat'><span class='stat-label'>检查规则</span><strong class='stat-value'>{len(journey_runs)}</strong></div><div class='stat'><span class='stat-label'>覆盖状态</span><strong class='stat-value'>{html.escape(coverage)}</strong></div><div class='stat'><span class='stat-label'>旅程页面</span><strong class='stat-value'>{len(payload['pages'])}</strong></div></div>
<section id='pages' class='report-section'><div class='section-head'><div><span class='section-index'>01 / PAGES</span><h2>检查页面</h2></div><p>按旅程顺序查看各阶段页面，并可进入对应的页面级详细报告。</p></div><div class='pages'>{page_cards}</div></section>
<section id='route' class='report-section'><div class='section-head'><div><span class='section-index'>02 / ROUTE</span><h2>旅程路径</h2></div><p>记录实际执行的受控动作、落点以及安全停止状态。</p></div><div class='route-list'>{action_cards}</div></section>
<section id='issues' class='report-section'><div class='section-head'><div><span class='section-index'>03 / EVIDENCE</span><h2>问题与证据</h2></div><p>只展示达到问题门槛的检查；存在证据使用红框，缺失侧保留无框对照。</p></div><div class='issue-stack'>{issue_cards}</div></section>
<section id='checks' class='report-section'><div class='section-head'><div><span class='section-index'>04 / CHECKS</span><h2>其他跨阶段检查</h2></div><p>通过、不适用、待确认与未执行的规则收起展示，点击可查看判定依据。</p></div><div class='check-stack'>{check_cards}</div></section>
<section id='transition' class='report-section'><div class='section-head'><div><span class='section-index'>05 / TRANSITION</span><h2>Transition 检查</h2></div><p>验证页面间动作是否可达、入口是否连续以及交易上下文是否保留。</p></div><div class='check-stack'>{transition_cards}</div></section>
</main></div></div>{embedded_page_reports}
<script>
const links=[...document.querySelectorAll('.nav-link,.sub-link')];
const targets=links.map(link=>document.querySelector(link.getAttribute('href'))).filter(Boolean);
const observer=new IntersectionObserver(entries=>{{const visible=entries.filter(entry=>entry.isIntersecting).sort((a,b)=>b.intersectionRatio-a.intersectionRatio)[0];if(!visible)return;links.forEach(link=>link.classList.toggle('active',link.getAttribute('href')==='#'+visible.target.id));}},{{rootMargin:'-12% 0px -72% 0px',threshold:[0,.2,.6]}});
targets.forEach(target=>observer.observe(target));
document.querySelectorAll('[data-page-report]').forEach(button=>button.addEventListener('click',()=>document.getElementById(button.dataset.pageReport).showModal()));
document.querySelectorAll('[data-close-page-report]').forEach(button=>button.addEventListener('click',()=>button.closest('dialog').close()));
</script></body></html>"""


def _safe_segment(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip()).strip("-.") or "unknown"


def _as_data_uri(content: bytes, media_type: str) -> str:
    encoded = base64.b64encode(content).decode("ascii")
    return f"data:{media_type};base64,{encoded}"


def _file_data_uri(path: Path) -> str:
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return _as_data_uri(path.read_bytes(), media_type)


def _page_card(item: dict, index: int) -> str:
    node_id = str(item.get("node_id") or item["page_id"])
    coverage = {
        "verified": "完整覆盖",
        "partially_verified": "部分覆盖",
        "not_verified": "未覆盖",
    }.get(item["coverage_status"], item["coverage_status"])
    link = (
        f"<button class='page-link' type='button' data-page-report='page-report-{index}'>"
        "打开内嵌页面报告&nbsp; ↗</button>"
        if item.get("embedded_report")
        else f"<a class='page-link' href='{html.escape(item['report'])}'>打开页面报告&nbsp; ↗</a>"
    )
    return (
        f"<article id='page-{_safe_segment(node_id)}' class='page-card'>"
        f"<span class='page-number'>{index:02d}</span>"
        f"<span class='page-stage'>{html.escape(node_id)}</span>"
        f"<h3>{html.escape(item['title'])}</h3>"
        f"<p class='url'>{html.escape(item['url'])}</p>"
        "<div class='page-meta'>"
        f"<span class='mini-chip'>页面问题 {item['issue_count']}</span>"
        f"<span class='mini-chip'>{html.escape(coverage)}</span>"
        "</div>"
        f"{link}</article>"
    )


def _embedded_page_report(item: dict, index: int) -> str:
    return (
        f"<dialog id='page-report-{index}' class='page-report-dialog'>"
        f"<header><strong>{html.escape(item['title'])}</strong>"
        "<button type='button' data-close-page-report>关闭</button></header>"
        f"<iframe title='{html.escape(item['title'])}' src='{html.escape(item['embedded_report'])}'></iframe>"
        "</dialog>"
    )


def _check_anchor(item: dict) -> str:
    identity = item.get("invocation_id") or item["check_spec_id"]
    return f"check-{_safe_segment(str(identity))}"


def _journey_check_card(
    item: dict,
    status_labels: dict[str, str],
    *,
    expanded: bool,
) -> str:
    standards = "；".join(
        f"{reference.get('source_name', '')} · {reference.get('criterion_title', '')}"
        for reference in item.get("standard_refs", [])
    ) or "MetaPQP 内部检查建议"
    evidence = "".join(
        f"<li>{html.escape(str(value))}</li>" for value in item.get("evidence", [])
    )
    suggestion = (
        "<div class='suggestion'><strong>改进建议</strong>"
        f"{html.escape(item['suggestion'])}</div>"
        if item.get("suggestion") else ""
    )
    subjects = "<span>→</span>".join(
        f"<span class='node-chip'>{html.escape(value)}</span>"
        for value in item.get("subject_node_ids") or []
    )
    detail = f"<p class='reason'>{html.escape(item['reason'])}</p>"
    if evidence:
        detail += f"<ul class='evidence-list'>{evidence}</ul>"
    detail += suggestion
    screenshots = "".join(
        _journey_screenshot(value)
        for value in item.get("evidence_screenshots", [])
    )
    if screenshots:
        detail += f"<div class='evidence-board'>{screenshots}</div>"
    detail += f"<div class='standard-line'>规范依据&nbsp; {html.escape(standards)}</div>"
    header = (
        "<div class='check-top'><div>"
        f"<h3 class='check-title'>{html.escape(item['title'])}</h3>"
        f"<div class='check-subjects'>{subjects}</div></div>"
        f"<span class='status {item['status']}'>"
        f"{status_labels.get(item['status'], item['status'])}</span></div>"
    )
    anchor = _check_anchor(item)
    if expanded:
        return (
            f"<article id='{anchor}' class='check-card {item['status']}'>"
            f"{header}{detail}</article>"
        )
    return (
        f"<details id='{anchor}' class='check-card {item['status']}'>"
        f"<summary>{header}</summary><div class='detail-body'>{detail}</div></details>"
    )


def _shot_kind(value: dict) -> str:
    precision = value.get("precision")
    if precision == "element":
        return "实际证据"
    if precision == "comparison":
        return "缺失对照"
    return "页面上下文"


def _journey_screenshot(value: dict) -> str:
    source = str(value.get("data_uri") or value["path"])
    return (
        f"<figure class='journey-shot {html.escape(value.get('precision', 'context'))}'>"
        f"<a href='{html.escape(source)}' target='_blank'>"
        f"<img loading='lazy' src='{html.escape(source)}' "
        f"alt='{html.escape(value['caption'])}'></a>"
        f"<figcaption><span>{html.escape(value['caption'])}</span>"
        f"<span class='shot-kind'>{_shot_kind(value)}</span></figcaption></figure>"
    )


def _transition_check_card(item: dict, status_labels: dict[str, str]) -> str:
    return (
        f"<details class='check-card {item['status']}'>"
        "<summary><div class='check-top'>"
        f"<h3 class='check-title'>{html.escape(item['title'])}</h3>"
        f"<span class='status {item['status']}'>"
        f"{status_labels.get(item['status'], item['status'])}</span>"
        "</div></summary><div class='detail-body'>"
        f"<p class='reason'>{html.escape(item['reason'])}</p></div></details>"
    )


def _action_card(trace: dict, index: int) -> str:
    action = trace["action"]
    action_name = action.get("element_name") or action.get("action_id") or ""
    occurrence = int(action.get("selected_occurrence") or 0) + 1
    action_label = f"{action_name}（匹配 {action.get('matched_count', 0)}，选择第 {occurrence} 个）"
    return (
        "<div class='route-row'>"
        f"<span class='route-index'>T{index:02d}</span>"
        "<div class='route-node'>"
        f"<strong>{html.escape(trace['from_node_id'])}</strong>"
        f"<span>{html.escape(action_label)}</span></div>"
        "<span class='route-arrow'>→</span>"
        "<div class='route-node'>"
        f"<strong>{html.escape(trace['to_node_id'])}</strong>"
        f"<span>{html.escape(trace.get('end_url') or '')}</span></div>"
        f"<span class='route-safe'>{html.escape(action.get('safety_decision') or '')}"
        "</span></div>"
    )
