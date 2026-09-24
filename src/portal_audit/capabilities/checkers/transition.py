"""Deterministic Transition capabilities.

Each class is independently registered by a capability manifest.  Keeping the
algorithms here prevents the Transition executor from becoming a growing
capability-id switch statement.
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from portal_audit.application.services.interaction_feedback import local_state_feedback
from portal_audit.domain.models import CheckRun, CheckStatus, PageSnapshot, TransitionTrace


class TransitionChecker:
    def execute(
        self,
        spec,
        trace: TransitionTrace,
        start_snapshot: PageSnapshot,
        end_snapshot: PageSnapshot,
    ) -> CheckRun:
        raise NotImplementedError

    @staticmethod
    def run(spec, status: CheckStatus, reason: str, trace: TransitionTrace) -> CheckRun:
        return CheckRun(
            check_spec_id=spec.id,
            check_spec_version=spec.version,
            status=status,
            title=spec.title,
            reason=reason,
            severity=spec.default_severity,
            confidence=1 if status != CheckStatus.NEEDS_VERIFICATION else 0.6,
            evidence=[
                f"start_url={trace.start_url}",
                f"end_url={trace.end_url}",
                f"action_status={trace.action.status}",
            ],
            executor_id=spec.executor.capability_id,
            invocation_id=f"{spec.id}__{trace.from_node_id}--{trace.to_node_id}",
            subject_node_ids=[trace.from_node_id, trace.to_node_id],
            comparison_mode="adjacent",
        )


class JourneyTransitionReachabilityChecker(TransitionChecker):
    def execute(self, spec, trace, start_snapshot, end_snapshot) -> CheckRun:
        has_declared_destination = bool(trace.expected_entry_url or trace.expected_url_contains)
        matched = (
            trace.status == "completed"
            and (
                (
                    trace.end_resolution is not None
                    and trace.end_resolution.status == "matched"
                    and trace.end_resolution.node_id == trace.to_node_id
                )
                if has_declared_destination
                else bool(end_snapshot.final_url and (end_snapshot.title or end_snapshot.body_text))
            )
        )
        result = self.run(
            spec,
            CheckStatus.PASS if matched else CheckStatus.FAIL,
            (
                (f"已到达预期节点 {trace.to_node_id}，终点 URL={trace.end_url}"
                 if has_declared_destination else f"点击后获得可用结果：{end_snapshot.title or trace.end_url}")
                if matched
                else (
                    f"预期在点击“{trace.action.element_name or trace.action.action_id}”后进入"
                    f"“{trace.to_node_id}”（目标 URL：{trace.expected_entry_url or '未登记'}）；"
                    f"实际到达“{end_snapshot.title or '未识别页面'}”"
                    f"（{trace.end_url or '未获取 URL'}）。"
                    f"该地址未匹配预期页面地图："
                    f"{trace.end_resolution.reason if trace.end_resolution else trace.termination_reason}"
                )
            ),
            trace,
        )
        if not matched:
            result.suggestion = (
                "核对该入口的实际跳转 URL 与预期订阅页是否一致；若当前页面就是有效订阅页，"
                "为其补充页面地图 URL 匹配规则和页面名称；否则修复入口跳转配置。"
            )
            result.evidence.extend(
                [
                    f"预期页面节点={trace.to_node_id}",
                    f"预期入口 URL={trace.expected_entry_url or '未登记'}",
                    f"预期 URL 特征={trace.expected_url_contains or '未限制'}",
                    f"实际到达 URL={trace.end_url or '未获取'}",
                    f"实际页面标题={end_snapshot.title or '未识别'}",
                    f"页面识别结果={trace.end_resolution.status if trace.end_resolution else '未识别'}",
                ]
            )
        return result


class EntryAndResumeContinuityChecker(TransitionChecker):
    def execute(self, spec, trace, start_snapshot, end_snapshot) -> CheckRun:
        del start_snapshot
        final_url = end_snapshot.final_url.lower()
        body = end_snapshot.body_text.lower()
        interrupted = bool(re.search(r"/(?:auth(?:entication)?/)?login(?:[/?#]|$)", final_url)) or any(
            marker in body for marker in ("登录", "sign in", "password login")
        )
        return self.run(
            spec,
            CheckStatus.FAIL if interrupted else CheckStatus.PASS,
            "跳转后停留在登录入口，未恢复业务页面"
            if interrupted
            else f"登录态连续，已恢复到业务页面 {end_snapshot.final_url}",
            trace,
        )


class TransactionContextContinuityChecker(TransitionChecker):
    def execute(self, spec, trace, start_snapshot, end_snapshot) -> CheckRun:
        start_compact = re.sub(r"[^a-z0-9]+", "", start_snapshot.body_text.lower())
        end_compact = re.sub(r"[^a-z0-9]+", "", end_snapshot.body_text.lower())
        stage_terms = {
            "awareness", "purchase", "order", "payment", "usage", "renewal",
            "change", "unsubscribe", "portal", "console",
        }
        from_terms = set(re.findall(r"[a-z0-9]+", trace.from_node_id.casefold()))
        to_terms = set(re.findall(r"[a-z0-9]+", trace.to_node_id.casefold()))
        product_terms = (from_terms & to_terms) - stage_terms
        start_has_product = any(term in start_compact for term in product_terms)
        end_has_product = any(term in end_compact for term in product_terms)
        status = (
            CheckStatus.PASS
            if product_terms and start_has_product and end_has_product
            else CheckStatus.NEEDS_VERIFICATION
        )
        return self.run(
            spec,
            status,
            f"起点与终点均显示相同产品上下文：{', '.join(sorted(product_terms))}"
            if status == CheckStatus.PASS
            else "终点已到达预期入口，但当前可见文本不足以确认产品上下文连续",
            trace,
        )


class InteractionFeedbackVisibilityChecker(TransitionChecker):
    """Require a safe click to produce an observable page, URL, or text change."""

    def execute(self, spec, trace, start_snapshot, end_snapshot) -> CheckRun:
        feedback = local_state_feedback(start_snapshot.interaction_state, end_snapshot.interaction_state)
        if trace.status == 'completed' and feedback:
            return self.run(spec, CheckStatus.PASS, feedback, trace)
        if end_snapshot.content_ready is False:
            return self.run(spec, CheckStatus.NEEDS_VERIFICATION, '目标正文尚未加载完成，当前证据不足以判断交互结果。', trace)
        changed = (
            start_snapshot.final_url != end_snapshot.final_url
            or start_snapshot.title != end_snapshot.title
            or start_snapshot.body_text != end_snapshot.body_text
        )
        return self.run(
            spec,
            CheckStatus.PASS if trace.status == "completed" and changed else CheckStatus.FAIL,
            "点击后出现了可观察的页面或内容变化"
            if trace.status == "completed" and changed
            else "点击后未观察到可验证的页面、标题或内容变化",
            trace,
        )


class PurchaseSelectionStateConsistencyChecker(TransitionChecker):
    """Verify that a requested purchase configuration is selected and echoed."""

    def execute(self, spec, trace, start_snapshot, end_snapshot) -> CheckRun:
        del start_snapshot
        quote = end_snapshot.quote_state
        requested = [str(value).strip() for value in quote.get("requested_options", []) if str(value).strip()]
        selected = [str(value) for value in quote.get("selected_options", [])]
        summary = {str(key): str(value) for key, value in (quote.get("summary") or {}).items()}
        selected_text = " ".join(selected)
        summary_text = " ".join(summary.values())
        missing_selected = [value for value in requested if value not in selected_text]
        missing_summary = [value for value in requested if value not in summary_text]
        passed = bool(requested) and not missing_selected and not missing_summary
        if passed:
            reason = "所选购买配置已同时反映在卡片选中态和订单摘要中：" + "、".join(requested)
        else:
            details = []
            if missing_selected:
                details.append("未获得选中态：" + "、".join(missing_selected))
            if missing_summary:
                details.append("订单摘要未同步：" + "、".join(missing_summary))
            reason = "；".join(details) or "未采集到可验证的购买配置状态"
        run = self.run(spec, CheckStatus.PASS if passed else CheckStatus.FAIL, reason, trace)
        run.evidence.extend([
            "requested=" + " | ".join(requested),
            "selected=" + " | ".join(selected),
            "summary=" + " | ".join(f"{key}:{value}" for key, value in summary.items()),
        ])
        if not passed:
            run.suggestion = "点击配置卡后同步更新选中态、套餐信息与购买时长摘要。"
        return run


class PriceCalculationConsistencyChecker(TransitionChecker):
    """Recalculate a displayed quote from the price factors disclosed on-page."""

    _unit_price = re.compile(
        r"[¥￥$]\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)\s*/\s*(月|年|months?|years?)",
        re.IGNORECASE,
    )
    _discount = re.compile(r"(\d+(?:\.\d+)?)\s*折")
    _discount_percent = re.compile(r"(\d+(?:\.\d+)?)\s*%\s*off", re.IGNORECASE)
    _months = re.compile(r"(\d+)\s*个?月")
    _years = re.compile(r"(\d+)\s*年")
    _months_en = re.compile(r"(\d+)\s*months?", re.IGNORECASE)
    _years_en = re.compile(r"(\d+)\s*years?", re.IGNORECASE)

    def execute(self, spec, trace, start_snapshot, end_snapshot) -> CheckRun:
        del start_snapshot
        quote = end_snapshot.quote_state
        complexities = [str(value) for value in quote.get("pricing_complexities", [])]
        selected = " ".join(str(value) for value in (
            list(quote.get("selected_options", []))
            + list(quote.get("requested_option_details", []))
        ))
        summary = {str(key): str(value) for key, value in (quote.get("summary") or {}).items()}
        requested = " ".join(str(value) for value in quote.get("requested_options", []))
        duration = next((value for key, value in summary.items()
                         if re.search(r"时长|周期|duration|period|term", key, re.IGNORECASE)),
                        selected + " " + requested)
        price_match = self._unit_price.search(selected)
        try:
            actual = Decimal(str(quote.get("total")))
        except (InvalidOperation, TypeError):
            return self._needs_verification(spec, trace, "未识别到最终配置费用")
        if not price_match:
            return self._needs_verification(spec, trace, "未能从当前选中套餐识别单价和计费单位")
        unit_price = Decimal(price_match.group(1).replace(",", ""))
        raw_unit = price_match.group(2).casefold()
        unit = "月" if raw_unit in {"月", "month", "months"} else "年"
        quantity = self._quantity(duration, unit)
        if quantity is None:
            return self._needs_verification(spec, trace, f"无法把购买时长“{duration}”换算为{unit}数")
        discount_match = self._discount.search(selected + " " + requested)
        percent_match = self._discount_percent.search(selected + " " + requested)
        if discount_match:
            discount = Decimal(discount_match.group(1)) / Decimal(10)
        elif percent_match:
            discount = Decimal(1) - Decimal(percent_match.group(1)) / Decimal(100)
        else:
            discount = Decimal(1)
        expected = (unit_price * quantity * discount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        difference = (actual - expected).copy_abs().quantize(Decimal("0.01"))
        formula = f"¥{unit_price:.2f} × {quantity} × {discount} = ¥{expected:.2f}"
        if complexities and difference > Decimal("0.01"):
            run = self._needs_verification(
                spec,
                trace,
                f"按页面已明确的信息计算为 {formula}，页面显示 ¥{actual:.2f}，差额 ¥{difference:.2f}；"
                f"但页面还显示未结构化的计价因子：{'、'.join(complexities)}",
            )
            self._append_calculation_evidence(
                run, unit_price, unit, duration, quantity, discount, actual, expected, difference,
            )
            return run
        passed = difference <= Decimal("0.01")
        reason = (
            f"页面配置费用 ¥{actual:.2f} 与明示规则计算结果一致：{formula}。"
            if passed else
            f"页面配置费用 ¥{actual:.2f} 与明示规则计算结果 ¥{expected:.2f} 不一致，差额 ¥{difference:.2f}（{formula}）。"
        )
        run = self.run(spec, CheckStatus.PASS if passed else CheckStatus.FAIL, reason, trace)
        self._append_calculation_evidence(
            run, unit_price, unit, duration, quantity, discount, actual, expected, difference,
        )
        if complexities:
            run.evidence.append("pricing_complexities=" + "、".join(complexities))
        if not passed:
            run.suggestion = "按页面明示单价、购买时长和折扣修正配置费用，或补充当前金额包含的其他计价项。"
        return run

    @staticmethod
    def _append_calculation_evidence(
        run: CheckRun,
        unit_price: Decimal,
        unit: str,
        duration: str,
        quantity: Decimal,
        discount: Decimal,
        actual: Decimal,
        expected: Decimal,
        difference: Decimal,
    ) -> None:
        run.evidence.extend([
            f"unit_price={unit_price}", f"billing_unit={unit}", f"duration={duration}",
            f"quantity={quantity}", f"discount={discount}", f"actual={actual}",
            f"expected={expected}", f"difference={difference}",
        ])

    def _needs_verification(self, spec, trace, reason: str) -> CheckRun:
        run = self.run(spec, CheckStatus.NEEDS_VERIFICATION, reason + "，当前证据不足以作算术判断。", trace)
        run.suggestion = "在购买配置区明确展示单价、计费周期、购买数量、折扣和最终费用。"
        return run

    def _quantity(self, duration: str, unit: str) -> Decimal | None:
        folded = duration.casefold()
        if unit == "年":
            match = self._years.search(duration) or self._years_en.search(duration)
            return Decimal(match.group(1)) if match else Decimal(1) if (
                "包年" in duration or "annual" in folded or "yearly" in folded
            ) else None
        if "连续包年" in duration or "annual" in folded or "yearly" in folded:
            return Decimal(12)
        if "连续包月" in duration or "monthly" in folded:
            return Decimal(1)
        if match := self._months.search(duration) or self._months_en.search(duration):
            return Decimal(match.group(1))
        if match := self._years.search(duration) or self._years_en.search(duration):
            return Decimal(match.group(1)) * Decimal(12)
        return None


class InteractionFailureGuidanceChecker(TransitionChecker):
    """Do not treat a post-click error page without recovery guidance as success."""

    def execute(self, spec, trace, start_snapshot, end_snapshot) -> CheckRun:
        del start_snapshot
        if trace.status != 'completed' or end_snapshot.content_ready is False:
            return self.run(
                spec,
                CheckStatus.NEEDS_VERIFICATION,
                '结果页尚未完成加载或交互已暂停，未对错误页恢复指引作出判断。',
                trace,
            )
        text = f"{end_snapshot.title}\n{end_snapshot.body_text}".casefold()
        error = any(value in text for value in (
            '404 not found', '500 internal server error', '页面出错', '访问出错',
            '发生错误', 'error occurred', 'an error has occurred',
        ))
        guidance = any(value in text for value in ("返回", "重试", "联系", "帮助", "back", "retry", "support"))
        return self.run(
            spec,
            CheckStatus.FAIL if error and not guidance else CheckStatus.PASS,
            "点击后出现错误且未提供下一步处理指引"
            if error and not guidance
            else "未发现无引导的错误结果",
            trace,
        )
