# 智果园页面检查清单

采集入口：<https://agentorchard.huaweicloud.com/index.html>  
采集日期：2026-08-25  
范围：入口页、顶部业务页签、正文直接可达业务页面，以及这些页面继续可达的一层产品详情/购买/体验页面。

## 执行约定

- `portal`：默认执行 Desktop zh-CN、Mobile zh-CN。
- `console`：默认执行 Desktop zh-CN、Desktop en-US，要求自动登录。
- 页脚中的法律、备案、帮助、联系方式、通用账号中心等站点级链接不作为独立检查对象；其链接有效性仍由来源页面的 `broken-links` 检查覆盖。
- “在线体验”“控制台”“参与邀测”不等同于购买页。没有实际购买入口时明确标记为“无购买页”。
- 模型目录会动态变化；每轮执行前重新抓取目录并与本文附录对比，新增、下架和 URL 变化都应记录。

## A. 入口与顶部页签

| 完成 | page_id | 页面 | page_surface | 默认场景 | URL | 说明 |
|---|---|---|---|---|---|---|
| [ ] | `orchard-home` | 智果园首页 | portal | Desktop/Mobile zh-CN | <https://agentorchard.huaweicloud.com/index.html> | 根入口 |
| [ ] | `agents-index` | 智能体聚合页 | portal | Desktop/Mobile zh-CN | <https://agentorchard.huaweicloud.com/agent.html> | 聚合 CodeArts、OfficeAce、DocZip、营销智能体 |
| [ ] | `agentarts-ecosystem` | 智果 AgentArts 开放能力页 | portal | Desktop/Mobile zh-CN | <https://agentorchard.huaweicloud.com/agentarts.html> | 开放能力与开发工具聚合页 |
| [ ] | `models-index` | 百模千态模型目录 | portal | Desktop/Mobile zh-CN | <https://agentorchard.huaweicloud.com/models.html> | 动态模型目录，模型详情见附录 |
| [ ] | `tokenplan-awareness` | Token Plan 感知页 | portal | Desktop/Mobile zh-CN | <https://agentorchard.huaweicloud.com/tokenplan.html> | 可独立购买产品 |
| [ ] | `industry-ai-index` | 行业 AI 梦工厂 | portal | Desktop/Mobile zh-CN | <https://www.huaweicloud.com/ai/> | 行业专区与公测产品聚合页 |

## B. 产品感知页与购买页

### B1. 智果 AgentArts

| 完成 | 页面阶段 | page_id | page_surface | 默认场景 | URL | 状态 |
|---|---|---|---|---|---|---|
| [ ] | 感知 | `agentarts-awareness` | portal | Desktop/Mobile zh-CN | <https://www.huaweicloud.com/product/agentarts.html> | 已确认 |
| [ ] | 使用入口 | `agentarts-console-home` | console | Desktop zh-CN/en-US | <https://console.huaweicloud.com/agentarts/?region=cn-southwest-2#/home/overview> | 已确认；不是购买页 |
| [ ] | 购买 | — | — | — | — | 当前页面未发现独立购买入口；“免费试用/控制台”不按购买页处理 |

### B2. 华为云码道 CodeArts 代码智能体

| 完成 | 页面阶段 | page_id | page_surface | 默认场景 | URL | 状态 |
|---|---|---|---|---|---|---|
| [ ] | 感知 | `codearts-awareness` | portal | Desktop/Mobile zh-CN | <https://codearts.huaweicloud.com/> | 已确认 |
| [ ] | 价格 | `codearts-pricing` | portal | Desktop/Mobile zh-CN | <https://codearts.huaweicloud.com/pricing.html> | 二层页面 |
| [ ] | 购买 | `codearts-purchase` | console | Desktop zh-CN/en-US | <https://codearts.huaweicloud.com/portal/settings/subscription?from=buy> | 需要登录；显式指定 `page_surface=console` |

### B3. 果办 OfficeAce 办公智能体

