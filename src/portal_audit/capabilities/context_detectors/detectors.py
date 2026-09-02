"""Deterministic MVP detectors; semantic detectors can be added as SKILL.md capabilities."""

from __future__ import annotations

from portal_audit.domain.models import ContextObservation, PageSnapshot


class JourneyStageDetector:
    id = "journey-stage-v1"

    def detect(self, snapshot: PageSnapshot) -> list[ContextObservation]:
        haystack = f"{snapshot.final_url} {snapshot.title} {snapshot.body_text[:20000]}".lower()
        patterns = [
            ("payment", ["支付", "收银台", "pay"]),
            ("order", ["确认订单", "立即购买", "下单", "order"]),
            (
                "purchase",
                [
                    "套餐",
                    "方案比较",
                    "订阅 token plan",
                    "subscription service",
                    "resourceplanmanagement",
                ],
            ),
            ("usage", ["控制台", "资源管理", "console"]),
            ("awareness", ["产品优势", "应用场景", "立即订阅", "product"]),
            ("renewal", ["续费", "renew"]),
            ("unsubscribe", ["退订", "unsubscribe"]),
        ]
        for stage, markers in patterns:
            matched = [marker for marker in markers if marker in haystack]
            if matched:
                return [
                    ContextObservation(
                        detector_id=self.id,
                        dimension="journey_stage",
                        value=stage,
                        confidence=0.75,
                        evidence=matched[:3],
                    )
                ]
        return [
            ContextObservation(
                detector_id=self.id, dimension="journey_stage", value="unknown", confidence=0.3
            )
        ]


class PageArchetypeDetector:
    id = "page-archetype-v1"

    def detect(self, snapshot: PageSnapshot) -> list[ContextObservation]:
        url = snapshot.final_url.lower()
        text = f"{snapshot.title} {snapshot.body_text}".lower()
        candidates = [
            (
                "payment_page",
                "payment" in url or any(marker in text for marker in ("收银台", "确认支付")),
            ),
            (
                "order_page",
                "order" in url or any(marker in text for marker in ("确认订单", "订单详情")),
            ),
            (
                "product_landing",
                "立即订阅" in text
                or "/product/" in url
                or "tokenplan" in url
                or "resourceplanmanagement" in url
                or "subscribe to token plan" in text,
            ),
            ("console_page", "console." in url),
        ]
        for value, matched in candidates:
            if matched:
                return [
                    ContextObservation(
                        detector_id=self.id,
                        dimension="page_archetype",
                        value=value,
                        confidence=0.8,
                        evidence=[snapshot.title, snapshot.final_url],
                    )
                ]
        return [
            ContextObservation(
                detector_id=self.id,
                dimension="page_archetype",
                value="content_page",
                confidence=0.5,
                evidence=[snapshot.title],
            )
        ]


class CommerceFeatureDetector:
    id = "commerce-features-v1"

    def detect(self, snapshot: PageSnapshot) -> list[ContextObservation]:
        text = snapshot.body_text[:30000].lower()
        element_text = " ".join(item.text.lower() for item in snapshot.interactive_elements)
        mapping = {
            "pricing": ["¥", "￥", "价格", "/月", "/年", "/month", "/year"],
            "purchase_entry": [
                "立即购买",
                "立即订阅",
                "购买",
                "订阅",
                "subscribe",
                "subscription",
                "restocking",
            ],
            "form": ["input", "提交", "确认"],
            "order_summary": ["订单金额", "订单详情"],
            "payment_entry": ["去支付", "在线支付", "付款"],
        }
        observations = []
        for feature, markers in mapping.items():
            matched = [m for m in markers if m in text or m in element_text]
            if matched:
                observations.append(
                    ContextObservation(
                        detector_id=self.id,
                        dimension="feature",
                        value=feature,
                        confidence=0.85,
                        evidence=matched[:3],
                    )
                )
        return observations
