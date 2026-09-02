# 从页面 URL 到三类 CheckPlan｜演示提示卡

> 用途：演示时扫一眼关键词，自由讲解。建议时长：3～5 分钟。

## 30 秒总览

- 输入：一个页面 URL
- 先做：识别页面类型，展开设备与语言，真实打开页面采集事实
- 再做：识别 Journey Stage、Page Archetype、Business Features
- 分流：同一个 CheckSpec Registry 按 `scope` 分给 Page / Transition / Journey Builder
- 编译：各自的输入证据 + AuditProfile + CheckSpec Registry → 对应 CheckPlan
- 输出：Selected / Skipped、选择原因、执行批次；Journey 额外生成 CheckInvocation
- 核心原则：**规则选择由配置和确定性逻辑完成，不由大模型临场决定**

## 一句话看懂关系图

```text
Page路径：URL → PageTarget → PageSnapshot → PageContext
Journey路径：URL → PageMapNode → 起点/终点 PageTarget → 多个 PageSnapshot
                                      ＋
          AuditProfile / CheckSpec Registry（含 page / transition / journey）
                                      ↓
             按 scope 分流到三个确定性 CheckPlan Builder
                 ├─ Page CheckPlan
                 ├─ Transition CheckPlan
                 └─ Journey CheckPlan
```

## 按页面区域讲

| 页面区域 | 表达什么 | 演示示例 | 可以怎么讲 |
|---|---|---|---|
| 顶部 URL | 本次审计入口 | `…/agentorchard/tokenplan.html` | 系统拿到 URL 后，不会直接让模型选择规则 |
| Page Surface | 页面所属产品表面 | `portal` | 决定 Portal / Console 的默认设备语言矩阵，并写入 PageTarget |
| 展开运行 | 确定检查哪些设备和语言 | Desktop + zh-CN；Mobile + zh-CN | 官网按 URL 语言检查桌面端和移动端 |
| 浏览器采集 | 获取页面真实事实 | `PageSnapshot → PageContext` | 系统会真实打开页面，不是只看 URL 字符串 |
| 青色模块 | 本次运行的页面上下文 | PageSnapshot、PageContext | Page Builder据此选择单页面规则 |
| 紫色模块 | 版本化配置 | PageMapNode、AuditProfile、CheckSpec Registry、Standards | 配置提供页面身份、规则范围和版本 |
| 橙色模块 | 确定性规则编译 | 三个 Scope 专属 Builder | 每个 Builder只处理自己的规则 |
| 绿色模块 | 最终执行计划 | Page / Transition / Journey CheckPlan | 对应执行器只能按照自己的计划运行 |

## URL 拿到以后做什么

### 1. 解析页面入口与 PageMapNode

- Journey 审计会先通过 PageMapNode URL Pattern 找到稳定的页面节点，并用它校验Journey起点和终点
- 单独的 `page` 命令当前仍主要通过 URL、Page Surface 和页面采集结果工作，PageMapNode不是Page CheckPlanBuilder的直接输入
- PageMapNode提供预期的 `stage`、`surface` 和登录要求；未命中时不阻断基础Page审计
- `console.*` → Console
- 其他域名 → Portal
- 支持显式指定，覆盖自动判断
- Journey页面采集后生成 PageContext，再与 PageMapNode 的预期身份核对
- PageMapNode 不保存 Transition、Journey、Fixture 或 Safety；这些由独立 Registry 管理

### 2. 展开设备与语言

| 页面类型 | 默认设备 | 默认语言 |
|---|---|---|
| Portal 官网 | Desktop + Mobile | URL 所表达的语言 |
| Console 控制台 | Desktop | zh-CN + en-US |

演示 URL 是中文 Portal，因此：

- Desktop + zh-CN
- Mobile + zh-CN
- 两个组合分别生成自己的 Snapshot、Context 和 CheckPlan

### 3. 真实采集页面

- 最终 URL 和 HTTP 状态
- Title、正文、标题结构
- 按钮、链接、表单、图片
- Console Error、Network Error
- 元素位置、尺寸和页面截图
- 移动端额外采集横向溢出、触控尺寸

