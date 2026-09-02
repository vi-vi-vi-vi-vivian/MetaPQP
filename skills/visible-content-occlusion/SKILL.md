---
name: visible-content-occlusion
description: 检查移动端 Portal 截图中关键内容或控件是否被其他元素明显遮挡；仅报告影响阅读或操作的高置信问题。
---

# 关键内容遮挡检查

逐张查看首屏、全页概览和局部切片，并结合 DOM bounds 判断是否存在真实遮挡。

仅在以下条件同时成立时报告 fail：被遮挡对象是关键标题、价格、CTA、表单或核心说明；遮挡面积明显；用户阅读或点击受到实质影响；截图和元素坐标相互支持。

不要报告正常的粘性导航、Cookie 提示、模态框背景遮罩、轮播裁切、图片上的设计文字、装饰性重叠或仅几个像素的接触。不确定遮挡是否真实存在时返回 needs_verification。

返回至少两个 element_refs（被遮挡元素与遮挡元素）才可支持 fail；否则应返回 needs_verification。

