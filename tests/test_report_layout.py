from pathlib import Path

from bs4 import BeautifulSoup

from portal_audit.interfaces.reporting.output_writer import OutputWriter


def test_report_groups_page_and_transition_findings_in_one_issue_register(tmp_path):
    audit = {
        "run": {"job_id": "layout-test"},
        "summary": {"p0": 0, "p1": 0, "p2": 1},
        "sections": [{
            "title": "Demo 页面", "url": "https://example.test", "name": "awareness",
            "coverage_status": {"status": "verified"}, "authentication": {"status": "not_requested"},
            "evidence_screenshots": [], "annotated_screenshot": None, "screenshot": None,
        }],
        "pages": [{"context": {"journey": "awareness"}}],
        "issues": [{
            "id": "page-copy", "marker": 1, "severity": "p2", "title": "页面文案不清晰", "evidence": "术语未解释",
            "locate": [], "standard_refs": [], "suggestion_after": "补充解释", "confidence": 0.9,
            "verification_status": "verified",
        }],
        "interaction_traces": [{
            "candidate": {"candidate_id": "buy-lite", "kind": "navigation", "decision_reason": "站内导航", "surrounding_text": "Lite", "element": {"text": "立即订阅", "tag": "a"}},
            "trace": {"status": "completed", "termination_reason": "完成"}, "before_snapshot": {}, "after_snapshot": None,
        }, {
            "candidate": {"candidate_id": "edgeone-doc", "kind": "navigation", "decision_reason": "站外文档", "surrounding_text": "帮助文档", "element": {"text": "查看更多", "tag": "a"}},
            "trace": {"status": "paused", "termination_reason": "自动化访问遇到站点连接安全检查"}, "before_snapshot": {}, "after_snapshot": None,
        }],
        "check_runs": [{
            "invocation_id": "transition-intent-result-consistency__buy-lite", "check_spec_id": "transition-intent-result-consistency",
            "status": "fail", "title": "点击结果应符合用户预期", "reason": "未带入套餐选择", "suggestion": "携带套餐标识",
        }],
    }
    html = OutputWriter(Path(tmp_path), model_name="", model_enabled=False)._report_html(audit)
    page = BeautifulSoup(html, "html.parser")

    assert [item["href"] for item in page.select(".side-nav a")] == [
        "#overview", "#issues", "#interactions", "#evidence", "#checks",
    ]
    issue_titles = page.select("#issues h3")
    assert [item.get_text(strip=True) for item in issue_titles] == [
        "页面文案不清晰", "交互／跳转问题：立即订阅 · Lite",
    ]
    assert page.select_one("#interaction-1")
    assert page.select_one("#evidence")
    assert page.select_one("#checks")
    assert not page.select_one("#context")
    assert len(page.select("#issues .finding-list > .finding")) == 2
    assert len(page.select("#issues .issue-visual")) == 2
    assert "EdgeOne" not in page.select_one("#issues").get_text()
    assert "自动化访问遇到站点连接安全检查" in page.select_one("#interactions").get_text()


def test_report_renders_quote_calculations_in_a_separate_pricing_table(tmp_path):
    audit = {
        "run": {"job_id": "pricing-layout-test"},
        "summary": {"p0": 0, "p1": 0, "p2": 0},
        "sections": [{
            "title": "OfficeAce 购买", "url": "https://example.test/purchase", "name": "purchase",
            "coverage_status": {"status": "verified"}, "authentication": {"status": "authenticated"},
            "evidence_screenshots": [], "annotated_screenshot": None, "screenshot": None,
        }],
        "pages": [{"context": {"journey": "purchase"}}],
        "issues": [],
        "interaction_traces": [{
            "candidate": {
                "candidate_id": "quote-annual", "kind": "quote_configuration",
                "decision_reason": "本地报价", "surrounding_text": "购买配置",
                "element": {"text": "个人高级版 · 连续包年", "tag": "div"},
                "configuration_steps": [
                    {"text": "个人高级版", "configuration_option": "个人高级版"},
                ],
            },
            "trace": {"status": "completed", "termination_reason": "安全交互已执行"},
            "before_snapshot": {},
            "after_snapshot": {"quote_state": {
                "total": "1663.20", "summary": {"购买时长": "连续包年"},
            }},
        }],
        "check_runs": [{
            "invocation_id": "price-calculation-consistency__quote-annual",
            "check_spec_id": "price-calculation-consistency", "status": "pass",
            "title": "配置费用应符合明示计价规则",
            "reason": "页面配置费用 ¥1663.20 与明示规则计算结果一致。",
            "evidence": [
                "unit_price=198.00", "billing_unit=月", "duration=连续包年",
                "quantity=12", "discount=0.7", "actual=1663.20",
                "expected=1663.20", "difference=0.00",
            ],
        }, {
            "invocation_id": "purchase-selection-state-consistency__quote-annual",
            "check_spec_id": "purchase-selection-state-consistency", "status": "pass",
            "title": "购买配置选择应同步", "reason": "配置已同步", "evidence": [],
        }],
    }

    report = OutputWriter(Path(tmp_path), model_name="", model_enabled=False)._report_html(audit)
    page = BeautifulSoup(report, "html.parser")

    assert page.select_one(".side-nav a[href='#pricing']")
    pricing = page.select_one("#pricing")
    assert "个人高级版 × 连续包年" in pricing.get_text(" ", strip=True)
    assert "¥198.00/月 × 12月 × 0.7（7折） = ¥1663.20" in pricing.get_text(" ", strip=True)
    assert "¥0.00" in pricing.get_text(" ", strip=True)
    assert "金额一致" in pricing.get_text(" ", strip=True)
    assert "个人高级版" not in page.select_one("#interactions").get_text()
    assert "配置费用应符合明示计价规则" not in page.select_one("#checks").get_text()
