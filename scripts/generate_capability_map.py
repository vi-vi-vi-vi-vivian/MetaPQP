import argparse
import html
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml


DEFAULT_REPOSITORY = Path(__file__).resolve().parents[1]
CONTENT = {
    'D1': {
        'question': '用户能找到并理解所需信息吗？',
        'current': ['页面标题与当前任务是否一致；错别字、语病和术语歧义。', '操作入口是否说明动作和结果；旅程前后的产品身份与术语是否一致。'],
        'boundary': ['基于已采集文字与页面事实判断，不等于真实用户已经看懂。', '不能据现有规则宣称已覆盖全站信息架构、导航或站内搜索。'],
        'next': ['待建设：查找路径、内容时效与事实校验。', '需人工：目标用户是否理解；用词是否符合业务语境。'],
    },
    'D2': {
        'question': '用户能判断是否适合自己、该选哪种吗？',
        'current': ['产品价值和适用对象是否清楚；跨阶段的选型引导是否衔接。', '参考对比：成果是否可见、核心价值能否体验、方案是否易区分、决策信息是否靠近选择点。'],
        'boundary': ['本维度 6 项中有 4 项为参考对比，必须提供可比的参考对象。', '参考差距是改进机会，不直接算主体产品缺陷；“有试用入口”不等于已验证实际试用效果。'],
        'next': ['待建设：复杂选型决策树与典型场景推荐。', '需人工：产品是否真正适合用户；方案是否有吸引力。'],
    },
    'D3': {
        'question': '用户能核对购买内容、费用和承诺吗？',
        'current': ['页面及旅程前后的价格、规格、权益、承诺是否一致。', '计价因子齐全时独立复算配置费用；检查续费、退订风险披露。另有 1 项承诺边界参考对比。'],
        'boundary': ['缺单价、单位、时长或折扣时不能判定金额正确。', '检查信息是否披露，不代表计费后台、实际扣款、退款和权益到账已验证；不是法律合规认证。'],
        'next': ['待建设：优惠叠加、复杂计价规则与收费事件依赖。', '需人工：资费和承诺是否合理；政策是否真的可执行。'],
    },
    'D4': {
        'question': '用户能完成操作，并在出错后继续吗？',
        'current': ['已配置动作的目标可达性、登录恢复、反馈和错误指引。', '操作前后上下文、配置与摘要、默认选择及资源状态是否连续；另有 1 项选择连续性参考对比。'],
        'boundary': ['依赖已配置且有证据的动作与旅程，不自动覆盖任意复杂交互。', '轻量支付、弹窗与跨域 iframe 不能因一次人工走查就记为自动覆盖；不以真实下单付款作为默认检查动作。'],
        'next': ['待建设：表单异常、搜索上传、异步任务、刷新返回及中断恢复；弹窗/iframe 旅程泛化。', '需人工：学习成本、复杂业务规则与高风险操作的授权边界。'],
    },
    'D5': {
        'question': '用户在目标环境下能访问并使用吗？',
        'current': ['主体加载、运行异常影响线索、可见链接和产品图片加载。', '可点击图片是否有可访问名称；移动端触控区域与例外条件核对。'],
        'boundary': ['网络/脚本日志不等于核心功能故障；匿名访问失败不必然等于链接损坏。', '并非所有缺少图片说明都算缺陷，也不代表完整无障碍、性能或浏览器兼容评估。'],
        'next': ['待建设：性能弱网、跨浏览器、键盘焦点、对比度及语义无障碍。', '需人工：真实环境中等待、卡顿与辅助操作是否可接受。'],
    },
    'D6': {
        'question': '关键信息是否清楚可见、可读？',
        'current': ['移动端横向溢出；响应式布局；文字裁切及内容遮挡。', '其中 1 项由规则检查，3 项通过视觉模型检查。'],
        'boundary': ['视觉检查已有入口，但依赖截图、采集范围和可用的视觉服务。', '模型失败必须标为未执行；静态截图不能证明动态状态、桌面视觉或全设备一致性已覆盖。'],
        'next': ['待建设：桌面端视觉、动态弹层、跨设备一致性与视觉回归。', '需人工：视觉层级、品牌表达和整体审美。'],
    },
}


