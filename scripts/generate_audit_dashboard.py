"""Generate a self-contained HTML dashboard from page audit artifacts."""

from __future__ import annotations

import argparse
import html
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

MODULE_BY_PAGE = {
    "orchard-home": "A",
    "agents-index": "A",
    "agentarts-ecosystem": "A",
    "models-index": "A",
    "tokenplan-awareness": "A",
    "industry-ai-index": "A",
    "skills-market": "C",
    "ai-shell-awareness": "C",
    "openjiuwen-external": "C",
}

PRODUCT_LABELS = {
    "agentarts": "AgentArts",
    "agentorchard": "智果园",
    "agri-explorer": "农科发现",
    "ai-pathology": "智慧病理",
    "ai-shell": "AI Shell",
    "cloudrobo": "CloudRobo",
    "codearts": "CodeArts",
    "doczip": "DocZip",
    "health-assistant": "健康管理助手",
    "industry-ai": "行业 AI",
    "maas": "MaaS",
    "officeace": "OfficeAce",
    "openjiuwen": "openJiuwen",
    "skills": "Skills 市场",
    "tokenplan": "Token Plan",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("output/web"))
    parser.add_argument("--output", type=Path, default=Path("output/dashboard.html"))
    return parser.parse_args()


def collect_runs(input_root: Path, output_path: Path) -> list[dict]:
    runs: list[dict] = []
    for audit_path in sorted(input_root.glob("**/audit.json")):
        payload = json.loads(audit_path.read_text(encoding="utf-8"))
        page = payload["pages"][0]
        target = page["target"]
        snapshot = page["snapshot"]
        summary = payload["summary"]
        report_path = audit_path.with_name("report.html")
        if not report_path.exists():
            raise FileNotFoundError(f"Missing HTML report for {audit_path}")
        checks = Counter(issue.get("check_spec_id", "unknown") for issue in payload["issues"])
        auth = snapshot.get("authentication") or {}
        runs.append(
            {
                "module": MODULE_BY_PAGE.get(target["page_id"], "B"),
                "product": target.get("product") or "unknown",
                "product_label": PRODUCT_LABELS.get(
                    target.get("product") or "unknown", target.get("product") or "未知产品"
                ),
                "page_id": target["page_id"],
                "url": target["url"],
                "surface": target.get("page_surface", "portal"),
                "device": target.get("device", "desktop"),
                "locale": target.get("locale", "zh-CN"),
                "job_id": payload["run"]["job_id"],
                "status": payload["run"]["status"],
                "http_status": snapshot.get("http_status"),
                "auth_status": auth.get("status"),
                "issue_count": summary["issue_count"],
                "p0": summary["p0"],
                "p1": summary["p1"],
                "p2": summary["p2"],
                "checks": dict(checks),
                "report": report_path.relative_to(output_path.parent).as_posix(),
            }
        )
    return runs


def build_html(runs: list[dict]) -> str:
    now = datetime.now().astimezone()
    generated_at = now.strftime("%Y-%m-%d %H:%M:%S %Z")
    build_id = now.strftime("%Y%m%d%H%M%S%f")
    data = json.dumps(runs, ensure_ascii=False).replace("</", "<\\/")
    return (
        TEMPLATE.replace("__RUN_DATA__", data)
        .replace("__GENERATED_AT__", html.escape(generated_at))
        .replace("__REPORT_COUNT__", str(len(runs)))
        .replace("__BUILD_ID__", build_id)
    )


def main() -> int:
    args = parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    runs = collect_runs(args.input, args.output)
    if not runs:
        raise SystemExit(f"No audit.json files found below {args.input}")
    args.output.write_text(build_html(runs), encoding="utf-8")
    print(f"Generated {args.output} from {len(runs)} reports")
    return 0


