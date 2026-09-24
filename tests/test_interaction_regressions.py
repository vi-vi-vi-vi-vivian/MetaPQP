from unittest.mock import AsyncMock, Mock

import pytest

from portal_audit.adapters.browser.playwright_browser import _capture_page_segments
from portal_audit.application.services.interaction_discovery import InteractionDiscovery
from portal_audit.domain.models import InteractiveElement, PageSnapshot
from portal_audit.interfaces.reporting.output_writer import _interaction_result


async def test_last_segment_records_clamped_scroll_position(tmp_path):
    class Page:
        top = 0
        wait_for_timeout = AsyncMock()
        screenshot = AsyncMock()

        async def evaluate(self, script, arg=None):
            if arg is not None:
                self.top = min(arg, 1786)
            if script == 'window.scrollY':
                return self.top
            return None

    artifacts = await _capture_page_segments(
        Page(), tmp_path, {'width': 1440, 'height': 1000}, {'width': 1440, 'height': 2786}
    )
    assert [a.metadata['top'] for a in artifacts] == [0, 1000, 1786]
    assert 2034.25 - artifacts[-1].metadata['top'] == 248.25


def test_discovery_keeps_unnamed_controls_and_select_but_excludes_global_chrome():
    snapshot = PageSnapshot(page_id='test', requested_url='https://example.test',
                            final_url='https://example.test', title='', viewport={'width': 1440, 'height': 1000}, interactive_elements=[
        InteractiveElement(tag='button', text='导航', selector='#nav', page_region='header'),
        InteractiveElement(tag='a', text='帮助', selector='#footer-help', page_region='footer'),
        InteractiveElement(tag='a', text='产品目录', selector='#console-services', page_region='navigation'),
        InteractiveElement(tag='button', selector='#icon', page_region='content'),
        InteractiveElement(tag='select', selector='#options', page_region='content'),
        InteractiveElement(tag='a', text='是否需要开通服务？', selector='#faq', page_region='content'),
        InteractiveElement(tag='span', selector='#focusable-decoration', page_region='content'),
    ])
    candidates = InteractionDiscovery().discover(snapshot)
    assert [c.element.selector for c in candidates] == ['#icon', '#options', '#faq']
    assert [c.execution_decision for c in candidates] == ['blocked', 'allowed', 'allowed']


def test_pending_clicks_are_not_reported_as_safety_skips_or_passes():
    result = _interaction_result({'candidate': {'candidate_id': 'one'},
                                  'trace': {'status': 'pending', 'termination_reason': '浏览器未启动'}}, [])
    assert '待补跑' in result
    assert '安全策略跳过' not in result
    assert '通过' not in result


async def test_configuration_locator_uses_option_text_and_outermost_card():
    from portal_audit.adapters.browser.playwright_browser import PlaywrightBrowser

    semantic_scope = Mock()
    semantic_scope.evaluate_all = AsyncMock(return_value={'count': 1, 'candidates': 2})
    marked = Mock(count=AsyncMock(return_value=1))
    page = Mock()
    page.locator.side_effect = lambda selector: semantic_scope if selector == 'div,li' else marked
    step = InteractiveElement(
        tag='div', text='个人高级版', selector='html > body > div:nth-of-type(4)',
        configuration_group='#plans', configuration_option='个人高级版',
    )

    locator = await PlaywrightBrowser._interaction_locator(page, step, 0)

    assert locator is marked
    request = semantic_scope.evaluate_all.await_args.args[1]
    assert request == {'option': '个人高级版', 'marker': 'metapqp-config-0'}
    assert page.locator.call_args_list[-1].args[0] == '[data-metapqp-config-target="metapqp-config-0"]'