| 完成 | 页面阶段 | page_id | page_surface | 默认场景 | URL | 状态 |
|---|---|---|---|---|---|---|
| [ ] | 感知/价格 | `officeace-awareness` | portal | Desktop/Mobile zh-CN | <https://www.huaweicloud.com/product/agentarts/officeace.html> | 同页包含套餐价格 |
| [ ] | 购买 | `officeace-purchase-standard` | console | Desktop zh-CN/en-US | <https://console.huaweicloud.com/agentarts/?region=cn-southwest-2#/shopping?product_list=%5B%7B%22skuCode%22:%22officeace.personal.package.standard%22%7D%5D&type=OfficeAce> | 个人标准版，98 元/月；需要登录 |
| [ ] | 购买 | `officeace-purchase-advanced` | console | Desktop zh-CN/en-US | <https://console.huaweicloud.com/agentarts/?region=cn-southwest-2#/shopping?product_list=%5B%7B%22skuCode%22:%22officeace.personal.package.advanced%22%7D%5D&type=OfficeAce> | 个人高级版，198 元/月；需要登录 |
| [ ] | 购买 | `officeace-purchase-premium` | console | Desktop zh-CN/en-US | <https://console.huaweicloud.com/agentarts/?region=cn-southwest-2#/shopping?product_list=%5B%7B%22skuCode%22:%22officeace.personal.package.premium%22%7D%5D&type=OfficeAce> | 个人旗舰版，498 元/月；需要登录 |

说明：体验版是客户端下载，不作为购买页；企业版当前显示“敬请期待”，暂不生成购买检查。

### B4. DocZip / WorkAgent 智能文档服务

| 完成 | 页面阶段 | page_id | page_surface | 默认场景 | URL | 状态 |
|---|---|---|---|---|---|---|
| [ ] | 感知 | `doczip-awareness` | portal | Desktop/Mobile zh-CN | <https://agentorchard.huaweicloud.com/workagent.html> | 已确认 |
| [ ] | 邀测申请 | `doczip-recruitment` | portal | Desktop/Mobile zh-CN | <https://developer.huaweicloud.com/signup/ab29daa9855f43a98e208c11ecd809bc> | 线索/邀测阶段，不是购买页 |
| [ ] | 购买 | — | — | — | — | 当前未开放购买 |

### B5. 营销智能体

| 完成 | 页面阶段 | page_id | page_surface | 默认场景 | URL | 状态 |
|---|---|---|---|---|---|---|
| [ ] | 产品卡片 | `marketing-agent-coming-soon` | portal | 随 `agents-index` 覆盖 | <https://agentorchard.huaweicloud.com/agent.html> | 当前仅“敬请期待”，无独立详情或购买页 |

### B6. Token Plan

| 完成 | 页面阶段 | page_id | page_surface | 默认场景 | URL | 状态 |
|---|---|---|---|---|---|---|
| [ ] | 感知 | `tokenplan-awareness` | portal | Desktop/Mobile zh-CN | <https://agentorchard.huaweicloud.com/tokenplan.html> | 已确认 |
| [ ] | 订阅管理入口 | `tokenplan-management` | console | Desktop zh-CN/en-US | <https://console.huaweicloud.com/modelarts/?region=cn-southwest-2#/model-studio/resourcePlanManagement> | 感知页“立即订阅”实际入口 |
| [ ] | 购买 | `tokenplan-purchase` | console | Desktop zh-CN/en-US | <https://console.huaweicloud.com/modelarts/?region=cn-southwest-2#/model-studio/resourcePlanManagement/purchase> | 已确认；需要登录 |

### B7. MaaS / 百模千态

| 完成 | 页面阶段 | page_id | page_surface | 默认场景 | URL | 状态 |
|---|---|---|---|---|---|---|
| [ ] | 感知/目录 | `maas-models-awareness` | portal | Desktop/Mobile zh-CN | <https://agentorchard.huaweicloud.com/models.html> | 已确认 |
| [ ] | 资源计划购买 | `maas-tokenplan-purchase` | console | Desktop zh-CN/en-US | <https://console.huaweicloud.com/modelarts/?region=cn-southwest-2#/model-studio/resourcePlanManagement/purchase> | 与 Token Plan 共用，不是单模型购买页 |

单模型详情大多直接位于 Console，展示模型能力和按量价格，但没有独立“购买”动作；按“详情/决策页”检查，不应误标为购买页。

### B8. 行业 AI 梦工厂中的可识别产品

| 完成 | 产品 | 页面阶段 | page_id | page_surface | 默认场景 | URL | 状态 |
|---|---|---|---|---|---|---|---|
| [ ] | CloudRobo | 感知/公测体验 | `cloudrobo-awareness` | portal | Desktop/Mobile zh-CN | <https://www.huaweicloud.com/product/cloudrobo.html> | 公测，未发现购买页 |
| [ ] | 医疗 AI 使能平台（智慧病理） | 体验入口 | `ai-pathology-experience` | console | Desktop zh-CN/en-US | <https://console.huaweicloud.com/ai-pathology/?region=cn-southwest-2> | 未发现购买页 |
| [ ] | 健康管理助手基础版 | 体验入口 | `health-assistant-experience` | portal | Desktop/Mobile zh-CN | <https://health.developer.huaweicloud.com/> | 公测，未发现购买页 |
| [ ] | 农科发现·探索者 | 体验入口 | `agri-explorer-experience` | console | Desktop zh-CN/en-US | <https://console.huaweicloud.com/neweihealth/?region=cn-east-3#/agsci> | 未发现购买页 |
| [ ] | CSP 病理格式体验 | 体验页 | `csp-format-experience` | portal | Desktop/Mobile zh-CN | <https://www.huaweicloud.com/ai/cspformat.html> | 二层页面，不是购买页 |

