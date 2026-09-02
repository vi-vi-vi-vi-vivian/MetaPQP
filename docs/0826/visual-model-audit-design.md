# 视觉模型页面检查方案｜第一版实现基线

> 状态：Implemented / V1  
> 日期：2026-08-26  
> 第一版已按本轮决策落地；Dashboard 暂不调整。

## 1. 讨论结论

- 已新增独立 `portal-mobile-visual` 多模态批次，不改变原有两个文本批次。
- 首版视觉模型为 Google Gemini `gemini-3.7-flash`；文本模型继续使用 OpenRouter。
- ModelPort 已改为提供商无关的 Text/Image Content Blocks，后续可以替换视觉 Provider。
- 首批规则为遮挡、文本裁切和响应式破版，仅适用于 `portal + mobile`；Console 排除。
- 视觉模型负责发现疑似问题；DOM Bounds、Overflow 和 Computed Style 负责低误报复核。
- 复核不足的结果降级为 `needs_verification`，在单页报告中以“待人工确认”计入问题。
- 视觉批次异常被隔离，不会中断 Local 或 Text Batch。Dashboard 本版保持不变。
- 模型网络层复用旧工程验证过的 macOS 系统代理发现逻辑，并允许显式代理覆盖；OpenRouter 与 Gemini 共用该出口选择。Gemini 生产传输直接使用 `requests` 调用 REST `generateContent`，避免依赖 SDK 内部 HTTP 客户端的代理行为。
- Gemini 内联图片采用 250 KB 压缩阈值、180 万像素上限和可配置 JPEG 质量；调用支持重试和可选模型回退。
- 文本模型批次也已增加失败隔离，Provider 暂时不可用时报告仍可落盘。

## 2. 实现前基线

### 2.1 当前模型调用拓扑

```text
local
  └─ Python Checkers

content-understanding
  └─ 文字 + 结构化 DOM

transaction-decision
  └─ 文字 + 结构化 DOM
```

Grouped 模式下，当前通常发生两次模型调用：

| 批次 | 当前证据 | 主要规则 |
|---|---|---|
| `content-understanding` | 文字、元素语义、PageContext | 文案、术语、一致性、产品价值 |
| `transaction-decision` | 文字、元素语义、PageContext | CTA、价格透明度、承诺风险 |

### 2.2 当前传给模型的页面证据

- 最终 URL
- 页面 Title
- 最多 16,000 字符可见正文
- 最多 500 个结构化页面元素
- 元素文本、Role、Href、Alt、Accessible Name、周边文字
- PageContext
- CheckSpec
- Skill 指令

当前没有：

- Screenshot
- Base64 Image
- `image_url`
- Screenshot Region
- Image Token 统计
- 多模态消息结构

## 3. 为什么需要视觉证据

DOM 描述页面结构和语义，截图描述用户最终看到的绘制结果。两者不完全等价。

### 3.1 截图价值较高的场景

| 场景 | 截图价值 | DOM 复核方式 |
|---|---|---|
| 元素遮挡、重叠 | 高 | Bounds、z-index、交叉区域 |
| 文案、按钮、价格被裁切 | 高 | clientWidth、scrollWidth、overflow |
| 弹窗或固定栏遮挡核心内容 | 高 | 元素位置、Viewport、层叠关系 |
| 响应式视觉错乱 | 高 | Mobile Layout、Bounds |
| 复杂背景下文字不可读 | 高 | Computed Style、颜色与透明度 |
| CTA 视觉显著性 | 高 | Interactive Element、页面区域 |
| 价格与套餐的视觉归属 | 高 | DOM 祖先、卡片结构、元素顺序 |
| 图片、图标、骨架屏渲染异常 | 高 | Network、元素状态、加载时间 |
| Canvas 或图片内文字 | 必要 | DOM 可能无法提供等价文字 |

### 3.2 不应依赖截图的场景

- Broken Link
- Console / Network Error
- Heading 结构
- Image Alt
- 表单 Label
- 精确触控尺寸
- Enabled / Disabled 状态
- URL 和跳转目标
- 纯文字错别字与语病

这些规则应继续使用 DOM、Accessibility Tree、Network 和本地 Checker。

## 4. 建议的模型调用方案

### 4.1 新增按需视觉批次

```text
0. local                     Python Checker
1. content-understanding     Text / DOM Model Batch
2. transaction-decision      Text / DOM Model Batch
3. visual-experience         Multimodal Model Batch（按需）
```

建议：

- 普通文本审计仍保持两次模型调用。
- 只有 CheckPlan 选中视觉 CheckSpec 时才生成第三个批次。
- Grouped 模式下，多个视觉 CheckSpec 合并为一次视觉模型调用。
- Single 模式下，每条视觉 CheckSpec 可以单独调用，用于回归和效果分析。
- 视觉模型失败不影响现有两个文本批次。

### 4.2 为什么不把截图加入现有两次调用

