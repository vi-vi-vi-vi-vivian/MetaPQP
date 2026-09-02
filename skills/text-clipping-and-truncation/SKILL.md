---
name: text-clipping-and-truncation
description: 检查移动端 Portal 中关键文本是否因布局错误被裁切或不可读，排除正常省略号和设计性截断。
---

# 文本裁切检查

检查标题、价格、规格、CTA 和关键说明是否出现字符被容器边界切断、上下半截缺失、文本与相邻组件重叠而不可读。

只有截图可见异常，并且 DOM 的 client/scroll 尺寸及 overflow 样式能够支持异常裁切时才报告 fail。必须返回对应 element_ref。

以下情况不报告：正常省略号；多行 line-clamp；卡片摘要的设计性截断；正文在切片边界处自然延续；可横向滚动区域中的暂时不可见文本；不影响理解的微小字距差异。不确定时返回 needs_verification。