TEMPLATE = r'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="dashboard-build" content="__BUILD_ID__">
  <title>MetaPQP · 智果园检查总览</title>
  <style>
    :root {
      color-scheme: light;
      --ink: #142033;
      --muted: #647087;
      --line: #dce3eb;
      --paper: #f5f7fa;
      --panel: #ffffff;
      --navy: #172d4d;
      --cyan: #1d8a99;
      --p0: #b42318;
      --p1: #d45b14;
      --p2: #9a6a05;
      --good: #17805c;
      --shadow: 0 14px 40px rgba(23, 45, 77, .08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--paper);
      color: var(--ink);
      font-family: "PingFang SC", "Microsoft YaHei", system-ui, sans-serif;
      font-size: 14px;
    }
    button, input, select { font: inherit; }
    a { color: inherit; }
    a:focus-visible, button:focus-visible, input:focus-visible, select:focus-visible {
      outline: 3px solid rgba(29, 138, 153, .34);
      outline-offset: 2px;
    }
    .masthead {
      color: #fff;
      background:
        linear-gradient(112deg, rgba(29, 138, 153, .22), transparent 44%),
        var(--navy);
      padding: 38px clamp(20px, 5vw, 76px) 34px;
      border-bottom: 5px solid var(--cyan);
    }
    .masthead-inner, main { max-width: 1520px; margin: 0 auto; }
    .eyebrow {
      margin: 0 0 10px;
      color: #9edce2;
      font: 700 12px/1.3 ui-monospace, SFMono-Regular, Menlo, monospace;
      letter-spacing: .13em;
      text-transform: uppercase;
    }
    h1 { margin: 0; font-size: clamp(29px, 4vw, 50px); line-height: 1.06; letter-spacing: -.04em; }
    .subtitle { max-width: 760px; margin: 14px 0 0; color: #cbd7e7; font-size: 15px; line-height: 1.7; }
    .coverage-rail { display: grid; grid-template-columns: repeat(3, 1fr); gap: 2px; margin-top: 28px; max-width: 780px; }
    .rail-segment { background: rgba(255,255,255,.1); padding: 12px 15px; border-top: 2px solid #8dd3da; }
    .rail-segment b { display: block; font-size: 16px; }
    .rail-segment span { color: #b9c8da; font-size: 12px; }
    main { padding: 26px clamp(16px, 4vw, 62px) 64px; }
    .metrics { display: grid; grid-template-columns: repeat(5, minmax(130px, 1fr)); gap: 12px; }
    .metric { background: var(--panel); padding: 18px; border: 1px solid var(--line); box-shadow: var(--shadow); }
    .metric-label { color: var(--muted); font-size: 12px; }
    .metric-value { display: block; margin-top: 9px; font: 750 30px/1 ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing: -.05em; }
    .metric-note { margin-top: 8px; color: var(--muted); font-size: 11px; }
    .risk .metric-value { color: var(--p1); }
    .toolbar {
      display: grid;
      grid-template-columns: minmax(240px, 1fr) repeat(3, minmax(130px, auto));
      gap: 10px;
      margin: 24px 0 12px;
      padding: 12px;
      background: #e9eef4;
      border: 1px solid #d7e0e9;
    }
    .control { width: 100%; min-height: 42px; border: 1px solid #c8d1dd; background: #fff; color: var(--ink); padding: 0 12px; border-radius: 2px; }
    .result-line { display: flex; justify-content: space-between; gap: 16px; margin: 12px 2px; color: var(--muted); font-size: 12px; }
    .table-shell { overflow: auto; background: var(--panel); border: 1px solid var(--line); box-shadow: var(--shadow); }
    table { width: 100%; border-collapse: collapse; min-width: 1020px; }
    th { position: sticky; top: 0; z-index: 1; padding: 12px 14px; color: #e9f0f8; background: var(--navy); text-align: left; font-size: 11px; letter-spacing: .06em; }
    td { padding: 14px; border-bottom: 1px solid var(--line); vertical-align: top; }
    tbody tr:hover { background: #f6fafb; }
    tbody tr:last-child td { border-bottom: 0; }
    .module { display: inline-grid; place-items: center; width: 28px; height: 28px; color: #fff; background: var(--navy); font: 700 13px ui-monospace, monospace; }
    .page-name { display: block; font-weight: 700; margin-bottom: 4px; }
    .page-id { color: var(--muted); font: 11px ui-monospace, SFMono-Regular, Menlo, monospace; }
    .surface { display: inline-block; padding: 3px 7px; border: 1px solid #bdd0d5; color: #155f69; background: #eff9fa; font-size: 11px; text-transform: uppercase; }
    .count { font: 700 13px ui-monospace, SFMono-Regular, Menlo, monospace; }
    .p0 { color: var(--p0); } .p1 { color: var(--p1); } .p2 { color: var(--p2); }
    .report-list { display: flex; flex-wrap: wrap; gap: 7px; min-width: 245px; }
    .report-link { text-decoration: none; padding: 7px 9px; border: 1px solid #cbd5df; background: #fff; font-size: 11px; }
    .report-link:hover { color: #fff; background: var(--cyan); border-color: var(--cyan); }
    .empty { padding: 44px; text-align: center; color: var(--muted); }
    .distribution { margin-top: 22px; padding: 20px; background: var(--panel); border: 1px solid var(--line); }
    .distribution h2 { margin: 0 0 16px; font-size: 17px; }
    .bars { display: grid; gap: 10px; }
    .bar-row { display: grid; grid-template-columns: minmax(170px, 260px) 1fr 36px; gap: 12px; align-items: center; }
    .bar-label { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font: 12px ui-monospace, monospace; }
    .bar-track { height: 9px; background: #e7ecf2; }
    .bar-fill { height: 100%; background: var(--cyan); }
    .bar-number { text-align: right; font: 700 12px ui-monospace, monospace; }
    footer { margin-top: 20px; color: var(--muted); font-size: 11px; }
    @media (max-width: 900px) {
      .metrics { grid-template-columns: repeat(2, 1fr); }
      .toolbar { grid-template-columns: 1fr 1fr; }
      .coverage-rail { grid-template-columns: 1fr; }
    }
    @media (max-width: 560px) {
      .metrics, .toolbar { grid-template-columns: 1fr; }
      .masthead { padding-top: 28px; }
    }
    @media (prefers-reduced-motion: no-preference) {
      .report-link { transition: color .15s ease, background .15s ease, border-color .15s ease; }
    }
  </style>
</head>
<body>
  <header class="masthead">
    <div class="masthead-inner">
      <p class="eyebrow">MetaPQP / Audit control desk</p>
      <h1>智果园页面检查总览</h1>
      <p class="subtitle">把 A、B、C 三个模块的覆盖范围、风险分布和每个场景报告放在同一张工作台中。所有数据来自当前 output/web 下的正式检查结果。</p>
      <div class="coverage-rail" id="coverageRail"></div>
    </div>
  </header>

  <main>
    <section class="metrics" id="metrics" aria-label="检查指标"></section>

    <section class="toolbar" aria-label="结果筛选">
      <input class="control" id="search" type="search" placeholder="搜索产品或 page_id" aria-label="搜索产品或页面">
      <select class="control" id="moduleFilter" aria-label="筛选模块">
        <option value="all">全部模块</option><option value="A">模块 A</option><option value="B">模块 B</option><option value="C">模块 C</option>
      </select>
      <select class="control" id="surfaceFilter" aria-label="筛选页面类型">
        <option value="all">全部类型</option><option value="portal">Portal</option><option value="console">Console</option>
      </select>
      <select class="control" id="riskFilter" aria-label="筛选风险">
        <option value="all">全部风险</option><option value="p1">存在 P1</option><option value="clean">无问题</option>
      </select>
    </section>

    <div class="result-line"><span id="resultCount"></span><span>点击场景标签打开对应 HTML 报告</span></div>
    <div class="table-shell">
      <table>
        <thead><tr><th>模块</th><th>产品 / 页面</th><th>类型</th><th>P0</th><th>P1</th><th>P2</th><th>场景报告</th></tr></thead>
        <tbody id="pageRows"></tbody>
      </table>
      <div class="empty" id="empty" hidden>没有符合当前筛选条件的页面。</div>
    </div>

    <section class="distribution">
      <h2>CheckSpec 问题分布</h2>
      <div class="bars" id="checkBars"></div>
    </section>
    <footer>生成时间：__GENERATED_AT__ · 数据源：__REPORT_COUNT__ 份 audit.json · <a href="ABC-audit-summary.md">查看 Markdown 汇总</a></footer>
  </main>

  <script>
    const RUNS = __RUN_DATA__;
    const byPage = new Map();
    for (const run of RUNS) {
      const key = `${run.product}/${run.page_id}`;
      if (!byPage.has(key)) byPage.set(key, { ...run, runs: [], p0: 0, p1: 0, p2: 0, issue_count: 0 });
      const page = byPage.get(key);
      page.runs.push(run);
      page.p0 += run.p0; page.p1 += run.p1; page.p2 += run.p2; page.issue_count += run.issue_count;
    }
    const pages = [...byPage.values()].sort((a, b) => a.module.localeCompare(b.module) || a.product_label.localeCompare(b.product_label, 'zh-CN') || a.page_id.localeCompare(b.page_id));
    const esc = value => String(value).replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
    const sceneLabel = run => `${run.device === 'mobile' ? 'Mobile' : 'Desktop'} · ${run.locale === 'zh-CN' ? '中文' : 'EN'}`;

    function renderMetrics() {
      const uniquePages = pages.length;
      const consoleRuns = RUNS.filter(r => r.surface === 'console');
      const authOk = consoleRuns.filter(r => r.auth_status === 'authenticated').length;
      const values = [
        ['唯一页面', uniquePages, 'A/B/C 去重后'],
        ['场景报告', RUNS.length, '均可直接打开'],
        ['P1', RUNS.reduce((n,r) => n+r.p1, 0), '建议优先处理'],
        ['P2', RUNS.reduce((n,r) => n+r.p2, 0), '一般改进项'],
        ['Console 登录', `${authOk}/${consoleRuns.length}`, '自动登录成功']
      ];
      document.querySelector('#metrics').innerHTML = values.map((v,i) => `<article class="metric ${i===2?'risk':''}"><span class="metric-label">${v[0]}</span><strong class="metric-value">${v[1]}</strong><div class="metric-note">${v[2]}</div></article>`).join('');
      document.querySelector('#coverageRail').innerHTML = ['A','B','C'].map(module => {
        const subset = pages.filter(p => p.module === module);
        return `<div class="rail-segment"><b>模块 ${module} · ${subset.length} 页</b><span>${subset.reduce((n,p)=>n+p.runs.length,0)} 份场景报告</span></div>`;
      }).join('');
    }

    function filteredPages() {
      const query = document.querySelector('#search').value.trim().toLowerCase();
      const module = document.querySelector('#moduleFilter').value;
      const surface = document.querySelector('#surfaceFilter').value;
      const risk = document.querySelector('#riskFilter').value;
      return pages.filter(page => {
        if (query && !`${page.product_label} ${page.product} ${page.page_id}`.toLowerCase().includes(query)) return false;
        if (module !== 'all' && page.module !== module) return false;
        if (surface !== 'all' && page.surface !== surface) return false;
        if (risk === 'p1' && page.p1 === 0) return false;
        if (risk === 'clean' && page.issue_count !== 0) return false;
        return true;
      });
    }

    function renderRows() {
      const filtered = filteredPages();
      document.querySelector('#resultCount').textContent = `显示 ${filtered.length} / ${pages.length} 个页面`;
      document.querySelector('#empty').hidden = filtered.length > 0;
      document.querySelector('#pageRows').innerHTML = filtered.map(page => {
        const links = page.runs.sort((a,b) => a.device.localeCompare(b.device) || a.locale.localeCompare(b.locale)).map(run => `<a class="report-link" href="${esc(run.report)}" title="${esc(run.url)}">${sceneLabel(run)} ↗</a>`).join('');
        return `<tr><td><span class="module">${page.module}</span></td><td><span class="page-name">${esc(page.product_label)}</span><span class="page-id">${esc(page.page_id)}</span></td><td><span class="surface">${esc(page.surface)}</span></td><td class="count p0">${page.p0}</td><td class="count p1">${page.p1}</td><td class="count p2">${page.p2}</td><td><div class="report-list">${links}</div></td></tr>`;
      }).join('');
    }

    function renderBars() {
      const counts = {};
      for (const run of RUNS) for (const [key, value] of Object.entries(run.checks)) counts[key] = (counts[key] || 0) + value;
      const entries = Object.entries(counts).sort((a,b) => b[1]-a[1]);
      const max = Math.max(...entries.map(x => x[1]), 1);
      document.querySelector('#checkBars').innerHTML = entries.map(([label,count]) => `<div class="bar-row"><span class="bar-label" title="${esc(label)}">${esc(label)}</span><div class="bar-track"><div class="bar-fill" style="width:${count/max*100}%"></div></div><span class="bar-number">${count}</span></div>`).join('');
    }

    for (const id of ['search','moduleFilter','surfaceFilter','riskFilter']) document.querySelector(`#${id}`).addEventListener('input', renderRows);
    renderMetrics(); renderRows(); renderBars();

    const currentBuild = document.querySelector('meta[name="dashboard-build"]').content;
    if (location.protocol === 'http:' || location.protocol === 'https:') {
      window.setInterval(async () => {
        try {
          const response = await fetch(`dashboard.html?version=${Date.now()}`, { cache: 'no-store' });
          const text = await response.text();
          const nextBuild = text.match(/name="dashboard-build" content="([^"]+)"/)?.[1];
          if (nextBuild && nextBuild !== currentBuild) location.reload();
        } catch (_) {
          // The local server may be restarting; the next poll will retry.
        }
      }, 5000);
    }
  </script>
</body>
</html>
'''


if __name__ == "__main__":
    raise SystemExit(main())