一句话：**URL 先定位 PageMapNode，页面加载后的 Snapshot 和 PageContext 才是本次运行的事实依据。**

## 构建链路中的输入

| 输入 | 来源 | 示例 | 影响什么 |
|---|---|---|---|
| Page Surface | URL 自动识别或请求覆盖 | `portal` | 决定运行矩阵并写入 PageTarget；当前不直接参与 Builder 条件筛选 |
| Device | 运行矩阵 | `desktop` | 是否启用移动端规则 |
| Locale | URL / 运行矩阵 | `zh-CN` | 是否启用中文文案检查 |
| Journey Stage | 页面 Detector 或人工覆盖 | `awareness` | 是否启用购买、下单、支付等阶段规则 |
| Page Archetype | 页面 Detector 或人工覆盖 | `product_landing` | 是否启用产品落地页规则 |
| Business Features | 页面 Detector + 人工补充 | `pricing`、`purchase_entry` | 是否启用价格、CTA 等规则 |
| AuditProfile | 请求配置 | `mvp` | 决定本次允许使用的候选规则集合 |
| CheckSpec Registry | 版本化 YAML | 28 条 CheckSpec | 提供 scope、适用条件、执行器和版本 |
| Standards | 规范配置 | WCAG、内部规范等 | 在 CheckSpec 加载时校验规范引用 |

## PageContext 怎么得到

当前有三个确定性 Detector：

| Detector | 识别内容 | 示例结果 |
|---|---|---|
| Journey Stage Detector | awareness / purchase / order / payment / renewal / unsubscribe 等（代码仍保留 legacy `usage` 识别） | `awareness` |
| Page Archetype Detector | product_landing / console_page / order_page 等 | `product_landing` |
| Commerce Feature Detector | pricing / purchase_entry / form 等 | `pricing`、`purchase_entry` |

提示：

- 当前是基于 URL、Title、正文和交互元素的确定性识别
- 调用方可以显式覆盖 Stage、Archetype，并补充 Features
- 图中的 Context 是演示快照，不代表一次实时抓取结果

## Builder 怎么选择规则

逐条检查：

1. 是否被 AuditProfile 启用
2. Device 是否匹配
3. Locale 是否匹配
4. Journey Stage 是否匹配
5. Page Archetype 是否匹配
6. `features_any` 是否至少命中一个
7. `features_all` 是否全部满足

结果：

- 满足条件 → `Selected`
- 不满足条件 → `Skipped`
- 每条都保存原因

## 三个 Builder 如何分工

三种 CheckPlan共用同一个 CheckSpec Registry和AuditProfile，但输入证据、适用条件和输出不同：

演示时只看HTML中的“合并架构图”：Page 是主路径，完整展开从页面事实和配置，到 Applicable CheckSpecs、Python Checkers、Model Check Skills、Execution Batches，再到最终 Page CheckPlan；Transition 和 Journey 作为两条紧凑的跨页路径，分别展示自己的证据、Builder 和计划输出。这样先讲最常用的单页检查，再补充跨页检查如何接入同一个规则体系。

| Builder | 当前代码 | 输入 | 选择逻辑 | 输出 |
|---|---|---|---|---|
| Page | `CheckPlanBuilder` | `PageAuditRequest` + `PageContext` | 只处理 `scope=page`，再匹配设备、语言、阶段、页面原型和业务特征 | Page `selected/skipped` + local/model execution batches |
| Transition | `TransitionCheckPlanBuilder` | `transition_id` + AuditProfile | 只处理 `scope=transition`，再匹配 `transition_ids` | Transition `selected/skipped` + `transition-deterministic` batch |
| Journey | `JourneyCheckPlanBuilder` | `JourneyDefinition` + `JourneyEvidenceBundle` | 只处理 `scope=journey`，再匹配 `journey_ids`、`execution_modes`、`comparison`和最少节点数 | Journey `selected/skipped` + `CheckInvocation` + `journey-semantic-consistency` batch |

### 三类计划的运行关系

