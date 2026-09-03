"""Stop audits when browser capture did not produce usable page evidence."""

from __future__ import annotations

from typing import ClassVar

from portal_audit.domain.models import PageSnapshot, PageTarget


class PageEvidenceCaptureError(RuntimeError):
    """Raised before checks when a page did not render usable, locatable content."""


class PageEvidenceGate:
    """Apply the same minimum evidence rule to every audit scope.

    This is a quality gate, not an evidence-size limit.  It only rejects a
    capture when there is no full-page screenshot, no locatable elements, or
    the document contains neither content structure nor content beyond the
    first viewport.  In that state a later rule or model cannot form a
    defensible conclusion.
    """

    _TEXT_CONTENT_TAGS: ClassVar[set[str]] = {
        "h1", "h2", "h3", "h4", "h5", "h6", "p", "dt", "dd"
    }

    def ensure(self, target: PageTarget, snapshot: PageSnapshot) -> None:
        reasons = self.reasons(snapshot)
        if not reasons:
            return
        label = target.product or target.page_id
        raise PageEvidenceCaptureError(
            f"页面“{label}”采集不完整，已停止后续检查：" + "；".join(reasons)
        )

    def reasons(self, snapshot: PageSnapshot) -> list[str]:
        reasons: list[str] = []
        if not any(item.kind == "screenshot" for item in snapshot.artifacts):
            reasons.append("未生成页面截图")
        if not any(item.bounds for item in snapshot.evidence_elements):
            reasons.append("未采集到可定位的页面元素")
        if not self._has_rendered_content(snapshot):
            reasons.append("未采集到可用于检查的页面正文，页面可能尚未完成渲染")
        if reasons and snapshot.network_errors:
            signals = " ".join(str(item.get("error", "")) for item in snapshot.network_errors)
            if "timeout" in signals.lower():
                reasons.append("采集期间发生页面加载超时")
            elif "ERR_CONNECTION" in signals:
                reasons.append("采集期间发生资源连接中断")
        return reasons

    def _has_rendered_content(self, snapshot: PageSnapshot) -> bool:
        has_structured_text = any(
            item.text.strip() and item.tag in self._TEXT_CONTENT_TAGS
            for item in snapshot.evidence_elements
        )
        document_height = snapshot.document_size.get("height", 0)
        viewport_height = snapshot.viewport.get("height", 0)
        extends_beyond_first_viewport = document_height > viewport_height
        return has_structured_text or extends_beyond_first_viewport
