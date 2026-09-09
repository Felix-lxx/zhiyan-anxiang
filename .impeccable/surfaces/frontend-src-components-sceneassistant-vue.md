---
version: 1
slug: "frontend-src-components-sceneassistant-vue"
primary_target: "frontend/src/components/SceneAssistant.vue"
related_targets: ["frontend/src/components/OperationsCenter.vue"]
---

# 场景助手 · Operate

## Direction contract

THESIS：面向当前演练的只读教练；解释真实数据，不另建通用聊天页面。

OWN-WORLD：继承导演台深墨绿、浅绿文字和细线 SVG；独立滚动，不挤压任务正文。

STORY：打开助手，确认场次与时间，提问，查看回答依据，再跳到现有操作区。

FIRST VIEWPORT：导演工具列有文字明确的 AI 助手入口；侧栏顶部显示场次、模型模式，中部问题和回答，底部输入与发送。手机使用带关闭按钮的全高面板。

FORM：现有界面局部扩展，无随机方向选择。签名交互是从带时间戳的回答依据定位居民或打开任务区；不直接执行处置。

FINISH：unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

模型提供方未指定；默认离线解读，管理员配置后由用户勾选才向模型发送精简上下文。回放使用历史快照，不混入未来事件或当前得分。