```text
JourneyAuditRunner
  ├─ 先打开 Journey 起点和终点，采集多个 PageSnapshot
  ├─ 每个页面 → PageAuditPipeline → Page CheckPlan → PageAssessment
  ├─ 每条 Transition Trace → TransitionCheckPlanBuilder → Transition CheckPlan
  ├─ Page results → JourneyEvidenceBuilder → JourneyEvidenceBundle
  └─ JourneyEvidenceBundle → JourneyCheckPlanBuilder → Journey CheckPlan
```

这里不是“一个大Builder生成三份计划”，而是三个Builder分别生成自己的计划；Journey Runner负责把它们串起来。

### Page CheckPlan 示例

### 结果摘要

| 字段 | 示例值 |
|---|---|
| Builder Version | `1.2.0` |
| AuditProfile | `mvp` |
| Model Mode | `grouped` |
| 候选 CheckSpec | 17 条 `scope=page` |
| Selected / Skipped | 根据当前 PageContext 动态决定 |
| Execution Batches | 3 |

### 代表性选择理由

| CheckSpec | 结果 | 原因 |
|---|---|---|
| `page-load` | Selected | 全局规则 |
| `product-value-clarity` | Selected | 页面是 `product_landing` |
| `pricing-transparency` | Selected | 页面具有 `pricing` 特征 |
| `cta-clarity` | Selected | 页面具有 `purchase_entry` 特征 |
| `mobile-horizontal-overflow` | Skipped | 当前运行是 `desktop` |
| `mobile-tap-target-size` | Skipped | 当前运行是 `desktop` |
| `commitment-risk-timing` | Skipped | 当前阶段是 `awareness`，不是 purchase / order / payment |

### Transition CheckPlan 示例

以 `tokenplan-awareness-to-purchase` 为例：

| 字段 | 示例值 |
|---|---|
| Builder Version | `1.0.0` |
| Transition | `tokenplan-awareness-to-purchase` |
| 起点 / 终点 | `tokenplan-awareness` → `tokenplan-purchase` |
| 动作 | 找到名为“立即订阅”的 Link，且 href 包含 `resourcePlanManagement` |
| 安全终点 | `purchase_page_loaded`，不提交交易 |
| 计划输出 | `transition-deterministic` |

当前Transition Builder只会选择匹配该Transition的规则。当前MVP中有3条Transition Scope规则，例如：

- `journey-transition-reachability`：是否到达声明的终点PageMapNode；
- `entry-and-resume-continuity`：跳转后是否仍保持业务入口；
- `transaction-context-continuity`：起点和终点的产品上下文是否连续。

### Journey CheckPlan 示例

以 `tokenplan-awareness-purchase-preview` 为例：

| 字段 | 示例值 |
|---|---|
| Builder Version | `1.0.0` |
| Journey | `tokenplan-awareness-purchase-preview` |
| 运行方式 | `sequential` |
| 页面节点 | `tokenplan-awareness`、`tokenplan-purchase` |
| 证据输入 | `JourneyPageFacts` / `JourneyEvidenceBundle` |
| 计划输出 | 多个 `CheckInvocation` + `journey-semantic-consistency` |

Journey Builder不会按页面逐条重跑Page规则，而是根据每条Journey CheckSpec的`comparison`生成比较实例：

```text
Journey CheckSpec
  → comparison.mode = adjacent / anchor_to_each / all_observed
  → CheckInvocation（subject_node_ids + evidence_facets）
  → Journey semantic model batch
```

例如跨阶段产品身份一致性，会把感知页和购买页的事实放入同一个Invocation，检查两个节点是否仍表达同一产品。

## 选中的规则怎么执行

### CheckSpec 有两种执行方式

| Scope | 当前规则数 | 主要执行方式 | 计划输出 |
|---|---:|---|---|
| `page` | 17 | 7条 Python Checker + 10条 Model Skill | Page selected/skipped + local/model batches |
| `transition` | 3 | Transition Checker（当前均为确定性执行） | `transition-deterministic` |
| `journey` | 8 | Journey Cross-stage Model Skill | `CheckInvocation` + `journey-semantic-consistency` |

因此当前Registry总数为28条，但一次运行不会把28条全部放进同一个计划；每个Builder只处理自己的Scope。

