# 四云 AI 产品页面对比检查清单

> 更新日期：2026-09-07  
> 范围：华为云智果园中可公开访问的 AI 产品感知/定价页面，与阿里云、腾讯云、火山引擎的公开产品页面进行体验对比。  
> 目标：发现华为云页面可借鉴的体验改进机会；不做产品能力排名，也不把参考产品当作规范。

## 1. 使用原则

- 以**用户任务和页面角色**配对，而非仅凭产品名称相似。
- 首轮仅使用公开的 Desktop 中文页面；不把登录后的控制台、实际购买提交或受邀测试页面混入同一轮比较。
- 一组主体页面可在一次 `meta-pqp compare` 中传入多个 `--reference-url`；模型只采纳证据充分且任务可比的参考做法。
- 对“产品边界不同”的组合保留备注。若参考产品的用户、交付形态或商业模式明显不同，应在结果中输出“不适用”，而非建议强行对齐。

## 2. 推荐执行清单

| 优先级 | 对比主题 | 华为云主体页面 | 阿里云参考页 | 腾讯云参考页 | 火山引擎参考页 | 可比任务 |
|---|---|---|---|---|---|---|
| P0 | 多模型 Token 套餐 | [Token Plan](https://agentorchard.huaweicloud.com/tokenplan.html) | [百炼](https://www.aliyun.com/product/bailian) | [TokenHub](https://cloud.tencent.com/product/tokenhub) | [火山方舟](https://www.volcengine.com/product/ark) | 了解多模型套餐、免费体验、价格和工具接入方式，再决定是否订阅。 |
| P0 | MaaS 模型发现与调用 | [百模千态模型目录](https://agentorchard.huaweicloud.com/models.html) | [百炼](https://www.aliyun.com/product/bailian) | [TokenHub](https://cloud.tencent.com/product/tokenhub) | [火山方舟](https://www.volcengine.com/product/ark) | 发现模型、理解适用场景和定价/体验入口，并开始调用。 |
| P1 | Agent 开发与企业落地 | [智果 AgentArts](https://www.huaweicloud.com/product/agentarts.html) | [百炼](https://www.aliyun.com/product/bailian) | [WorkBuddy Enterprise](https://cloud.tencent.com/product/workbuddy-enterprise) | [AgentKit](https://www.volcengine.com/product/agentkit) | 企业或开发者了解如何构建、部署、治理智能体。腾讯页面偏企业 AI 工作平台，应仅比较相同的智能体构建与治理信息。 |
| P1 | AI 编程助手 | [华为云码道 CodeArts](https://codearts.huaweicloud.com/) | [Qoder CN](https://www.aliyun.com/product/lingma) | [CodeBuddy](https://cloud.tencent.com/product/acc) | — | 开发者了解产品形态、适用对象、体验/下载入口和订阅方案。 |
| P1 | 办公智能体 | [果办 OfficeAce](https://www.huaweicloud.com/product/agentarts/officeace.html) | — | [WorkBuddy](https://intl.cloud.tencent.com/zh/products/workbuddy) | — | 职场用户以自然语言交办文档、数据、汇报等任务，并获得可验收结果。 |

## 3. 每组比较的检查重点

系统当前的六项体验检查将按以下决策路径呈现：

| 决策路径 | 体验检查 | 在本清单中的关注点 |
|---|---|---|
| 认识价值 | 结果价值是否清晰可见；核心价值是否可先体验 | 是否展示可理解的任务结果、样例、在线体验、免费额度或试用入口。 |
| 评估并选择 | 方案选择是否清晰；关键决策信息是否在选择前说清 | 是否清楚区分模型、套餐、版本、额度、适用对象、价格和限制。 |
| 确认并开始使用 | 承诺与限制是否提前说明；用户选择是否连续保留 | 是否在订阅、下载、调用或跳转前说明前置条件、计费、权限和已有选择。 |

对比范围并不覆盖完整任务效率、实时响应、异常恢复、跨渠道承诺一致性或外部事实准确性；这些需要 Page、Transition、Journey 或后续专用检查补充。

## 4. 建议启动方式

### 4.1 Token Plan：首个全量对比

```bash
meta-pqp compare \
  --subject-url 'https://agentorchard.huaweicloud.com/tokenplan.html' \
  --subject-product '华为云 Token Plan' \
  --reference-url 'https://www.aliyun.com/product/bailian' \
  --reference-product '阿里云百炼' \
  --reference-url 'https://cloud.tencent.com/product/tokenhub' \
  --reference-product '腾讯云 TokenHub' \
  --reference-url 'https://www.volcengine.com/product/ark' \
  --reference-product '火山方舟' \
  --device desktop \
  --locale zh-CN
```

其余 P0/P1 组合沿用相同命令结构，只替换主体和参考 URL。一次运行建议不超过三个参考页，方便保留清晰的页面证据与改进归因。

## 5. 暂不纳入正式比较

| 华为云页面 | 原因 | 后续进入条件 |
|---|---|---|
| DocZip / WorkAgent 智能文档服务 | 当前是邀测/体验入口，缺少与三家厂商角色一致的公开产品感知页。 | 找到同为“终端用户文档智能体”的公开页面后再纳入。 |
| CloudRobo、医疗/农业等行业 AI 页面 | 行业、交付方式和前置条件差异过大，容易把能力差异误判为体验问题。 | 针对单一行业找到同类公开解决方案和明确用户任务。 |
| 营销智能体 | 智果园当前仅有“敬请期待”卡片，无独立产品详情。 | 出现独立感知页及体验/购买入口。 |
| 火山 TRAE | 已确认有 AI 编程产品文档，但尚未确认与 CodeArts 页面角色相同的完整公开营销/定价页。 | 取得稳定的产品落地页后，作为 CodeArts 的第三个参考对象。 |

## 6. 候选依据

- 阿里云百炼同时公开模型服务、Agent 开发、模型体验、价格和 Token Plan 信息，适合作为 Token Plan、MaaS 和 AgentArts 的参考页面。[百炼产品页](https://www.aliyun.com/product/bailian)
- 腾讯云 TokenHub 统一聚合多家模型，并提供在线体验、API、用量/费用和 Token Plan；CodeBuddy、WorkBuddy 与 WorkBuddy Enterprise 分别覆盖 AI 编程、办公智能体和企业级 Agent 平台。[TokenHub](https://cloud.tencent.com/product/tokenhub) [CodeBuddy](https://cloud.tencent.com/product/acc) [WorkBuddy Enterprise](https://cloud.tencent.com/product/workbuddy-enterprise)
- 火山方舟提供模型服务、免费额度和 Agent/Coding 计划；AgentKit 则面向 Agent 构建、部署、运行、工具、记忆和知识库等企业能力。[火山方舟](https://www.volcengine.com/product/ark) [AgentKit](https://www.volcengine.com/product/agentkit)
- Qoder CN 公开展示 AI 编码产品形态、体验入口、模型选择与团队/企业版本，和 CodeArts 的开发者决策页角色接近。[Qoder CN](https://www.aliyun.com/product/lingma)
