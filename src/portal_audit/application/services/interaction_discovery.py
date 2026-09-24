"""Discover page interactions and classify whether automation may execute them."""

from __future__ import annotations

import re
from itertools import product
from urllib.parse import urlsplit

from portal_audit.domain.models import (
    ActionRiskLevel,
    InteractionCandidate,
    PageSnapshot,
)


class InteractionDiscovery:
    """A conservative, product-neutral safety classifier for visible controls."""

    _blocked = re.compile(
        r"支付|付款|提交订单|确认购买|立即开通|创建|删除|释放|停用|"
        r"发送验证码|退出登录|pay|submit|delete|create|terminate|logout",
        re.IGNORECASE,
    )
    _local = re.compile(
        r"详情|了解|查看|帮助|文档|计费|规则|展开|收起|more|detail|help|"
        r"documentation|billing|expand|collapse",
        re.IGNORECASE,
    )

    def discover(self, snapshot: PageSnapshot) -> list[InteractionCandidate]:
        surrounding = {
            item.element_ref: item.surrounding_text
            for item in snapshot.evidence_elements
            if item.element_ref
        }
        candidates: list[InteractionCandidate] = []
        configuration_groups: dict[str, list] = {}
        for element in snapshot.interactive_elements:
            if not element.enabled or not element.selector:
                continue
            # Global chrome is tested separately as a shared asset.  A product
            # Page audit focuses on its own task flow and excludes header/footer.
            if element.page_region in {"header", "footer", "navigation"}:
                continue
            if element.configuration_group and element.configuration_option:
                configuration_groups.setdefault(element.configuration_group, []).append(element)
                continue
            if (
                element.tag not in {"a", "button", "input", "select", "textarea", "summary"}
                and not element.has_click_handler
                and not element.role
                and element.aria_expanded is None
                and element.aria_controls is None
            ):
                # A focusable layout child (often an icon or swatch nested in
                # a real control) is not itself a dependable click target.
                continue
            if (element.image_only and not element.href and not element.has_click_handler
                    and not element.role and element.aria_expanded is None and not element.aria_controls):
                # Image wrappers often use <a> only for hover styling.
                continue
            label = " ".join(filter(None, (element.text, element.href or "")))
            decision, kind, risk, reason = self._classify(element.tag, element.role, label, element.href, snapshot.final_url)
            if kind == 'unknown' and element.aria_expanded in {'true', 'false'}:
                decision, kind, risk, reason = 'allowed', 'disclosure', ActionRiskLevel.LOCAL_STATE, '具有展开状态及关联内容区域的折叠控件'
            candidates.append(
                InteractionCandidate(
                    element=element,
                    kind=kind,
                    risk_level=risk,
                    execution_decision=decision,
                    decision_reason=reason,
                    surrounding_text=surrounding.get(element.element_ref or "", ""),
                )
            )
        candidates.extend(self._configuration_candidates(configuration_groups))
        return candidates

    @staticmethod
    def _configuration_candidates(groups: dict[str, list]) -> list[InteractionCandidate]:
        """Build isolated quote scenarios from safe, repeated selection groups.

        Small purchase forms are exhaustively covered.  Larger forms retain a
        bounded one-option-at-a-time fallback so a page cannot create an
        unbounded browser workload.
        """
        option_groups = []
        for values in groups.values():
            unique = {}
            for item in values:
                key = (item.configuration_option or item.text).strip().casefold()
                current = unique.get(key)
                # Prefer the outer card (shorter DOM path), while preserving a
                # positively detected selected state if only one duplicate has it.
                if current is None or (
                    item.selection_selected and not current.selection_selected
                ) or (
                    item.selection_selected == current.selection_selected
                    and item.selector.count(">") < current.selector.count(">")
                ):
                    unique[key] = item
            if len(unique) >= 2:
                option_groups.append(list(unique.values()))
        if not option_groups:
            return []
        combinations = list(product(*option_groups))
        if len(combinations) > 40:
            baseline = [next((item for item in values if item.selection_selected), values[0])
                        for values in option_groups]
            combinations = []
            for group_index, values in enumerate(option_groups):
                for value in values:
                    scenario = list(baseline)
                    scenario[group_index] = value
                    combinations.append(tuple(scenario))
        result = []
        for steps in combinations:
            labels = [item.configuration_option or item.text for item in steps]
            synthetic = steps[0].model_copy(update={
                "text": " · ".join(labels),
                "selection_selected": all(item.selection_selected for item in steps),
            })
            result.append(InteractionCandidate(
                element=synthetic,
                kind="quote_configuration",
                risk_level=ActionRiskLevel.LOCAL_STATE,
                execution_decision="allowed",
                decision_reason="套餐、规格或购买时长选择只更新本地报价，不提交订单",
                surrounding_text="购买配置组合：" + "；".join(labels),
                configuration_steps=list(steps),
            ))
        return result

    def _classify(self, tag: str, role: str | None, label: str, href: str | None, page_url: str):
        if self._blocked.search(label):
            return "blocked", "mutation", ActionRiskLevel.MUTATING, "命中不可逆或交易操作安全策略"
        if tag in {"select", "summary"} or role in {"combobox", "checkbox", "radio", "switch"}:
            return "allowed", "local_state", ActionRiskLevel.LOCAL_STATE, "展开或切换本地控件状态"
        if tag in {"input", "textarea"}:
            return "blocked", "form_input", ActionRiskLevel.MUTATING, "表单输入可能修改业务状态"
        if not href and label.strip() in {"取消", "关闭", "返回"}:
            return "allowed", "local_state", ActionRiskLevel.LOCAL_STATE, "取消或返回属于可逆的本页操作"
        if role == "tab":
            return "allowed", "local_state", ActionRiskLevel.LOCAL_STATE, "Tab 切换为局部只读状态"
        if href:
            destination = urlsplit(href)
            current = urlsplit(page_url)
            if destination.scheme and destination.scheme not in {"http", "https"}:
                return "blocked", "external_protocol", ActionRiskLevel.CONFIRMATION_ONLY, "非网页协议、下载或外部客户端操作不自动执行"
            if destination.scheme in {"http", "https"} and destination.netloc and destination.netloc != current.netloc:
                return "allowed", "navigation", ActionRiskLevel.READ_ONLY, "跨站导航为只读操作"
            return "allowed", "navigation", ActionRiskLevel.READ_ONLY, "站内导航为只读操作"
        if self._local.search(label):
            return "allowed", "disclosure", ActionRiskLevel.LOCAL_STATE, "信息披露或局部状态操作"
        if not href and re.search(r"[？?]$", label):
            return "allowed", "disclosure", ActionRiskLevel.LOCAL_STATE, "无跳转地址的信息展开入口"
        if not href and label.strip() in {"+", "＋", "-", "－"}:
            return "allowed", "disclosure", ActionRiskLevel.LOCAL_STATE, "符号型信息展开入口"
        return "blocked", "unknown", ActionRiskLevel.CONFIRMATION_ONLY, "未能证明该按钮为只读交互"