@pytest.mark.parametrize('auth_case', ['none', 'password', 'challenge', 'sms_after_password'])
async def test_popup_callback_uses_real_playwright_wrapper(tmp_path, monkeypatch, auth_case):
    from playwright._impl._impl_to_api_mapping import ImplToApiMapping

    from portal_audit.adapters.artifacts.local_store import LocalArtifactStore
    from portal_audit.adapters.browser import playwright_browser as module
    from portal_audit.domain.models import PageTarget

    mapping = ImplToApiMapping()
    page = Mock()
    popup = Mock()
    for item, url in ((page, 'https://example.test'), (popup, 'https://example.test/detail')):
        item.url = url
        for name in ('goto', 'wait_for_timeout', 'screenshot', 'wait_for_load_state', 'close'):
            setattr(item, name, AsyncMock())
        item.title = AsyncMock(return_value=url)
    callbacks = {}

    def on(event, handler):
        # This is the real wrapper that rejected list.append in production.
        callbacks[event] = mapping.wrap_handler(handler)

    page.on = on
    locator = Mock(count=AsyncMock(return_value=1), scroll_into_view_if_needed=AsyncMock())
    locator.evaluate = AsyncMock(return_value={})

    async def click(**kwargs):
        callbacks['popup'](popup)

    locator.click = AsyncMock(side_effect=click)
    page.locator.return_value = locator
    context = Mock(new_page=AsyncMock(return_value=page), close=AsyncMock())
    browser = Mock(new_context=AsyncMock(return_value=context), close=AsyncMock())
    manager = AsyncMock()
    monkeypatch.setattr(module, 'async_playwright', lambda: manager)
    monkeypatch.setattr(module, 'launch_chromium', AsyncMock(return_value=browser))
    adapter = module.PlaywrightBrowser(LocalArtifactStore(tmp_path))
    adapter._wait_for_interaction_content = AsyncMock(return_value={'ready': True, 'text': 'content'})
    from portal_audit.application.ports.auth import BrowserAuthSession
    from portal_audit.domain.models import AuthenticationSummary
    session = None
    if auth_case != 'none':
        adapter.auth_provider = Mock()
        adapter.auth_provider.requires_challenge = AsyncMock(side_effect=[auth_case == 'challenge', False])
        adapter.auth_provider._is_login_url.side_effect = [False] if auth_case == 'challenge' else [True, False]
        adapter.auth_provider.continue_password_login = AsyncMock(return_value=BrowserAuthSession(
            AuthenticationSummary(status='challenge_required' if auth_case == 'sms_after_password' else 'authenticated')))
    monkeypatch.setattr(adapter, '_primary_body', lambda _: Mock(inner_text=AsyncMock(return_value='content')))
    snapshot = PageSnapshot(page_id='test', requested_url=page.url, final_url=page.url,
                            title='', viewport={'width': 1440, 'height': 1000},
                            interactive_elements=[InteractiveElement(tag='a', text='详情', href=popup.url, selector='#detail')])
    traces = await adapter.inspect_interactions(
        PageTarget(page_id='test', url=page.url, source='web', device='desktop', locale='zh-CN'),
        'popup-test', InteractionDiscovery().discover(snapshot) * 2, session
    )
    assert len(traces) == 2
    paused = auth_case in {'challenge', 'sms_after_password'}
    assert traces[0].trace.status == ('paused' if paused else 'completed')
    assert traces[0].after_snapshot.final_url == popup.url
    assert popup.screenshot.await_count == 2
    assert popup.close.await_count == 2
    assert browser.new_context.await_count == 2
    if paused:
        assert traces[1].trace.status == 'completed'
        assert traces[1].after_snapshot is not None
        assert locator.click.await_count == 2
    if auth_case == 'challenge':
        adapter.auth_provider.continue_password_login.assert_not_awaited()
    elif auth_case == 'password':
        assert traces[0].after_snapshot.authentication.status == 'authenticated'
        adapter.auth_provider.continue_password_login.assert_awaited_once_with(popup, persist=False)


def test_hover_image_is_excluded_but_linked_image_and_disclosure_remain():
    snapshot = PageSnapshot(page_id='test', requested_url='https://example.test', final_url='https://example.test',
                            title='', viewport={'width': 1440, 'height': 1000}, interactive_elements=[
        InteractiveElement(tag='a', text='图片控件（资源名：logo-kimi.png）', selector='#logo', image_only=True),
        InteractiveElement(tag='a', text='模型详情', selector='#link', image_only=True, href='https://example.test/detail'),
        InteractiveElement(tag='a', text='多模型灵活接入，主流大模型全支持', selector='#expand', aria_expanded='true', aria_controls='content'),
        InteractiveElement(tag='a', text='Token Plan 使用过程中是否会收集数据用于模型训练等用途？', selector='#faq'),
    ])
    candidates = InteractionDiscovery().discover(snapshot)
    assert [c.element.selector for c in candidates] == ['#link', '#expand', '#faq']
    assert all(c.execution_decision == 'allowed' for c in candidates)


