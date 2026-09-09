---
name: 智演安巷 · 场景助手
description: 既有导演台内的只读场景解读面板；记录当前实现，不定义全局视觉系统。
colors:
  panel: "#102b27"
  text: "#e9f1e8"
  panel-border: "#3a5a4e"
  context: "#193830"
  divider: "#335347"
  button: "#214238"
  button-hover: "#315647"
  button-text: "#e5eee0"
  button-border: "#4b6b5c"
  primary: "#d8e8bb"
  primary-hover: "#e6f2cf"
  primary-text: "#173d2a"
  focus: "#afd5a4"
  input: "#0d241f"
  input-border: "#65836a"
  input-text: "#edf5e7"
  placeholder: "#abc1ac"
  user-message: "#25493b"
  error: "#ffd0b8"
typography:
  title: {fontSize: "19px", lineHeight: 1.4}
  headline: {fontSize: "25px", lineHeight: 1.5, letterSpacing: "-.025em"}
  body: {fontSize: "13px", fontWeight: 400, lineHeight: 1.7}
  label: {fontSize: "12px"}
rounded:
  panel: "14px"
  message-input: "10px"
  button: "7px"
  mode: "5px"
spacing:
  control-gap: "8px"
  section-gap: "12px"
  log-inset: "20px"
components:
  button-primary: {backgroundColor: "{colors.primary}", textColor: "{colors.primary-text}", rounded: "{rounded.button}", padding: "7px 12px"}
  button-primary-hover: {backgroundColor: "{colors.primary-hover}"}
  button-secondary: {backgroundColor: "{colors.button}", textColor: "{colors.button-text}", rounded: "{rounded.button}", padding: "8px 10px"}
---

# Design System: 场景助手（局部实现记录）

## Overview

范围仅为 `frontend/src/components/SceneAssistant.vue` 与 `frontend/src/assistant.css`。面板继承导演台深墨绿与浅绿文字，使用既有细线 SVG 图标。本文按已实现界面及 `docs/场景助手_界面约定.md` 记录事实；不是全局设计系统，也未新增视觉方向或访谈结论。

## Colors

主操作使用浅绿底与深绿字；普通操作使用较亮的深绿底，悬停进一步提亮。面板、场次条、用户发言与输入区通过不同深绿底区分。浅绿焦点轮廓与暖色错误文字同时配合文本语义，错误并非仅靠颜色表达。关键色值见前置元数据。

## Typography

局部样式未指定新字体族；输入区显式继承字体。面板标题对应 title，欢迎语对应 headline，基础正文对应 body；回答为 14px、行高 1.85，并保留换行、允许长词换行。角色名与普通按钮为 12px，依据为 12px；数据时间、字数提示和免责声明至少 11px。手机回答与输入为 16px，依据为 14px。

## Layout

桌面面板绝对定位：顶部 16px、右侧 88px、底部最终生效值 84px，宽度为 `min(430px, calc(100% - 112px))`，层级 42。纵向结构依次为标题、场次、独立滚动对话、固定于面板底部的输入区；不挤压导演台正文。标题内边距 18px 20px，对话区 20px，相邻消息间隔 22px。

视口宽度不超过 760px 时改为固定定位，边距 8px、层级 90；支持 VisualViewport 时跟随其高度与偏移，标题/场次左右及对话区内边距缩至 16px。可视高度小于 560px 时暂时隐藏常见问题、配置与页脚，优先显示输入和发送；输入区可滚动，对话允许缩小。常见问题默认显示两项，点击“全部 5 个问题”展开；问题按钮换行而非横向挤压。

## Elevation & Depth

助手局部 CSS 没有声明阴影或动画；层次来自底色、边框及覆盖层级。对话区设置滚动链隔离，滚动条沿用绿色系。焦点使用 3px 实线轮廓与 2px 外偏移，覆盖按钮、展开摘要、复选框与文本输入。

## Shapes

面板、消息/输入、按钮、模式标签分别采用前置元数据记录的圆角；面板裁切溢出内容。容器与输入以 1px 边框定界，场次条、依据区和输入区用细分隔线划分。头部图标按钮至少 36px 宽、36px 高，默认透明背景与边框。

## Components

- 按钮：发送为浅绿主按钮；定位/导航和配置检查为深绿次按钮；建议问题按钮默认透明。禁用态透明度为 0.5；禁用时不应用悬停底色。发送等待期间替换为“停止等待”。
- 输入：外层框内边距 10px 12px，文本区透明、无自身边框，高度 45–110px，可垂直调整；最多 2000 字。Enter 发送、Shift+Enter 换行，中文输入法组合输入期间不触发发送。等待期间禁用输入，失败恢复文字，并提供“重试本次问题”。清空需要就地确认，可保留对话。
- 依据：每条助手回答附模式、数据时间及快照/回放标签；原生 details 默认折叠，摘要显示依据数量。点击回答里的有效编号可展开并聚焦对应依据；未知编号保留纯文本。新回答滚动至开头，不自动跳过长回答。导航按钮只发出入口定位事件，不直接执行演练指令。
- 配置与只读状态：场次条显示最新快照或历史时刻，以及离线/模型模式。模型授权在折叠配置中显式勾选，等待时不可更改；配置展开区域最多 145px 高并滚动。欢迎语和页脚明确只读、训练用途及页面内保存对话的边界。
- 可访问性：有可读名称的侧栏、图标按钮和输入标签；对话使用 polite 日志播报与忙碌状态，等待使用 status，错误使用 alert。手机以 dialog 语义和 Tab/Shift+Tab 首尾循环管理焦点；Esc 优先取消清空确认，否则关闭并回到入口。手机回复后不强制唤起键盘，桌面恢复输入焦点。历史/实时模式切换、回放时刻变化或实时推进至少 15 秒，会标明旧回答并提供按新快照重答。

## Do's and Don'ts

- Do 保留场次、数据时间、模式、依据展开与只读说明；这些信息用于区分离线规则、模型问答和历史回放。
- Do 延续本面板已实现的文字层级、焦点轮廓与小屏滚动行为。
- Don't 把导航入口描述为已执行指令，或将离线解读标示为大模型回答。
- Don't 将本文件的局部尺寸、配色或圆角扩大为全站规范；本文不涉及既有 COMP_ROUND_OPEN 的调整。