def load_inventory(repository):
    schema_path = repository / 'scripts/dashboard_pipeline/assets/quality_dimensions.json'
    schema = json.loads(schema_path.read_text())
    rules = {item['id']: item for item in schema['rules']}
    if len(rules) != len(schema['rules']):
        raise ValueError('六维映射存在重复检查 ID')
    dimensions = schema['dimensions']
    if {item['id'] for item in dimensions} != set(CONTENT) or len(dimensions) != 6:
        raise ValueError('六维定义缺失或重复')
    specs = {}
    for path in sorted((repository / 'config/check_specs').glob('*.yaml')):
        spec = yaml.safe_load(path.read_text())
        if spec['id'] in specs:
            raise ValueError('检查配置存在重复 ID')
        specs[spec['id']] = spec
    if set(rules) != set(specs):
        raise ValueError(f'检查配置与六维映射不一致：{sorted(set(rules) ^ set(specs))}')
    capabilities = {}
    for path in sorted((repository / 'config/capabilities').rglob('*.yaml')):
        capability = yaml.safe_load(path.read_text())
        capabilities[capability['id']] = capability
    inventory = []
    for rule in schema['rules']:
        spec = specs[rule['id']]
        if rule['dimension'] not in CONTENT:
            raise ValueError(f'无效的主维度：{rule["id"]}')
        executor = spec['executor']
        capability = capabilities.get(executor['capability_id'])
        if capability is None:
            raise ValueError(f'执行能力未注册：{rule["id"]}')
        if spec.get('scope', 'page') == 'comparison':
            mode = 'reference'
        elif executor['type'] == 'deterministic':
            mode = 'code'
        elif capability.get('modality') == 'vision':
            mode = 'vision'
        else:
            mode = 'semantic'
        inventory.append({**rule, 'mode': mode, 'scope': spec.get('scope', 'page'),
                          'executor': executor['capability_id'], 'version': str(spec['version'])})
    return dimensions, inventory


def render(repository, date):
    dimensions, inventory = load_inventory(repository)
    counts = Counter(item['mode'] for item in inventory)
    scopes = Counter(item['scope'] for item in inventory)
    escape = html.escape
    mode_labels = {'code': '规则执行', 'semantic': '语义模型 · 条件式', 'vision': '视觉模型 · 条件式', 'reference': '参考对比 · 改进机会'}
    scope_labels = {'page': '页面', 'transition': '交互', 'journey': '旅程', 'comparison': '参考对比'}
    rows = []
    appendix = []
    navigation = []
    summary = []
    for dimension in dimensions:
        key, name = dimension['id'], dimension['name']
        items = [item for item in inventory if item['dimension'] == key]
        reference_count = sum(item['mode'] == 'reference' for item in items)
        modes = Counter(item['mode'] for item in items)
        badge = f'{len(items)} 项映射' + (f' · 含 {reference_count} 项参考对比' if reference_count else '')
        navigation.append(f'<a href="#{key}"><code>{key}</code><span>{escape(name)}</span><b>{len(items)}</b></a>')
        cells = ''.join('<td><ul>' + ''.join('<li>' + escape(value) + '</li>' for value in CONTENT[key][column]) + '</ul></td>'
                        for column in ('current', 'boundary', 'next'))
        rows.append(f'<tr id="{key}"><th scope="row"><code>{key}</code><h3>{escape(name)}</h3><p>{escape(CONTENT[key]["question"])}</p><small>{badge}</small></th>{cells}</tr>')
        details = ''.join(f'<li data-rule="{escape(item["id"])}"><div><strong>{escape(item["title"])}</strong><span class="mode {item["mode"]}">{mode_labels[item["mode"]]}</span></div>'
                          f'<p>{scope_labels[item["scope"]]} · <a href="../config/check_specs/{escape(item["id"])}.yaml"><code>{escape(item["id"])}</code></a> · v{escape(item["version"])}</p></li>'
                          for item in items)
        appendix.append(f'<details class="rule-group"><summary>{key} {escape(name)}<span>{badge}</span></summary><ol>{details}</ol></details>')
        summary.append({'id': key, 'name': name, 'rules': len(items), 'modes': dict(modes)})
    template = Path(__file__).with_name('capability_map_template.html').read_text()
    replacements = {'__DATE__': date, '__RULE_COUNT__': str(len(inventory)), '__NAV__': ''.join(navigation),
                    '__MATRIX__': ''.join(rows), '__APPENDIX__': ''.join(appendix),
                    '__CODE__': str(counts['code']), '__SEMANTIC__': str(counts['semantic']),
                    '__VISION__': str(counts['vision']), '__REFERENCE__': str(counts['reference']),
                    '__SCOPES__': ' · '.join(f'{scope_labels[key]} {scopes[key]} 项' for key in ('page', 'transition', 'journey', 'comparison'))}
    for key, value in replacements.items():
        template = template.replace(key, value)
    return template, {'date': date, 'rules': len(inventory), 'dimensions': summary, 'modes': dict(counts), 'scopes': dict(scopes)}


def main():
    parser = argparse.ArgumentParser(description='Refresh the six-dimension capability map from registered rules.')
    parser.add_argument('--repository', type=Path, default=DEFAULT_REPOSITORY)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--date', default=datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat())
    args = parser.parse_args()
    destination = args.output or args.repository / 'docs/capability-map.html'
    document, summary = render(args.repository, args.date)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(document)
    print(json.dumps({'output': str(destination), **summary}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
