# MetaPQP

页面优先的官网体验检查 MVP。核心架构采用模块化单体和稳定 Application Ports；OpenJiuwen、Playwright、模型 Provider、SQLite、Dashboard 与可选 MCP 均作为外围适配器接入。

## 在新电脑首次启动

无需复制另一台电脑上的 `.venv`。虚拟环境包含本机的 Python 解释器和依赖，应在每台电脑重新创建；`.env`、`config/auth/account.local.yaml`、`data/` 与 `output/` 也都是本机文件，不应提交到 Git。

前置条件：已安装 Git、Python 3.13+ 和 Node.js/npm（Playwright CLI 相关工具需要 `npx`；项目检查本身由 Python Playwright 驱动）。在新电脑执行：

```bash
git clone <仓库地址>
cd MetaPQP

python3 -m venv .venv
source .venv/bin/activate
python --version
pip install -e '.[dev]'
playwright install chromium

cp .env.example .env
cp config/auth/account.example.yaml config/auth/account.local.yaml
chmod 600 config/auth/account.local.yaml
```

然后按需填写 `.env` 中的文本/视觉模型 Provider、URL、API Key 与模型名；需要检查登录后的 Console 或 Journey 时，再填写 `config/auth/account.local.yaml` 的华为云账号。仅检查匿名门户页面时，可保持账号配置禁用，并在命令中使用 `--auth off`。

完成配置后，先校验所有 YAML manifest、Skill、页面地图、Journey 和执行器引用：

```bash
meta-pqp validate-config
```

## 本地环境

```bash
source .venv/bin/activate
python --version
pip install -e '.[dev]'
playwright install chromium
```

真实 API Key 通过未纳入 Git 的 `.env` 注入；登录凭据保存在未纳入 Git 的本地账号配置中。凭据不能写入源码、可提交 YAML、SKILL.md、日志或报告。

模型相关检查是可选的。`default-text` 和 `default-vision` 分别配置文本与多模态能力；默认实现仍是 OpenRouter 文本模型和 Gemini `gemini-3.7-flash`，也可以仅通过环境变量切换到 OpenAI-compatible 内网接口。Journey 语义检查使用 `default-text`，只有携带截图的视觉规则使用 `default-vision`。未配置对应 API Key 时，确定性检查和另一个模型批次照常执行，相关 CheckSpec 会标记为“未执行”，不会伪造通过或计入页面问题。

```dotenv
OPENROUTER_API_KEY=...
TEXT_MODEL_PROVIDER=openrouter
VISION_MODEL_PROVIDER=gemini
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-3.7-flash
GEMINI_FALLBACK_PROBE_TIMEOUT_SECONDS=45
VISUAL_AUDIT_ENABLED=true
VISUAL_MODEL_MAX_IMAGES_PER_CALL=5
```

模型 HTTP 请求按以下优先级选择代理：`MODEL_HTTPS_PROXY` 显式配置 → `HTTP_PROXY/HTTPS_PROXY` 环境变量或 macOS 系统代理 → 直连。macOS 上使用系统代理软件时通常无需手工导出环境变量；沙箱或 CI 无法读取宿主系统代理时，可以显式设置：

```dotenv
MODEL_HTTPS_PROXY=http://127.0.0.1:15236
MODEL_RETRY_ATTEMPTS=2
MODEL_RETRY_BACKOFF_SECONDS=3
```

Gemini 生产调用复用旧工程验证过的 `requests + generateContent + 系统代理` 路径，不依赖 Gemini SDK 的传输实现。内联图片超过配置阈值时会转为 JPEG 并限制总像素。`GEMINI_FALLBACK_MODELS` 可用逗号分隔配置后备模型；默认在 `gemini-3.7-flash` 暂时高负载时回退到已验证的 `gemini-3.6-flash`。存在后备模型时，首选模型使用 `GEMINI_FALLBACK_PROBE_TIMEOUT_SECONDS` 探测窗口，遇到可重试的 HTTP 或传输错误后立即切换，不在失效首选模型上重复等待；后备模型仍使用完整的 `GEMINI_TIMEOUT_SECONDS`。Provider 连接中断、超时或未配置会生成 `error` CheckRun，HTML 显示为“未执行”，只降低覆盖状态，不进入页面问题；底层异常写入运行日志，不进入最终报告。模型已经返回疑似页面发现但本地证据不足时，才使用 `needs_verification`。

