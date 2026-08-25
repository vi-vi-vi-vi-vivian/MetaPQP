# MetaPQP 规范来源与 CheckSpec 映射

## 1. 模型

规范来源、规范条款与可执行检查是三类不同对象：

```text
StandardSource 1 ── * StandardCriterion
                         *
                         │ StandardReference
                         *
                     CheckSpec 1 ── * CheckRun ── * Finding
```

- `StandardSource`：规范集合及其治理信息，例如 WCAG 2.2、Nielsen 可用性启发式、MetaPQP 内部检查建议。
- `StandardCriterion`：来源中的单个条款或原则，例如 WCAG 2.5.8、Nielsen H2。
- `CheckSpec`：能被计划、执行和评审的原子检查规则。
- `StandardReference`：Criterion 与 CheckSpec 的多对多关系，保存关系强度和边界说明。

配置分别位于：

- `config/standards/sources.yaml`
- `config/standards/criteria.yaml`
- `config/check_specs/*.yaml` 的 `standard_refs`

## 2. 当前规范来源

| 来源 | 类型 | 状态 | 用途 |
| --- | --- | --- | --- |
| WCAG 2.2 | 外部标准 | active | 可访问性成功准则 |
| Nielsen 10 Usability Heuristics | 外部启发式 | active | 通用可用性原则 |
| MetaPQP Internal Review Guidance | 内部检查建议 | active | 当前产品体验与工程质量检查 |
| Huawei Cloud Design Standard | 组织设计规范 | reserved | 预留；正式规则和版本进入目录前禁止引用 |

`reserved` 只代表保留扩展位置，不代表已经获得或实现该规范。Registry 会拒绝 CheckSpec 引用 reserved 来源。

## 3. 关系类型

| relation | 含义 | 报告可以表达 | 报告不能表达 |
| --- | --- | --- | --- |
| `implements` | CheckSpec 直接实现内部规则 | 违反/满足该内部检查建议 | 外部认证或整体合规 |
| `partial_coverage` | 只自动验证外部条款的一部分 | 与该条款相关，当前证据未满足已检查部分 | 已完整验证该条款或整个标准 |
| `supports` | 检查结果为条款提供支持证据 | 为条款评估提供证据 | 单独决定条款合规性 |
| `inspired_by` | 规则设计受启发式原则指导 | 与该原则相关 | “违反”具有强制性的标准条款 |

默认采用保守映射。没有可说明的直接关系时，只引用 MetaPQP 内部检查建议，不为了增加“权威感”而挂接外部规范。

## 4. 为什么必须是多对多

一条规范可能需要多个 CheckSpec 才能形成完整证据。例如 WCAG 1.1.1 不仅涉及 `img alt`，还可能涉及图标、图表、验证码和媒体等检查；当前 `image-alt` 只能标为 `partial_coverage`。

一个 CheckSpec 也可能同时关联多个条款。例如 `document-structure` 同时实现内部标题结构规则，并为 WCAG 2.4.2 和 1.3.1 提供不同程度的支持证据。

因此不能要求“一条外部规范只对应一条 CheckSpec”，也不能把 CheckSpec 本身当成外部规范条款。

## 5. 新增规则时改哪些层

不一定三个对象都要新增：

| 场景 | StandardSource | StandardCriterion | CheckSpec / standard_refs |
| --- | --- | --- | --- |
| 在现有规范下增加一个新检查 | 不改 | 条款已存在则不改 | 新增 CheckSpec，并引用已有 Criterion |
| 第一次使用现有规范中的新条款 | 不改 | 新增 Criterion | 新增或修改 CheckSpec 映射 |
| 引入全新的规范体系 | 新增 Source | 新增实际使用的 Criterion | 新增或修改 CheckSpec 映射 |
| 只是调整检测算法，规则语义不变 | 不改 | 不改 | CheckSpec 升版本，更新 Checker/Skill |
| 只是修正规范映射 | 不改 | 视情况而定 | 修改 `standard_refs`，CheckSpec 升版本并记录原因 |

每个新 CheckSpec 至少应引用一条 MetaPQP 内部 Criterion，使内部规则的业务所有权明确；外部引用是经过审查后的补充，不是强制凑数。

## 6. 输出与版本

`audit.json` 从 schema `2.3` 起：

- Finding 输出结构化 `standard_refs[]`，包含来源、条款、关系和说明；
- 顶层 `standards` 对本次实际使用的来源与条款去重；
- HTML 报告区分外部标准、可用性启发式、内部检查建议和组织设计规范；
- 旧报告不回写，新运行按新 schema 生成。

新增来源、条款或映射后，必须通过 Registry 校验与测试；未知条款和 reserved 来源会阻止启动，避免静默生成错误的规范声明。