def test_question_and_symbol_buttons_are_safe_disclosures_without_aria_metadata():
    snapshot = PageSnapshot(page_id='test', requested_url='https://example.test', final_url='https://example.test',
                            title='', viewport={'width': 1440, 'height': 1000}, interactive_elements=[
        InteractiveElement(tag='button', text='什么是果办 OfficeAce？', selector='#faq'),
        InteractiveElement(tag='button', text='+', selector='#expand'),
    ])
    candidates = InteractionDiscovery().discover(snapshot)
    assert [(item.kind, item.execution_decision) for item in candidates] == [
        ('disclosure', 'allowed'), ('disclosure', 'allowed'),
    ]


def test_cancel_is_safe_but_a_focusable_layout_child_is_not_a_click_candidate():
    snapshot = PageSnapshot(page_id='test', requested_url='https://example.test', final_url='https://example.test',
                            title='', viewport={'width': 1440, 'height': 1000}, interactive_elements=[
        InteractiveElement(tag='button', text='取消', selector='#cancel'),
        InteractiveElement(tag='span', selector='#color-swatch'),
    ])
    candidates = InteractionDiscovery().discover(snapshot)
    assert [(item.element.selector, item.kind, item.execution_decision) for item in candidates] == [
        ('#cancel', 'local_state', 'allowed'),
    ]


def test_disclosure_result_shows_added_answer_and_escapes_content():
    from portal_audit.interfaces.reporting.output_writer import _interaction_outcome
    item = {'before_snapshot': {'final_url': 'https://example.test', 'body_text': '问题\n页脚'},
            'after_snapshot': {'final_url': 'https://example.test', 'body_text': '问题\n答复：无需额外开通。<script>\n页脚'}}
    result = _interaction_outcome(item)
    assert '答复：无需额外开通。&lt;script&gt;' in result
    assert 'https://example.test' not in result
    assert '页脚' not in result


def test_interaction_results_do_not_mix_same_named_buttons():
    runs = [{'invocation_id': 'reachability__first', 'status': 'pass', 'title': '可达性', 'reason': '结果可见'},
            {'invocation_id': 'reachability__second', 'status': 'fail', 'title': '可达性', 'reason': '目标不可用'}]
    result = _interaction_result({'candidate': {'candidate_id': 'first'}}, runs)
    assert '通过' in result
    assert '目标不可用' not in result
    assert '（1 项检查）' in result


def test_successful_error_guard_is_hidden_from_human_interaction_output():
    result = _interaction_result({'candidate': {'candidate_id': 'first'}}, [
        {'invocation_id': 'interaction-failure-guidance__first', 'status': 'pass', 'title': '错误页是否提供恢复指引', 'reason': '未发现错误页'},
        {'invocation_id': 'feedback__first', 'status': 'pass', 'title': '交互反馈', 'reason': '页面已更新'},
    ])
    assert '错误页是否提供恢复指引' not in result
    assert '页面已更新' in result
    assert '（1 项检查）' in result


def test_terminology_pending_is_a_p2_finding_without_claiming_verified():
    from pathlib import Path

    from portal_audit.application.services.assessment_builder import AssessmentBuilder
    from portal_audit.domain.models import CheckRun, PageContext
    from portal_audit.domain.registry import CheckSpecRegistry, StandardsRegistry
    root = Path(__file__).parents[1]
    registry = CheckSpecRegistry(root / 'config/check_specs', StandardsRegistry(root / 'config/standards').load()).load()
    spec = registry.get('terminology-clarity')
    run = CheckRun(check_spec_id=spec.id, check_spec_version=spec.version, status='needs_verification',
                   title=spec.title, reason='当前内容未解释计量单位', severity='p2', executor_id=spec.executor.capability_id)
    snapshot = PageSnapshot(page_id='test', requested_url='https://example.test', final_url='https://example.test',
                            title='', viewport={'width': 1440, 'height': 1000})
    result = AssessmentBuilder(registry).build(snapshot, PageContext(), [run])
    assert len(result.findings) == 1
    assert result.findings[0].severity == 'p2'
    assert result.findings[0].verification_status == 'pending'