模型调用使用提供商无关的 Text/Image Content Blocks。浏览器快照、模型证据投影和 Journey facts 不使用元素数、字符数或事实数的静默前缀截断。视觉截图连续覆盖整页，并根据 `VISUAL_MODEL_MAX_IMAGES_PER_CALL` 分批调用和归并；该配置限制单次请求，不限制整次检查范围。`default-text` 与 `default-vision` 是执行计划中的模型 Profile；替换 Provider 只需调整环境变量或新增 Adapter，不需要修改 CheckSpec 或 Skill。

## 运行单页面检查

```bash
source .venv/bin/activate
meta-pqp page \
  --url 'https://example.com' \
  --product example \
  --page-id awareness
```

未指定设备和语言时，系统先根据 URL 识别 `page_surface`，再展开默认检查矩阵：

- `portal`：门户展示语言由 URL 决定，中文站 URL 默认检查 Desktop 与 Mobile；`/intl/en-us/` 国际站 URL 同样只检查 Desktop 与 Mobile，不自动构造不存在的另一语言页面。
- `console`：默认只检查 Desktop，并通过 URL `locale` 参数分别检查中文和英文；不默认执行 Mobile 检查。

`--device`、`--locale` 和 `--page-surface portal|console` 可覆盖默认策略；显式指定 `--device mobile` 时仍可对 Console 执行移动端专项检查：

```bash
meta-pqp page \
  --url 'https://example.com' \
  --product example \
  --page-id awareness \
  --device desktop \
  --locale zh-CN
```

`--page-id` 是同一产品内稳定、可读的页面名称，例如 `awareness`、`purchase`、`order-confirmation`；不要使用 URL Hash 或时间戳充当页面名。`--stage` 和 `--archetype` 用于人工覆盖自动判别结果。`page_surface` 描述页面承载面，当前仅使用 `portal` 和 `console`，不要与内容结构维度 `page_archetype` 混用。

Mobile 模式使用 390×844 CSS px、3x DPR、Touch 与 iPhone User-Agent 独立采集，并增加横向溢出和最低触控目标尺寸两条确定性 CheckSpec。`portal + mobile` 还会生成首屏、全页概览及连续覆盖整页的切片，执行遮挡、文本裁切和响应式破版三条视觉 CheckSpec；单次模型请求的图片数受传输批次控制，但整次检查不限制切片总数。Console 不进入该视觉批次：

```bash
meta-pqp page \
  --url 'https://example.com' \
  --product example \
  --device mobile \
  --locale zh-CN \
  --auth off
```

## 运行有监督 Journey

当前提供一条显式选择、单 Transition 的有监督 Journey：TokenPlan 感知页点击“立即订阅”，自动复用华为云登录态，到达 Console 购买入口后立即停止。运行时已经支持在同一个 Browser Context 中依次执行多条已登记 Transition；是否允许多步由具名 Journey 和 SafetyProfile 的最大深度共同控制。它不会创建订单、支付或执行其他交易提交。

```bash
meta-pqp audit \
  --scope journey \
  --journey tokenplan-awareness-purchase-preview \
  --url 'https://agentorchard.huaweicloud.com/tokenplan.html' \
  --product tokenplan \
  --locale zh-CN \
  --auth required
```

## 运行参考产品对比

Comparison 以稳定的通用 CheckSpec 评估动态参考页面，不对产品做优劣排名；只有参考做法、当前缺口和可迁移用户收益都能由页面证据证明时，才报告“可借鉴改进机会”。结果写入 `output/comparisons/{benchmark-profile}/{job-id}/report.html`，是单文件报告：左侧目录跳转检查项，右侧展示问题、两侧页面截图和证据；未发现机会的检查项显示“通过”。

```bash
meta-pqp compare \
  --subject-url 'https://www.huaweicloud.com/product/agentarts/officeace.html' \
  --subject-product '华为云 OfficeAce' \
  --reference-url 'https://www.workbuddy.cn/' \
  --reference-product 'WorkBuddy' \
  --device desktop \
  --locale zh-CN
```

