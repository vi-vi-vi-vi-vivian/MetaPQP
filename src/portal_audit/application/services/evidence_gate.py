"""Stop audits when browser capture did not produce usable page evidence."""

from __future__ import annotations

from typing import ClassVar
from urllib.parse import urlparse

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
            if self._is_huawei_login_page(snapshot.final_url):
                detail = self._authentication_detail(snapshot.authentication.reason)
                reasons.append(f"目标页面已跳转至登录页，自动登录未完成（{detail}）")
            else:
                reasons.append("未采集到可用于检查的页面正文，页面可能尚未完成渲染")
        if reasons and snapshot.network_errors:
            signals = " ".join(str(item.get("error", "")) for item in snapshot.network_errors)
            if "timeout" in signals.lower():
                reasons.append("采集期间发生页面加载超时")
            elif self._has_relevant_connection_failure(snapshot):
                reasons.append("采集期间发生资源连接中断")
        return reasons

    @staticmethod
    def _is_huawei_login_page(url: str) -> bool:
        parsed = urlparse(url)
        return parsed.hostname == "auth.huaweicloud.com" and "login" in parsed.path.lower()

    @staticmethod
    def _has_relevant_connection_failure(snapshot: PageSnapshot) -> bool:
        """Ignore local telemetry/extension failures unrelated to page content."""
        for item in snapshot.network_errors:
            error = str(item.get("error", ""))
            host = (urlparse(str(item.get("url", ""))).hostname or "").lower()
            if "ERR_CONNECTION" not in error or host in {"127.0.0.1", "localhost", "::1"}:
                continue
            return True
        return False

    @staticmethod
    def _authentication_detail(reason: str | None) -> str:
        return {
            "local_security_service_unavailable": "登录所需的本地安全服务未响应；已按安全规则暂停",
            "login_result_timeout": "登录提交后未获得服务端结果",
        }.get(reason or "", reason or "自动登录未完成")

    def _has_rendered_content(self, snapshot: PageSnapshot) -> bool:
        if snapshot.content_ready is False:
            return False
        page_elements = [
            item for item in snapshot.evidence_elements
            if item.page_region not in {"header", "footer", "navigation"}
        ]
        has_structured_text = any(
            item.text.strip() and item.tag in self._TEXT_CONTENT_TAGS
            for item in page_elements
        )
        document_height = snapshot.document_size.get("height", 0)
        viewport_height = snapshot.viewport.get("height", 0)
        extends_beyond_first_viewport = document_height > viewport_height and bool(page_elements)
        return has_structured_text or extends_beyond_first_viewport