行业专区卡片还包括智慧金融、智慧医疗、具身智能、科学计算和智能制造。当前卡片由脚本点击驱动，未暴露稳定 `href`；在获得稳定 URL 前由 `industry-ai-index` 覆盖，不先创建猜测 URL 的独立任务。

## C. 其他二层业务页面

这些页面从首页或 AgentArts 能力页可达，但不是“感知页 + 购买页”产品对。

| 完成 | page_id | 页面 | page_surface | 默认场景 | URL | 分类 |
|---|---|---|---|---|---|---|
| [ ] | `skills-market` | Skills 市场 | portal | Desktop/Mobile zh-CN | <https://skills.huaweicloud.com/> | 开放能力 |
| [ ] | `ai-shell-awareness` | AI Shell | portal | Desktop/Mobile zh-CN | <https://developer.huaweicloud.com/aishell.html> | 开发工具 |
| [ ] | `openjiuwen-external` | openJiuwen | portal | Desktop/Mobile（按站点实际语言） | <https://www.openjiuwen.com/> | 外部站点，建议独立产品域管理 |

AgentArts 页面还展示 API/SDK、Terraform Explorer、KooCLI、开发者空间、云学堂和开发者社区等卡片，但当前部分卡片未暴露稳定链接。它们由 `agentarts-ecosystem` 页面先行覆盖，获得稳定目标 URL 后再进入独立检查列表。

## D. 百模千态动态模型详情

下列 40 个模型是 2026-08-25 在 `models.html` 中直接展示的详情入口。除 openPangu-2.0-Pro 外均为 Console 详情页，默认只跑 Desktop zh-CN/en-US；openPangu-2.0-Pro 是门户详情页，默认跑 Desktop/Mobile zh-CN。