当前页和参考页始终由命令参数传入；可重复 `--reference-url` 以添加多个参考页面。`config/comparison_profiles/*.yaml` 只定义可复用的检查维度，六条首期规则放在 `config/check_specs/reference-*.yaml`，因此替换参考产品或新增目标产品不需要复制或改写 CheckSpec。

默认使用 Playwright 安装的隔离 Chromium，headed 模式便于用户观察并随时终止；自动化或沙箱验证可增加 `--headless`。运行时不会回退或启动 `/Applications/Google Chrome.app`，因此隔离 Chromium 在受限沙箱中启动失败时会直接结束并报告浏览器不可用，不会触发 macOS 的 “Google Chrome quit unexpectedly” 弹窗。Journey 使用同一个 Browser Context 完成起点采集、白名单动作和终点采集，然后复用现有 Page Pipeline 检查两个快照。

结果写入 `output/journeys/{journey-id}/{job-id}/`，其中 `report.html` 汇总安全停止、ActionRecord、Transition 检查和 Journey 跨阶段详细检查。Journey 报告是单文件交付件：跨阶段截图会内嵌为 data URI，起点与终点的 Page 报告及其本地图片也会内嵌，并通过“打开内嵌页面报告”在弹窗中查看。因此只复制 `report.html` 到另一台电脑，截图和页面级报告仍可正常显示；`audit.json` 仍保持外部路径，供程序处理使用。桌面报告使用固定左侧目录，可跳转到总览、页面、路径、具体问题和各类检查；窄屏下目录自动变为顶部横向导航。跨阶段规则确认发现问题时，报告会为所有参与比较的页面生成对照截图：实际存在的问题证据使用红框编号；描述“缺失”的页面只展示对应区域，不绘制会误导为问题元素的红框；无法定位到单一 DOM 元素时保留页面上下文并明确标注。通过、不适用、待确认和未执行的规则不生成截图。当前启用 9 条产品通用的跨阶段 CheckSpec，覆盖产品身份、商业条件、可选内容与权益、决策引导、操作预期、术语、选择状态、生命周期状态以及持续承诺与退出规则。规则不绑定固定阶段；CheckPlan 会按 `adjacent`、`anchor_to_each` 或 `all_observed` 生成具体页面比较实例。

### 自动登录

复制单账号配置，并填写当前账号凭据：

```bash
cp config/auth/account.example.yaml config/auth/account.local.yaml
chmod 600 config/auth/account.local.yaml
```

```yaml
version: "1"
account:
  id: default
  account_type: huawei_cloud_account
  provider: huaweicloud
  enabled: true
  site: cn
  username: your-account
  password: your-password
```

当前执行逻辑只读取这一个 `account`。`id` 和 `account_type` 是为后续多账号及场景选号预留的稳定字段，目前不会进行账号路由。

页面检查默认使用 `--auth auto`：如果目标属于 `huaweicloud.com`，会先验证缓存登录态，失效后尝试密码登录；失败时降级为匿名检查，并把原因写入 `PageSnapshot.authentication`。

```bash
meta-pqp page --url 'https://www.huaweicloud.com/product/modelarts.html' --auth auto
```

需要确保登录成功才允许继续时，使用：

```bash
meta-pqp page --url 'https://console.huaweicloud.com/console/' --auth required
```

有头登录命令仅用于本地诊断，不属于无人值守检查的正常路径：

```bash
meta-pqp auth login --site cn --headed --force
```

正式检查使用 `--auth required`，按“有效缓存登录态 → 本地账号密码自动登录”的顺序执行。自动登录遇到 CAPTCHA、短信、MFA 或风险校验时必须失败关闭并给出 `challenge_required`，不能等待人工接管，也不能绕过安全验证；用于自动化的测试账号需要配置为允许无人值守密码登录。

华为云门户展示语言由 URL 控制：中文站与 `/intl/en-us/` 国际站被视为不同目标 URL，不通过浏览器 Locale 猜测或切换。华为云 Console 的界面语言受 URL 参数和账号状态影响；目标为 `console.huaweicloud.com` 时，Target Resolver 会把 `--locale zh-CN|en-US` 显式规范化为 URL 的 `locale=zh-cn|en-us`，保证采集语言可重复。