### Page Scope 的 Python Checker 清单

| CheckSpec | Python Checker |
|---|---|
| `page-load` | `page-load-checker` |
| `document-structure` | `document-structure-checker` |
| `runtime-errors` | `runtime-errors-checker` |
| `broken-links` | `broken-links-checker` |
| `image-alt` | `image-alt-checker` |
| `mobile-horizontal-overflow` | `mobile-horizontal-overflow-checker` |
| `mobile-tap-target-size` | `mobile-tap-target-checker` |

### Page Scope 的 Model Check Skill 清单

| CheckSpec | Skill Capability |
|---|---|
| `product-value-clarity` | `product-value` |
| `cta-clarity` | `cta-clarity` |
| `copy-quality` | `copy-quality` |
| `terminology-clarity` | `terminology-clarity` |
| `content-internal-consistency` | `content-internal-consistency` |
| `pricing-transparency` | `pricing-transparency` |
| `commitment-risk-timing` | `commitment-risk-timing` |

### 三类计划的执行批次

| Plan | 批次 | 作用 |
|---|---|---:|---|
| Page | `local`、`content-understanding`、`transaction-decision`、视觉批次（按选中规则） | 当前页面的单页检查 |
| Transition | `transition-deterministic` | 基于TransitionTrace检查终点到达、登录恢复和上下文连续 |
| Journey | `journey-semantic-consistency` | 基于JourneyEvidence和CheckInvocation做跨节点语义一致性检查 |

补充：

- 默认 `grouped`：按语义合并模型调用
- 可切换 `single`：每条模型规则单独调用
- 分批只优化执行，不改变每条 CheckSpec 的独立身份
- 后续执行器严格按照对应Scope的 CheckPlan 运行

## OpenJiuwen 在这里怎么用

### 一句话定位

- **OpenJiuwen = 工作流编排底座**
- **MetaPQP = 页面审计业务逻辑和领域模型**
- OpenJiuwen 负责“按什么顺序运行、状态怎么传、运行如何管理”
- OpenJiuwen 不负责“当前页面应该选择哪些 CheckSpec”

### 当前的两层结构

```text
OpenJiuwen 编排层（当前接入 Page）：Start / End、Connection、IO State、Session、Timeout、Invoke、Logging
                                      ↓ 调度
MetaPQP Page 业务组件：Baseline → Context → Page Plan → Checks → Assessment → Persist

Journey Runner 当前由 MetaPQP 应用层直接编排：

```text
JourneyAuditRunner
  → PageAuditPipeline × N
  → TransitionCheckPlanBuilder
  → JourneyEvidenceBuilder
  → JourneyCheckPlanBuilder
```
```

| MetaPQP 业务节点 | 业务动作 | 主要输出 |
|---|---|---|
| Baseline | 浏览器采集页面 | PageTarget、PageSnapshot |
| Context | 运行 Detectors | PageContext |
| Plan | 调用 CheckPlan Builder | CheckPlan |
| Checks | 按 Execution Batches 执行规则 | CheckRun、ModelCallRecord |
| Assessment | 汇总检查结果 | Findings、PageAssessment |
| Persist | 写入本地结果 | `audit.json`、`checkplan.json`、`report.html` |

说明：

- Start 和 End 是 OpenJiuwen 原生节点
- 中间六个节点是 MetaPQP Page 业务能力，被包装成 `WorkflowComponent`
- 从“调度角度”看，OpenJiuwen 当前参与 Page 流程；Journey Runner 尚未包装成 OpenJiuwen Workflow
- 从“功能实现角度”看，采集、Context、Plan 和检查都由 MetaPQP 实现

### 用到 OpenJiuwen 的哪些能力

