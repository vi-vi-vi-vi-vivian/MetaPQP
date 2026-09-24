"""Interpret local UI states and explicit navigation contracts."""

from urllib.parse import parse_qsl, urlsplit


def local_state_feedback(before: dict, after: dict) -> str | None:
    for key, label in (('expanded', '展开状态'), ('open', '开合状态'), ('selected', '选中状态'), ('checked', '勾选状态')):
        old, new = before.get(key), after.get(key)
        if old is not None and new is not None and old != new:
            if (key == 'expanded' and after.get('panel_visible') is not None
                    and after['panel_visible'] != (new == 'true')):
                return None
            return f'{label}已正常切换（{old} → {new}）；收起或取消选中也是有效交互。'
    if (before.get('expanded') == after.get('expanded') == 'true'
            and before.get('panel_visible') and after.get('panel_visible')
            and after.get('panel_text', '').strip()):
        return '该区域原本已展开，点击后内容仍可见；保持已展开状态不视为内容缺失。'
    if (before.get('selection_control') and after.get('selection_control')
            and before.get('selected') is True and after.get('selected') is True):
        return '该配置原本已选中，点击后仍保持选中；组合中的其他配置由订单摘要继续核对。'
    return None


def subscription_selection_feedback(candidate, final_url: str, body_text: str) -> tuple[str, str, str] | None:
    """Verify that a plan card carries its user's choice into the next step."""
    expected = candidate.element.href
    if candidate.kind != 'navigation' or not expected:
        return None
    source, destination = urlsplit(expected), urlsplit(final_url)
    if ('resourcePlanManagement' not in source.fragment or source.hostname != destination.hostname
            or source.path != destination.path or source.fragment != destination.fragment
            or dict(parse_qsl(source.query)) != dict(parse_qsl(destination.query))):
        return None
    plans = ('Lite', 'Standard', 'Pro', 'Max')
    selected_plan = next((plan for plan in plans if plan.casefold() in candidate.surrounding_text.casefold()), None)
    if not selected_plan:
        return None
    compact = ' '.join(body_text.split())
    selected = __import__('re').search(
        rf'{selected_plan}.{{0,80}}(?:已选|当前套餐|已选择|selected|current plan|下单|确认订单|立即购买)',
        compact,
        __import__('re').IGNORECASE,
    )
    if selected:
        return ('pass',
                f'已进入资源套餐管理页，并明确显示 {selected_plan} 已被带入后续订阅步骤。',
                '')
    return ('fail',
            f'点击 {selected_plan} 的“立即订阅”后进入通用资源套餐管理页，但未显示 {selected_plan} 已选中、进入下单流程或订阅成功。用户需要重新识别并选择套餐。',
            f'在跳转参数或会话状态中携带 {selected_plan} 套餐标识；目标页加载后自动选中该套餐，并显示“确认订阅／下单”等下一步操作。')