- 同一截图会被处理两次，重复产生图片成本。
- 会改变现有文本规则的回归基线。
- 文本任务和视觉任务混在同一 Prompt 中，边界不清晰。
- 视觉失败可能影响原本稳定的文字检查。
- 无法独立统计视觉模型的准确率、费用和时延。
- 不方便单独选择或替换视觉模型。

## 5. 建议的视觉 CheckSpec

| 建议 ID | 检查内容 | 主要证据 |
|---|---|---|
| `visible-content-occlusion` | 核心内容或 CTA 是否被遮挡 | Screenshot + Bounds |
| `text-clipping-and-truncation` | 文案、价格、按钮文字是否被裁切 | Screenshot + DOM |
| `responsive-visual-integrity` | 移动端是否出现错位、挤压、异常换行 | Screenshot + Mobile Layout |
| `visual-contrast-readability` | 复杂背景下文字是否实际可读 | Screenshot + Computed Style |
| `cta-visual-salience` | 关键 CTA 是否容易被发现 | Screenshot + Interactive Elements |
| `modal-and-banner-obstruction` | Modal、Cookie、固定栏是否阻碍核心操作 | Screenshot + DOM |
| `visual-loading-failure` | 白屏、骨架屏、图片或图标是否渲染异常 | Screenshot + Network |

第一版已经创建前三条 CheckSpec 和对应 Skill；其余规则仍为候选，不在本版范围。

## 6. 视觉证据组织方式

不建议只传一张缩小后的完整长截图。

一次视觉批次建议包含：

1. 全页缩略图：理解整体页面结构。
2. 首屏原始分辨率截图：检查核心信息和 CTA。
3. 页面分段 Tile：保留小字号、价格单位和边缘细节。
4. 与图片对应的精简 DOM：文本、Role、Bounds、Overflow、Computed Style。
5. PageContext 和本批次视觉 CheckSpec。

第一版不额外生成带编号的标注位图；模型通过图片清单、坐标元数据与 DOM `element_ref` 建立关联，避免重复生成图片。

### 6.1 建议的多模态消息形态

```json
{
  "role": "user",
  "content": [
    {
      "type": "text",
      "text": "PageContext、视觉 CheckSpec、精简 DOM 和图片索引"
    },
    {
      "type": "image_url",
      "image_url": {
        "url": "data:image/jpeg;base64,..."
      }
    }
  ]
}
```

该结构仅为接口方向示意，最终需根据所选 Provider 和模型能力确认。

## 7. 视觉发现与 DOM 复核

### 7.1 推荐流程

```text
视觉模型发现疑似问题
        ↓
返回 check_spec_id、原因、截图区域、element_ref
        ↓
本地 Evidence Verifier
        ↓
检查 DOM Bounds、Overflow、Computed Style、交互状态
        ↓
Fail / Needs Verification
```

### 7.2 判定原则

- 视觉证据与 DOM 证据一致：可以形成 `fail`。
- 视觉模型无法关联元素：`needs_verification`。
- 视觉与 DOM 证据冲突：`needs_verification`。
- 只有视觉主观判断、没有稳定规则：保持人工复核。
- DOM 复核优先使用 Python，不建议再增加一次模型调用。

## 8. CheckPlan 与执行批次提案

### 8.1 ExecutionBatch

第一版通过证据 Profile 区分视觉批次，不新增 ExecutionBatchMode：

```json
{
  "batch_id": "portal-mobile-visual",
  "mode": "model_batch",
  "evidence_profile": "visual",
  "model_profile": "default-vision",
  "check_spec_ids": [
    "visible-content-occlusion",
    "text-clipping-and-truncation",
    "responsive-visual-integrity"
  ]
}
```

### 8.2 可能需要扩展的合同

| 合同 | 建议字段 |
|---|---|
| CheckSpec | 复用 `required_evidence`，视觉规则使用 `visual` tag |
| ExecutionBatch | `evidence_profile`、`model_profile` |
| ModelPort | Text / Image Content Blocks |
| ModelCallRecord | Provider、模型、Token、时延和调用明细 |
| CheckRun | Visual Evidence Ref；稳定 DOM 位置继续使用 ElementLocation |
| Artifact | Viewport、Overview、Tile 和页面坐标元数据 |

## 9. `.env` 字段提案

### 9.1 最小必要字段

第一版配置：

```dotenv
GEMINI_API_KEY=
GEMINI_MODEL=gemini-3.7-flash
VISUAL_AUDIT_ENABLED=true
VISUAL_MODEL_PROFILE=default-vision
VISUAL_MODEL_MAX_IMAGES_PER_CALL=5
GEMINI_TIMEOUT_SECONDS=180
MODEL_HTTPS_PROXY=
MODEL_RETRY_ATTEMPTS=2
MODEL_RETRY_BACKOFF_SECONDS=3
GEMINI_FALLBACK_MODELS=
GEMINI_IMAGE_COMPRESS_THRESHOLD_BYTES=250000
GEMINI_IMAGE_MAX_PIXELS=1800000
GEMINI_IMAGE_JPEG_QUALITY=82
```

设计原则：