登录成功后，storage state 缓存在 `data/auth/{account.id}.json`，文件权限设为当前用户可读写；报告只记录 `account_id`、`account_type` 和认证状态，不包含 Cookie、用户名或密码。`--auth off` 可明确禁用登录。

每次运行输出到：

```text
output/{source}/{product}/{page-id}/{device}/{locale}/{job-id}/
├── artifacts/          # DOM、正文、交互元素、Console、Network
├── screenshots/        # 全页、首屏、视觉概览与有限切片
├── audit.json          # 紧凑 Page-first 合同；聚合对象通过 ID 引用
├── checkplan.json      # 本次规则选择与执行批次
└── report.html         # 页面维度报告
```

例如 Token Plan 感知页和购买页分别写入：

```text
output/web/tokenplan/awareness/desktop/zh-CN/{job-id}/
output/web/tokenplan/purchase/desktop/zh-CN/{job-id}/
```

任务状态记录在 `data/app.db`。OpenJiuwen Workflow 负责执行编排，领域模型和各原子能力不依赖 OpenJiuwen，后续迁移 Runtime 或服务化时可以复用。

已有多页面检查结果时，可生成静态汇总 Dashboard：

```bash
.venv/bin/python scripts/generate_audit_dashboard.py
```

默认扫描 `output/web/**/audit.json` 并生成 `output/dashboard.html`。Dashboard 汇总页面数、场景数和问题等级，支持按模块、页面类型和风险筛选；每个场景可直接打开对应的 `report.html`。分组优先读取运行元数据，未提供时显示“—”；可通过 `--title`、`--subtitle`、`--input` 和 `--output` 自定义展示与目录。

需要固定的浏览器地址时，启动本地 Dashboard 服务：

```bash
.venv/bin/python scripts/serve_audit_dashboard.py
```

服务启动时会刷新数据，并持续监听 `output/web/**/audit.json`；发现新增或修改的检查结果后自动重建 Dashboard，已打开的浏览器页面也会在数秒内自动刷新。之后访问 <http://127.0.0.1:8765/dashboard.html>。服务保持运行期间，该地址始终可用；按 `Ctrl+C` 停止。

## 原子能力与动态组装

- `config/check_specs/*.yaml`：一条可独立选择、执行和评审的 CheckSpec；
- `config/capabilities/**/*.yaml`：Capability manifest；将 CheckSpec 的 `capability_id` 接到 Python checker 或 Skill，并声明适用范围、证据契约与文本/视觉模态；
- `config/standards/*.yaml`：规范来源与条款目录；CheckSpec 通过 `standard_refs` 建立多对多映射；
- `config/audit_profiles/*.yaml`：定义某次审计允许启用的 CheckSpec 集合；
- `capabilities/context_detectors/`：可插拔页面场景判别器；
- `src/portal_audit/capabilities/checkers/`：确定性 Python checker 实现；
- `skills/*/SKILL.md`：Text / Visual Skill 的提示词、输出契约与评估样例；
- `config/journey_executors/*.yaml`：Journey 执行模式的 manifest；当前为受监督的 `sequential`，可独立扩展；
- `CheckPlanBuilder`：根据设备、旅程阶段、页面类型和特征计算 selected/skipped 及理由。

当前规范治理、映射关系和新增规则时需要修改的层次，见 [docs/standards-governance.md](docs/standards-governance.md)。

首批 Skill 的人工评审页位于 `docs/reviews/skill-evals.html`。这些样例用于校准边界，目前不宣称是 Golden Set。

## 验证

```bash
ruff check src tests
pytest -q
pip check
.venv/bin/python -m portal_audit.interfaces.cli validate-config
```

## MCP 边界

- `adapters/mcp/client.py`：未来消费外部 MCP Tools；
- `interfaces/mcp/server.py`：未来把审查用例暴露为 MCP Tools；
- `application/ports/mcp.py`：稳定协议，核心模块不依赖 MCP SDK。

MCP 默认关闭，不影响本地 MVP 运行。
