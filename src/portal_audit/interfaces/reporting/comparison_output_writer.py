"""Portable, locator-first HTML for comparison results."""

from __future__ import annotations

import base64
import html
import json
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw

from portal_audit.domain.models import ComparisonResult


class ComparisonOutputWriter:
    def __init__(self, output_root: Path):
        self.output_root = output_root

    def write(self, result: ComparisonResult) -> Path:
        root = self.output_root / "comparisons" / result.comparison_profile.id / result.job_id
        root.mkdir(parents=True, exist_ok=True)
        payload = result.model_dump(mode="json")
        crops = self._crops(result)
        payload["comparison_crops"] = crops
        (root / "comparison.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (root / "report.html").write_text(self._html(payload), encoding="utf-8")
        return root

    def _crops(self, result: ComparisonResult) -> dict[str, dict[str, str | None]]:
        results = {item.target.page_id: item for item in [result.subject_result, *result.reference_results]}
        crops: dict[str, dict[str, str | None]] = {}
        for detail in result.assessment.details:
            entries = [detail.subject_display, *detail.reference_displays]
            crops[detail.check_spec_id] = {
                item.target_id: self._crop(results.get(item.target_id), item.element_refs)
                for item in entries
            }
        return crops

    @staticmethod
    def _crop(result, refs: list[str]) -> str | None:
        if result is None or not refs:
            return None
        source = next(
            (Path(item.path) for item in result.snapshot.artifacts if item.kind == "screenshot" and Path(item.path).is_file()),
            None,
        )
        if source is None:
            return None
        elements = {item.element_ref: item for item in result.snapshot.evidence_elements}
        boxes = [elements[ref].bounds for ref in refs if ref in elements and elements[ref].bounds]
        if not boxes:
            return None
        with Image.open(source) as image:
            image = image.convert("RGB")
            doc = result.snapshot.document_size or result.snapshot.viewport
            scale_x = image.width / max(1, doc.get("width", result.snapshot.viewport["width"]))
            scale_y = image.height / max(1, doc.get("height", image.height))
            pixel_boxes = [
                (box["x"] * scale_x, box["y"] * scale_y, (box["x"] + box["width"]) * scale_x, (box["y"] + box["height"]) * scale_y)
                for box in boxes
            ]
            padding = 72
            left = max(0, int(min(box[0] for box in pixel_boxes) - padding))
            top = max(0, int(min(box[1] for box in pixel_boxes) - padding))
            right = min(image.width, int(max(box[2] for box in pixel_boxes) + padding))
            bottom = min(image.height, int(max(box[3] for box in pixel_boxes) + padding))
            canvas = image.copy()
            draw = ImageDraw.Draw(canvas)
            for left_box, top_box, right_box, bottom_box in pixel_boxes:
                draw.rectangle((left_box, top_box, right_box, bottom_box), outline="#e5484d", width=5)
            crop = canvas.crop((left, top, right, bottom))
            stream = BytesIO()
            crop.save(stream, format="PNG", optimize=True)
        return f"data:image/png;base64,{base64.b64encode(stream.getvalue()).decode('ascii')}"

    def _html(self, data: dict) -> str:
        profile = data["comparison_profile"]
        runs = data["assessment"]["check_runs"]
        details = {item["check_spec_id"]: item for item in data["assessment"].get("details", [])}
        crops = data.get("comparison_crops", {})
        esc = lambda value: html.escape(str(value or ""))
        nav = "".join(f'<a href="#check-{esc(item["check_spec_id"])}">{esc(item["title"])}</a>' for item in runs)
        cards = []
        for run in runs:
            issue = run["status"] == "fail"
            label = {
                "fail": "可借鉴改进机会",
                "pass": "通过",
                "needs_verification": "待确认",
                "not_applicable": "不适用",
                "error": "未执行",
            }.get(run["status"], "未执行")
            if not issue:
                state = "pass" if run["status"] == "pass" else "neutral"
                cards.append(f'<section id="check-{esc(run["check_spec_id"])}" class="card {state}"><div class="cardtop"><span class="pill">{label}</span><span>{esc(run["check_spec_id"])}</span></div><h2>{esc(run["title"])}</h2><p>{esc(run["reason"])}</p></section>')
                continue
            detail = details.get(run["check_spec_id"], {})
            subject = detail.get("subject_display", {})
            references = detail.get("reference_displays", [])
            visual_cards = self._visual_cards(crops.get(run["check_spec_id"], {}), subject, references, esc)
            reference_text = "".join(f'<article><b>{esc(item.get("product"))}</b><p>{esc(item.get("content"))}</p></article>' for item in references)
            cards.append(f'''<section id="check-{esc(run["check_spec_id"])}" class="card issue"><div class="cardtop"><span class="pill">{label}</span><span>{esc(run["check_spec_id"])}</span></div><h2>{esc(run["title"])} </h2><div class="field"><b>问题描述</b><p>{esc(detail.get("issue_description") or run["reason"])}</p></div><div class="evidence-grid"><div class="field"><b>本产品展示内容</b><p>{esc(subject.get("content"))}</p></div><div class="field"><b>参考产品展示内容</b>{reference_text}</div></div><div class="field suggestion"><b>修改建议</b><p>{esc(detail.get("recommendation") or run.get("suggestion"))}</p></div>{visual_cards}</section>''')
        count = sum(item["status"] == "fail" for item in runs)
        return f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(profile["title"])} · 对比检查</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f5f7fb;color:#182033;font:15px -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif}}aside{{position:fixed;width:264px;height:100vh;background:#12233f;color:#dfe9f9;padding:32px 24px;overflow:auto}}aside h1{{font-size:18px;color:white;margin:0 0 9px}}aside p{{font-size:13px;line-height:1.5;color:#a9c1e2}}aside a{{display:block;color:#d8e6fa;text-decoration:none;padding:8px 0;border-bottom:1px solid #294361;font-size:13px}}main{{margin-left:264px;max-width:1320px;padding:42px 54px 80px}}.hero{{background:linear-gradient(120deg,#183b70,#2367a7);color:#fff;border-radius:18px;padding:28px 32px;margin-bottom:28px}}.hero h1{{margin:0 0 10px;font-size:28px}}.metric{{font-size:32px;font-weight:700}}.card{{background:#fff;border:1px solid #dce4f0;border-radius:14px;padding:24px 28px;margin:18px 0;box-shadow:0 4px 14px #1525420c}}.issue{{border-left:5px solid #dc6b37}}.pass{{border-left:5px solid #48a178}}.neutral{{border-left:5px solid #8291a7}}.cardtop{{display:flex;justify-content:space-between;color:#65758d;font-size:12px}}.pill{{border-radius:20px;padding:4px 9px;background:#e7f5ed;color:#197047;font-weight:600}}.neutral .pill{{background:#eef2f6;color:#56677e}}.issue .pill{{background:#fff0e9;color:#b74619}}h2{{font-size:19px;margin:14px 0}}p{{line-height:1.7;margin:7px 0}}.field{{padding:14px 16px;margin:13px 0;border-radius:9px;background:#f7f9fc;border:1px solid #e1e8f1}}.field>b{{display:block;color:#485971}}.evidence-grid,.shots{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px}}.evidence-grid .field{{margin:0}}.field article{{padding-top:6px;border-top:1px solid #dce5ee}}.field article:first-of-type{{border-top:0}}.suggestion{{background:#fff7f2;border-color:#f4d5c5}}.shots{{margin-top:20px}}figure{{margin:0;border:1px solid #dfe6ef;border-radius:10px;padding:10px;background:#f9fbfe}}figcaption{{font-weight:600;margin:0 0 8px}}img{{display:block;width:100%;max-height:520px;object-fit:contain;object-position:top;background:#fff}}.missing{{min-height:160px;padding:58px 16px;text-align:center;color:#7e8da3;background:#f0f3f8}}@media(max-width:800px){{aside{{position:static;width:auto;height:auto}}main{{margin:0;padding:20px}}}}
</style><aside><h1>对比检查报告</h1><p>{esc(profile["title"])}</p><a href="#overview">概览</a>{nav}</aside><main><header id="overview" class="hero"><h1>{esc(profile["title"])}</h1><p>基于可验证的参考做法，识别可迁移的体验改进机会；不做产品优劣排名。</p><div class="metric">{count} <small>项可借鉴改进机会 / {len(runs)} 项检查</small></div></header>{''.join(cards)}</main></html>'''

    @staticmethod
    def _visual_cards(crops: dict, subject: dict, references: list[dict], esc) -> str:
        def figure(label: str, target_id: str) -> str:
            source = crops.get(target_id)
            body = f'<img src="{source}" alt="{esc(label)} 局部截图，红框标示证据">' if source else '<div class="missing">未能根据元素坐标生成局部截图</div>'
            return f'<figure><figcaption>{esc(label)}</figcaption>{body}</figure>'
        return '<div class="shots">' + figure(f'本产品页面展示 · {subject.get("product", "")}', subject.get("target_id", "")) + ''.join(figure(f'参考产品页面展示 · {item.get("product", "")}', item.get("target_id", "")) for item in references) + '</div>'
