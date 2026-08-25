# MetaPQP

页面优先的官网体验检查 MVP。核心架构采用模块化单体和稳定 Application Ports；OpenJiuwen、Playwright、OpenRouter、SQLite、Dashboard 与可选 MCP 均作为外围适配器接入。

## 本地环境

```bash
source .venv/bin/activate
python --version
pip install -e '.[dev]'
playwright install chromium
```

真实 API Key 通过未纳入 Git 的 `.env` 注入；登录凭据保存在未纳入 Git 的本地账号配置中。凭据不能写入源码、可提交 YAML、SKILL.md、日志或报告。

模型相关检查是可选的。未配置 `OPENROUTER_API_KEY` 时，确定性检查照常执行，依赖模型的 CheckSpec 会明确标记为无法验证，不会伪造结果。

## 运行单页面检查

```bash
source .venv/bin/activate
meta-pqp page \
  --url 'https://example.com' \
  --product example \
  --page-id awareness
```

未指定设备和语言时，单个 URL 默认展开为四次独立检查：Desktop 中文、Desktop 英文、Mobile 中文、Mobile 英文。每种组合都产生独立 Snapshot、CheckPlan 和报告。

`--device` 和 `--locale` 是矩阵过滤条件：只指定设备会检查该设备的中英文，只指定语言会检查该语言的 Desktop/Mobile，两个都指定时只检查一个组合：

```bash
meta-pqp page \
  --url 'https://example.com' \
  --product example \
  --page-id awareness \
  --device desktop \
  --locale zh-CN
```

`--page-id` 是同一产品内稳定、可读的页面名称，例如 `awareness`、`purchase`、`order-confirmation`；不要使用 URL Hash 或时间戳充当页面名。`--stage` 和 `--archetype` 用于人工覆盖自动判别结果。

Mobile 模式使用 390×844 CSS px、3x DPR、Touch 与 iPhone User-Agent 独立采集，并在通用 12 条规则之外增加横向溢出和最低触控目标尺寸两条确定性 CheckSpec：

```bash
meta-pqp page \
  --url 'https://example.com' \
  --product example \
  --device mobile \
  --locale zh-CN \
  --auth off
```

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

华为云 Console 的界面语言不仅取决于浏览器 Locale，也受 URL 参数和账号状态影响。目标为 `console.huaweicloud.com` 时，Target Resolver 会把 `--locale zh-CN|en-US` 显式规范化为 URL 的 `locale=zh-cn|en-us`，保证采集语言可重复。

登录成功后，storage state 缓存在 `data/auth/{account.id}.json`，文件权限设为当前用户可读写；报告只记录 `account_id`、`account_type` 和认证状态，不包含 Cookie、用户名或密码。`--auth off` 可明确禁用登录。

每次运行输出到：

```text
output/{source}/{product}/{page-id}/{device}/{locale}/{job-id}/
├── artifacts/          # DOM、正文、交互元素、Console、Network
├── screenshots/        # 全页截图
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

## 原子能力与动态组装

- `config/check_specs/*.yaml`：一条可独立选择、执行和评审的 CheckSpec；
- `config/standards/*.yaml`：规范来源与条款目录；CheckSpec 通过 `standard_refs` 建立多对多映射；
- `config/audit_profiles/*.yaml`：定义某次审计允许启用的 CheckSpec 集合；
- `capabilities/context_detectors/`：可插拔页面场景判别器；
- `capabilities/checkers/`：确定性工具型检查能力；
- `skills/*/SKILL.md`：需要语义判断的模型型原子能力；
- `CheckPlanBuilder`：根据设备、旅程阶段、页面类型和特征计算 selected/skipped 及理由。

当前规范治理、映射关系和新增规则时需要修改的层次，见 [docs/standards-governance.md](docs/standards-governance.md)。

首批 Skill 的人工评审页位于 `docs/reviews/skill-evals.html`。这些样例用于校准边界，目前不宣称是 Golden Set。

## 验证

```bash
ruff check src tests
pytest -q
pip check
```

## MCP 边界

- `adapters/mcp/client.py`：未来消费外部 MCP Tools；
- `interfaces/mcp/server.py`：未来把审查用例暴露为 MCP Tools；
- `application/ports/mcp.py`：稳定协议，核心模块不依赖 MCP SDK。

MCP 默认关闭，不影响本地 MVP 运行。