- 文本与视觉模型使用独立凭据和 Provider。
- `GEMINI_API_KEY` 未配置或 Provider 调用失败时，视觉 CheckSpec 返回执行态 `error`，HTML 显示“未执行”；它只降低覆盖状态，不计入页面问题，也不能伪造通过。只有模型已返回疑似页面发现但本地证据不足时才使用 `needs_verification`。
- CheckPlan 和 Executor 只引用 Profile，不依赖 Gemini 或 OpenRouter 字段。

### 9.2 可选运行参数

如后续需要独立控制，可以考虑：

```dotenv
VISUAL_AUDIT_ENABLED=false
VISUAL_MODEL_MAX_IMAGES_PER_CALL=5
VISUAL_AUDIT_IMAGE_DETAIL=high
VISUAL_AUDIT_TIMEOUT_SECONDS=180
VISUAL_AUDIT_MAX_IMAGE_EDGE=2048
VISUAL_AUDIT_JPEG_QUALITY=85
```

这些参数不建议全部在第一版引入。第一版优先保留：

- `OPENROUTER_VISION_MODEL`
- `VISUAL_AUDIT_ENABLED`
- `VISUAL_MODEL_MAX_IMAGES_PER_CALL`（仅限制单次请求；整页切片总数不设上限）
- `VISUAL_AUDIT_TIMEOUT_SECONDS`

### 9.3 当前状态

- `.env.example` 和 Settings 已增加视觉配置；真实 `.env` 不自动写入。
- 已新增 Provider-neutral Gemini Adapter；其生产调用使用 `requests + generateContent + 系统代理`，未配置视觉能力时不影响其他检查。
- 当前沙箱网络受限，依赖需在可联网环境通过 `pip install -e '.[dev]'` 安装。

## 10. 成本与可靠性控制

### 10.1 成本控制

- 视觉批次按 CheckPlan 选择，不固定调用。
- 同一 Screenshot 在一个视觉批次中只处理一次。
- 长页面使用有限数量 Tile。
- 相同 Snapshot 可缓存视觉结果。
- 在 ModelCallRecord 中独立统计视觉调用成本。
- 页面加载失败或截图无效时不调用视觉模型。

### 10.2 可靠性控制

- 视觉模型输出必须使用严格 JSON Schema。
- 每个 CheckSpec 必须且只能返回一个结果。
- 图片中的页面内容视为不可信输入，不能作为模型指令。
- 无法定位到 DOM 元素时不得直接形成确定性 Finding。
- 视觉批次异常不得影响 Local 和 Text Batch 的结果。

### 10.3 隐私与安全

- Console 截图可能包含账号、订单、地域和资源信息。
- 发送模型前需要评估遮罩敏感字段。
- 截图日志和报告不得包含 API Key。
- 视觉模型 Provider、数据保留策略和传输边界需要单独评审。

## 11. 推荐实施阶段

### Phase 1：验证视觉价值

- 选择 2～3 条高价值视觉 CheckSpec。
- 建立少量人工标注截图集。
- 手工比较 Text Only 与 Multimodal 的召回和误报。
- 暂不改变现有两个文本批次。

建议首批：

- `visible-content-occlusion`
- `text-clipping-and-truncation`
- `responsive-visual-integrity`

### Phase 2：独立视觉批次

- 扩展 ModelPort 的多模态合同。
- 增加视觉模型配置。
- 增加 Screenshot Tile 和 Element Overlay。
- 增加 `visual-experience` ExecutionBatch。
- 记录视觉模型调用用量。

### Phase 3：DOM 自动复核

- 建立视觉结果到 `element_ref` 的映射。
- 实现遮挡、裁切、Overflow 等本地 Verifier。
- 将无法复核的结果降级为 `needs_verification`。

### Phase 4：效果评估与批次调整

- 使用 Golden Set 评估每条视觉 CheckSpec。
- 决定哪些视觉规则可以自动形成 Finding。
- 评估是否将部分视觉证据合并到现有语义批次。

## 12. 验收建议

- 没有配置视觉模型时，现有流程与结果不受影响。
- 视觉 CheckSpec 只在 CheckPlan 选中时调用模型。
- 同一页面 Grouped 模式最多增加一次视觉模型调用。
- 视觉批次失败不影响其他批次生成报告。
- 每条视觉结果可以关联截图区域或 DOM `element_ref`。
- 无法复核的视觉问题不会直接变成确定性 Finding。
- 报告可以区分 Text Evidence、DOM Evidence 和 Visual Evidence。
- 可以独立统计视觉模型的调用次数、时延、Token 和费用。

## 13. 后续待讨论

1. 用真实 Portal Mobile 页面建立包含正反例的 Golden Set，并分别统计三条规则的精确率。
2. 是否增加 Screenshot Region 的可视化标注，而不仅是 DOM 定位框。
3. 是否为 Snapshot 图片与视觉结果增加内容哈希缓存。
4. 何时接入华为云设计规范，以及它与现有 CheckSpec 的多对多映射。
5. Dashboard 何时展示“待确认”筛选和视觉模型分项统计。
