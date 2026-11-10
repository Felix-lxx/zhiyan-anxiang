# 文档导航

文档按当前用途组织，功能与范围以代码、现行说明和最新验收为准。被替代的阶段日志通过 Git 历史查询。

| 入口 | 内容 |
| --- | --- |
| [项目 README](../README.md) | 能力、案例、实跑、启动与结构 |
| [操作指南](../使用指南.md) | 两个角色端的完整流程 |
| [产品定位](../PRODUCT.md) | 用户、使用场景及原则 |
| [术语](glossary.md) | 冻结世界、到场/清点、预演及证据 |

## 架构与工程

- [系统架构](architecture/README.md)与[ADR-0001](architecture/adr/0001-modular-monolith.md)：分层、命令事务、任务编排、仿真、实时与数据闭环。
- [贡献指南](../CONTRIBUTING.md)：分支、依赖方向、检查与 PR。
- [界面规范](../DESIGN.md)与[助手工作区](scene-assistant/DESIGN.md)：字号、单工作区、短屏和移动端。

## 功能

- [场景与仿真](guides/scenarios-and-simulation.md)：火点、运动、供水与模型。
- [知识与智能体](guides/knowledge-and-agent.md)：资料、RAG、规划、工具、批准和修订。
- [助手配置](guides/assistant.md)：离线、兼容模型、Ollama 及授权。
- [语音输入](guides/speech.md)：讯飞、采集、限制及验证范围。
- [训练记录](guides/training-records.md)：档案、对话留存、经验审核和接口。

## 运维

- [部署与升级](operations/deployment.md)：本地、Compose、配置、迁移与回滚。
- [维护与仓库检查](operations/maintenance.md)：快照压缩、编码回退及交付检查。

## 最新证据

- [决策与联动验收](reports/2026-11-10-acceptance.md)：三条完整流程、成绩、修复和未覆盖项。
- [楼栋空间呈现](reports/2026-11-10-building-release.md)：投影、标记、定位和资源释放。
- [三维材质与消防设备](reports/2026-11-09-model-assets.md)：来源、许可与实现。
- [仓库整理与发布](reports/2026-11-10-repository-release.md)：清理清单、检查和升级说明。

[UI 设计参考](ui-design/UI界面样式图索引.md)只保留六个核心页面的参考图，不作为当前功能验收截图。README 图片来自实际运行。

历史可用 `git log --all -- docs` 或 `git show <commit>:<path>` 查询。整理不重写历史，不删除运行数据库、第三方许可或有效回归测试。