| 完成 | 模型 | page_id | URL |
|---|---|---|---|
| [ ] | openPangu-2.0-Pro | `model-openpangu-2-pro-detail` | <https://www.huaweicloud.com/product/modelarts/studio/maas-openpangu-2-pro.html> |
| [ ] | openPangu-2.0-Flash | `model-openpangu-2-flash-detail` | <https://console.huaweicloud.com/modelarts/?region=cn-southwest-2#/model-studio/square/1ec90d21-8c0f-4c4f-9a8e-01fdcd90daf9/detail> |
| [ ] | GLM-5.2 | `model-glm-5-2-detail` | <https://console.huaweicloud.com/modelarts/?region=cn-southwest-2#/model-studio/square/861f7fdc-9451-418f-9ed6-9bd3af1b3ad6/detail> |
| [ ] | GLM-5.1 | `model-glm-5-1-detail` | <https://console.huaweicloud.com/modelarts/?region=cn-southwest-2#/model-studio/square/911c468c-82e4-4e6d-a247-01e43702f7fa/detail> |
| [ ] | GLM-5 | `model-glm-5-detail` | <https://console.huaweicloud.com/modelarts/?region=cn-southwest-2#/model-studio/square/09a90e9f-8ab5-4289-8851-d397cf261913/detail> |
| [ ] | Kimi-K2.6 | `model-kimi-k2-6-detail` | <https://console.huaweicloud.com/modelarts/?region=cn-southwest-2#/model-studio/square/2e21e24c-c519-41be-bcb8-7a3df91586bc/detail> |
| [ ] | ViduQ3-Turbo T2V | `model-viduq3-turbo-t2v-detail` | <https://console.huaweicloud.com/modelarts/?region=cn-southwest-2#/model-studio/square/5a4c7ab1-e8b8-48d3-b0ae-688d3bf4345f/detail> |
| [ ] | ViduQ3-Turbo IT2V | `model-viduq3-turbo-it2v-detail` | <https://console.huaweicloud.com/modelarts/?region=cn-southwest-2#/model-studio/square/615e47c2-4170-412d-a785-f9658a33a7b4/detail> |
| [ ] | PixVerse V6 T2V | `model-pixverse-v6-t2v-detail` | <https://console.huaweicloud.com/modelarts/?region=cn-southwest-2#/model-studio/square/808a2a24-218a-4080-8fc2-ce0e83f37373/detail> |
| [ ] | DeepSeek-V4-Pro | `model-deepseek-v4-pro-detail` | <https://console.huaweicloud.com/modelarts/?region=cn-southwest-2#/model-studio/square/73451de8-daaf-4bc5-a7a0-64aa9239567b/detail> |
| [ ] | DeepSeek-V4-Flash | `model-deepseek-v4-flash-detail` | <https://console.huaweicloud.com/modelarts/?region=cn-southwest-2#/model-studio/square/780ef592-b052-431a-a0cf-3211a5a20367/detail> |
| [ ] | DeepSeek-V3.2 | `model-deepseek-v3-2-detail` | <https://console.huaweicloud.com/modelarts/?region=cn-southwest-2#/model-studio/square/d5fb0d08-90a9-49f9-9e5d-6fa5ea7b2996/detail> |
| [ ] | DeepSeek-R1-0528 | `model-deepseek-r1-0528-detail` | <https://console.huaweicloud.com/modelarts/?region=cn-southwest-2#/model-studio/square/d68c500f-9954-4968-87f8-db198499f5b8/detail> |
| [ ] | DeepSeek-V3 | `model-deepseek-v3-detail` | <https://console.huaweicloud.com/modelarts/?region=cn-southwest-2#/model-studio/square/fca5aa4d-e957-40fe-986c-7197ead5b8cc/detail> |
| [ ] | DeepSeek-V3.1-128K | `model-deepseek-v3-1-128k-detail` | <https://console.huaweicloud.com/modelarts/?region=cn-southwest-2#/model-studio/square/e59699a8-b742-4cc3-a3e9-44a289152f05/detail> |
| [ ] | DeepSeek-V3.1-64K | `model-deepseek-v3-1-64k-detail` | <https://console.huaweicloud.com/modelarts/?region=cn-southwest-2#/model-studio/square/267f39a3-423c-4b2d-92d7-7ad6fe6ac71a/detail> |
| [ ] | Qwen-Image | `model-qwen-image-detail` | <https://console.huaweicloud.com/modelarts/?region=cn-southwest-2#/model-studio/square/401c423d-8f5d-4c79-bdd5-9195122de960/detail> |
| [ ] | Qwen-Image-Edit | `model-qwen-image-edit-detail` | <https://console.huaweicloud.com/modelarts/?region=cn-southwest-2#/model-studio/square/89054e9d-4bbe-4613-9b32-7d447acd20ab/detail> |
| [ ] | Qwen3-30B-A3B-128K | `model-qwen3-30b-a3b-128k-detail` | <https://console.huaweicloud.com/modelarts/?region=cn-southwest-2#/model-studio/square/4f68028f-f5b2-40b0-a9f1-716aa35166f2/detail> |
| [ ] | Qwen3-30B-A3B-32K | `model-qwen3-30b-a3b-32k-detail` | <https://console.huaweicloud.com/modelarts/?region=cn-southwest-2#/model-studio/square/97fc999f-87d0-42c1-baa3-61950a197c0e/detail> |
| [ ] | Qwen2.5-VL-72B-32K | `model-qwen2-5-vl-72b-32k-detail` | <https://console.huaweicloud.com/modelarts/?region=cn-southwest-2#/model-studio/square/35a09517-c60c-437a-8d41-5fdb7ebb8d22/detail> |
| [ ] | Qwen2.5-VL-72B-48K | `model-qwen2-5-vl-72b-48k-detail` | <https://console.huaweicloud.com/modelarts/?region=cn-southwest-2#/model-studio/square/49481f67-6faf-4442-bdbc-00d9502b86f3/detail> |
| [ ] | Qwen3-235B-A22B | `model-qwen3-235b-a22b-detail` | <https://console.huaweicloud.com/modelarts/?region=cn-southwest-2#/model-studio/square/1c558327-2e40-4e1d-b4ec-c2f5f53a9a7c/detail> |
| [ ] | Qwen3-235B-A22B-64K | `model-qwen3-235b-a22b-64k-detail` | <https://console.huaweicloud.com/modelarts/?region=cn-southwest-2#/model-studio/square/5bb7f809-130f-4305-b291-41545c02b065/detail> |
| [ ] | Qwen3-235B-A22B-32K | `model-qwen3-235b-a22b-32k-detail` | <https://console.huaweicloud.com/modelarts/?region=cn-southwest-2#/model-studio/square/942f4b1a-46d7-402d-a21d-7c472fcc263c/detail> |
| [ ] | Qwen3-32B | `model-qwen3-32b-detail` | <https://console.huaweicloud.com/modelarts/?region=cn-southwest-2#/model-studio/square/b5c8e9a3-d2db-4dd5-aa2d-f3ec89797d9d/detail> |
| [ ] | Qwen3-32B-64K | `model-qwen3-32b-64k-detail` | <https://console.huaweicloud.com/modelarts/?region=cn-southwest-2#/model-studio/square/b9f21a05-69db-4080-8fc2-ce0e83f37373/detail> |
| [ ] | Qwen3-32B-32K | `model-qwen3-32b-32k-detail` | <https://console.huaweicloud.com/modelarts/?region=cn-southwest-2#/model-studio/square/cad5b29b-c6d2-44af-9a7c-d5fa0eea0627/detail> |
| [ ] | Wan2.2-T2V-A14B | `model-wan2-2-t2v-a14b-detail` | <https://console.huaweicloud.com/modelarts/?region=cn-southwest-2#/model-studio/square/32417dd3-085d-443e-9a6e-fa1ef27bc99f/detail> |
| [ ] | Wan2.2-I2V-A14B | `model-wan2-2-i2v-a14b-detail` | <https://console.huaweicloud.com/modelarts/?region=cn-southwest-2#/model-studio/square/566f8a10-7017-493c-bc49-5780a298e58b/detail> |
| [ ] | LongCat-Flash-Chat | `model-longcat-flash-chat-detail` | <https://console.huaweicloud.com/modelarts/?region=cn-southwest-2#/model-studio/square/ec03aa27-c747-473f-8263-5230a6876973/detail> |
| [ ] | BGE-M3 | `model-bge-m3-detail` | <https://console.huaweicloud.com/modelarts/?region=cn-southwest-2#/model-studio/square/794c0d6a-0e9f-44b6-8121-bdea0b6a9362/detail> |
| [ ] | BGE-Reranker-V2-M3 | `model-bge-reranker-v2-m3-detail` | <https://console.huaweicloud.com/modelarts/?region=cn-southwest-2#/model-studio/square/e1b07273-6fcc-47a1-9dde-c9a3e1019d02/detail> |
| [ ] | ViduQ3-Turbo KF2V | `model-viduq3-turbo-kf2v-detail` | <https://console.huaweicloud.com/modelarts/?region=cn-southwest-2#/model-studio/square/b8019706-b0f9-483f-8b4d-e9e13bec1045/detail> |
| [ ] | ViduQ3-Turbo R2V | `model-viduq3-turbo-r2v-detail` | <https://console.huaweicloud.com/modelarts/?region=cn-southwest-2#/model-studio/square/71e81d4d-1a62-49ce-8225-0012a9af571a/detail> |
| [ ] | ViduQ3-Pro T2V | `model-viduq3-pro-t2v-detail` | <https://console.huaweicloud.com/modelarts/?region=cn-southwest-2#/model-studio/square/6c82e22d-db06-4466-a6d2-7ed1fd6497e9/detail> |
| [ ] | ViduQ3-Pro IT2V | `model-viduq3-pro-it2v-detail` | <https://console.huaweicloud.com/modelarts/?region=cn-southwest-2#/model-studio/square/fe30c70b-d68b-4f53-afe5-3adcbd445b34/detail> |
| [ ] | ViduQ3-Pro KF2V | `model-viduq3-pro-kf2v-detail` | <https://console.huaweicloud.com/modelarts/?region=cn-southwest-2#/model-studio/square/add75d44-6f14-419e-b978-9ba3e307bd22/detail> |
| [ ] | PixVerse V6 KF2V | `model-pixverse-v6-kf2v-detail` | <https://console.huaweicloud.com/modelarts/?region=cn-southwest-2#/model-studio/square/1011521e-70da-4fb2-b9fd-7b6e4359e359/detail> |
| [ ] | PixVerse V6 R2V | `model-pixverse-v6-r2v-detail` | <https://console.huaweicloud.com/modelarts/?region=cn-southwest-2#/model-studio/square/7c314f98-c958-4786-a2c9-16049626fe8d/detail> |

## E. 建议的首轮执行顺序

1. 入口与五个顶部页签：验证导航、内容分层和产品发现路径。
2. CodeArts、OfficeAce、Token Plan：三组存在真实购买能力的完整“感知 → 购买”链路。
3. AgentArts、DocZip、CloudRobo 和行业 AI 公测产品：验证“免费试用/邀测/体验”是否被准确表达，避免与购买混淆。
4. 百模千态目录与前三个推荐模型：先验证目录到详情/体验的链路。
5. 其余动态模型详情：作为批量目录回归执行；模型新增或下架时更新附录。