| OpenJiuwen 能力 | 当前怎么使用 | 带来的价值 |
|---|---|---|
| `Workflow` / DAG | 创建固定的 Page 工作流，并显式连接各节点 | 流程清晰、顺序固定、便于追踪 |
| `Start` / `End` | 定义统一入口和结果出口 | 输入输出边界明确 |
| `WorkflowComponent` | 用 `PipelineStep` 包装每个异步业务步骤 | 业务组件可以接入工作流，同时不依赖框架类型 |
| Input Schema / IO State | 把上一步状态包装后传给下一节点 | Snapshot、Context、Plan 等数据连续传递 |
| Workflow Session | 每个 Job 创建独立 Session，Session ID 使用 Job ID | 单次运行有独立上下文 |
| Execute Timeout | 通过 Session 环境配置整个 Workflow 超时 | 防止页面采集或模型调用无限挂起 |
| Async Invoke | 使用 `workflow.invoke(...)` 执行完整 Page 审计 | 支持浏览器和模型等异步能力 |
| Logging | 配置日志级别、文件输出和性能日志 | 便于定位工作流运行问题 |

### 代码中的集成方式

- `OpenJiuwenWorkflowRunner` 是外围 Adapter
- `PageAuditPipeline` 保持框架无关
- 每个 Pipeline 方法接收和返回普通 `dict`
- `PipelineStep` 负责把业务方法适配为 `WorkflowComponent`
- `_state_envelope` 从前序节点读取状态并传入下一节点
- `workflow.invoke` 完成后校验并返回 `AuditResult`
- 异常由 Runner 捕获，同时把 Job 标记为失败
- Persist 后只向 End 传最终结果，避免把大页面 DOM 证据重复带入结束节点

### 当前明确没有使用

| 未使用能力 | 原因 / 当前边界 |
|---|---|
| ReAct Agent | 页面审计步骤是固定流程，不需要 Agent 自主规划 |
| JiuwenSwarm | 当前 Page Workflow 和 Journey Runner 都不是多 Agent 协作 |
| Agent 自主选择 CheckSpec | 规则必须可解释、可复现，因此由 CheckPlan Builder 编译 |
| MCP 实际调用 | 当前仅保留可选接口方向，没有接入本次页面审计主流程 |

### 可以怎么向领导解释

- OpenJiuwen 提供的是“流程骨架”和“运行容器”
- MetaPQP 把页面采集、Context、三类 CheckPlan 和检查执行作为独立业务能力接进去
- 当前只有 Page Workflow 接入 OpenJiuwen；Journey Runner 已实现为 MetaPQP 应用层运行器，尚未包装成 OpenJiuwen Workflow
- 未来替换执行框架或扩展 Runtime 时，领域模型和原子检查能力仍可复用
- 当前选择确定性 Workflow，是为了保证质检过程稳定、可审计，而不是追求 Agent 自由度

## 最后强调的三点

1. **按 Scope 分工**：Page、Transition、Journey 各自生成自己的 CheckPlan
2. **动态适配**：页面 Context、Transition ID 和 Journey Evidence 分别决定规则是否适用
3. **全程可解释**：每条规则都有 Selected / Skipped 原因，Journey 还记录 CheckInvocation
4. **可治理、可复现**：规则来自版本化配置，不由模型自由挑选

## 领导可能会问

| 问题 | 简短回答 |
|---|---|
| 是不是大模型决定检查什么？ | 不是。三个Builder使用确定性逻辑按Scope选择规则；模型只执行已经选中的语义检查 |
| 三个Builder是一个Builder吗？ | 不是。Page、Transition、Journey各自有独立Builder，共用Registry和AuditProfile |
| 只靠 URL 判断页面吗？ | 不是。URL先匹配PageMapNode，核心判断来自浏览器采集的真实PageSnapshot和PageContext |
| 为什么不同设备结果不同？ | Mobile 会额外启用横向溢出、触控目标尺寸等设备规则 |
| 为什么中英文结果不同？ | 部分规则有 Locale 条件，例如中文文案检查只适用于 zh-CN |
| 能解释为什么没检查某项吗？ | 可以。Skipped 中保存具体原因 |
| 结果保存在哪里？ | `checkplan.json`，同时保存在 `audit.json.check_plan` |
| Journey如何检查跨页面一致性？ | Journey Builder根据JourneyEvidence和comparison生成CheckInvocation，再由Journey语义模型批次执行 |
| Standards 是否直接决定规则选择？ | 当前不是。它在 CheckSpec 加载时校验规范引用，并随检查结果提供规范依据 |
