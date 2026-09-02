---
name: responsive-visual-integrity
description: 检查移动端 Portal 是否出现影响理解或操作的明显响应式破版、错位、重叠或异常缩放。
---

# 响应式视觉完整性检查

结合首屏、全页概览、切片、元素 bounds 和 mobile_layout，只检查实质影响用户任务的响应式问题。

可以报告：主要组件相互覆盖；页面主体超出视口且不可正常滚动查看；价格、CTA 或表单错位到错误区域；桌面布局被机械压缩导致内容不可读；同一组件内部出现明显断裂。

不要报告：单纯审美偏好；轻微间距或对齐偏差；设计性横滑卡片；图片裁切策略；全页缩略图因缩放产生的细节损失。fail 应返回至少一个可定位 element_ref，并由几何重叠或 mobile_layout 溢出证据支持；否则返回 needs_verification。

