# 2026-11-10 决策实跑与联动修复

## 实际运行结果

使用当前工作树、独立 SQLite 数据库、真实 HTTP/WebSocket 和后台时钟验收。前端 `127.0.0.1:5181`，后端 `127.0.0.1:8011`；教学模式、4 倍速；外部模型、语音及远程 Embedding 关闭。未替换时钟、提高暴露阈值或改写已结束成绩。

最后一轮服务端冻结结果如下。责任任务由验收客户端逐项接收、到位和提交文字证据，不代表实体设备接入或现实现场处置。

| 案例与策略 | 得分 | 到场 / 清点 | 暴露超阈值 | 责任任务 | 演练时长 |
| --- | ---: | --- | ---: | --- | ---: |
| 厨房：撤空后门控、分流与护送 | 98 | 8/8，8/8 | 1 | 4/4 完成 | 203 秒 |
| 充电棚：立即撤离 | 92 | 18/18，18/18 | 7 | 3/3 完成 | 188 秒 |
| 充电棚：消防车压制后逐栋放行 | 81 | 18/18，18/18 | 0 | 3/3 完成，2 项超时核验 | 688 秒 |

三场智能体均为 `completed`。该状态表示目标行动、责任任务与清点已核对，不表示满分。厨房和立即撤离的扣分来自暴露；逐栋策略的扣分来自超时核验和整体效率。零暴露策略存在明显时间代价。

本轮较早的真实场次分别取得厨房 100、99 分及充电棚 96 分。它们不是受控时钟重复实验；4 倍速会放大请求、后台负载与动作时机的差异，本次未据此声称性能提升或成绩可稳定复现。早期分批脚本曾在 180 秒墙钟上限截断未完成场次，得到 76 分，不能作为完整策略的对照成绩；后续延长等待后取得完整结果。

## 已落实的修复

| 问题及触发条件 | 修改位置 | 处理与证据 |
| --- | --- | --- |
| 本地方案先写暂停、再等命令锁；后台持命令锁等 SQLite 写入，出现锁等待反转 | `api/routes/agent.py`、`services/engine_scheduler.py` | 本地暂停、解释和候选生成进入同一事务门，失败先回滚；后台租约及首次读取同样纳入。最终三场日志未再出现数据库锁异常 |
| 刷新凭证已轮换但响应丢失，旧 Cookie 导致页面回跳登录 | `api/routes/auth.py`、`core/security.py`、`models/auth.py` | 上一个凭证仅在 10 秒内重试并得到同一个后继凭证，不延长窗口或会话有效期；数据库只保存哈希。测试覆盖重试、窗口到期与注销 |
| 长时间部分到场反而可能比最终全员到场获得更高效率分 | `services/scoring.py` | 部分与完整疏散使用同一延迟扣分，再按到场比例计入；无人到场无速度分。计算版本更新为 4，已冻结成绩保持原值 |
| 机器人等前栋全员到场后才前往下一栋 | `services/agent_release.py` | 上栋广播完成后可提前前往下一栋；下一次广播及居民放行仍等前栋实际到场和有效压制条件 |
| 首栋有限时域仿真无法说明全批次耗时 | `services/agent_schedule.py`、`AgentPlanWorkspace.vue` | 增加逐栋时序估算与截止风险；与正式仿真指标区分。明确不含新增拥堵、护送接近、交通等待及人工核验，缺少路线不填造时间 |
| 超时完成摘要只显示“已核验” | `agent_task_graph.py`、`TaskWorkflow.vue`、`AgentPlanWorkspace.vue` | 转发 `completed_on_time`，直接显示“超时核验”，保留实际证据与扣分 |
| 已结束计划仍显示停止按钮及未下令文案 | `AgentPlanWorkspace.vue`、`AgentPlanningEvidence.vue` | 终态移除不适用的执行操作；已批准记录明确为批准前依据 |
| 地图名称仍被覆盖为约 12.64px | `frontend/src/map-editor.css` | 将名称 `strong` 纳入 14px 规则，浏览器复核计算值为 14px |
| 封路参数拼错可被忽略并回退到附近道路 | `schemas/operations.py` | 事件注入拒绝未知字段；正式字段为 `road_edge_id`，不再静默忽略 `edge_id` |

上述后端路径均位于 `backend/app/`。评分和动作合法性继续由服务端规则确定。

## 功能与页面证据

| 路径 | 本轮结果 |
| --- | --- |
| 参数—发布—冻结 | 两案例均实际创建、保存合法火点和人数、发布并冻结新场次 |
| 方案—执行—核验—清点—评分 | 三条完整真实 HTTP 流程，候选、命令及结束快照留存 |
| 车辆、机器人与放行 | 完成实际车辆到位、供水/喷水、逐栋移动广播及放行依赖 |
| 两端实时与恢复 | 两个独立 WebSocket 均收到增量；指定路段封锁、恢复成功；参演端重连后快照和身份保留 |
| 档案与历史 | 两案例档案成绩与冻结成绩一致；00:00 回放到场人数为 0，未混入最终结果 |
| 助手与知识 | 真实离线问答分别返回 14、12 条现场/知识来源；对话可重读；厨房检索命中 5 条资料 |
| 页面导航 | 首页、个人中心、复盘记录、知识、地图、准备、复盘共 14 个桌面/手机状态有效导航，无文档横向溢出或页面脚本异常 |
| 工作区 | 1366×650、390×844 下助手可见主要面板数为 1，终态停止按钮数为 0；手机任务页显示 2 处“超时核验” |

第一次页面批查因登录回跳作废，没有算入有效页面检查。修复后重新核对 URL 与业务内容后检查。已目视查看厨房准备、复盘、短屏助手及手机任务截图；DOM 宽度检查不代表全部浮层状态都已验收。

本地证据位于被 Git 忽略的 `output/`：

- `acceptance-20261110-delivery/`、`acceptance-20261110-delivery-staged/`：最终候选与完整结果。
- `acceptance-20261110-links/checks.json`：档案、回放、知识和两端联动断言。
- `acceptance-20261110-delivery-error.log`：最终服务日志。
- `playwright/delivery-assistant-1366.png`、`playwright/delivery-assistant-390.png`、`playwright/delivery-tasks-390.png`：最终工作区截图。
- `playwright/acceptance-fixed-preparation-390.png`、`playwright/acceptance-fixed-replay-1440.png`：准备与复盘截图。

## 检查及部署

针对性后端检查四批分别为 25、43、33、12 项通过，批次有重复，不将它们相加宣称为独立测试数量。实际命令：

```powershell
Set-Location backend
.venv/Scripts/python.exe -m pytest tests/test_scoring_v3.py tests/test_agent_release.py tests/test_system.py tests/test_connection_security.py -q --tb=short -p no:cacheprovider
.venv/Scripts/python.exe -m pytest tests/test_agent_workflow.py tests/test_agent_task_graph.py tests/test_agent_outcomes.py tests/test_agent_coordination.py tests/test_training_collection.py tests/test_realtime_commands.py -q --tb=short -p no:cacheprovider
.venv/Scripts/python.exe -m pytest tests/test_agent_review_upgrade.py tests/test_task_guidance.py tests/test_system.py tests/test_agent_release.py tests/test_scoring_v3.py -q --tb=short -p no:cacheprovider
.venv/Scripts/python.exe -m pytest tests/test_connection_security.py tests/test_operations_flow.py tests/test_command_application.py -q --tb=short -p no:cacheprovider
Set-Location ../frontend
npm test
npm run build
```

前端状态和三维回归 69 项通过，类型检查及生产构建通过。新增时序提示的 Impeccable 检查未报告问题；`git diff --check` 通过。

启动时幂等执行 `20261110_refresh_retry`，向 `auth_sessions` 增加可空的 `previous_refresh_hash`、`previous_refresh_until`，已有会话保持兼容。已在既有验收 SQLite 数据库上实际应用；回滚应用可保留新增列，不需要删除历史记录。生产升级按现有部署说明备份数据库。本轮未验证 PostgreSQL 部署。

## 剩余问题及验证缺口

1. 全批次时序仍是当前路线估算，未覆盖护送接近、队列与人工核验，尚未代替任务图全程仿真；预演不能作为最终时间保证。
2. 等前栋全员到场再放下一栋过于保守。后续应比较共同路段释放、重点人员保障和广播资源形成的策略，再从同一冻结起点验证；不能直接提高阈值补成高分。
3. 4 倍速下请求和负载仍会影响成绩，需要另做受控负载与首次用户验证。
4. 厨房模型可加载，几何/资产回归通过；未逐帧跟随所有人物检查全部转角与家具，也未执行 1000 人或低配设备 FPS 基准。世界空间标牌在远景仍偏小。
5. 真实外部大模型、Embedding、讯飞语音和实体设备未执行；知识全部上传格式、全部 CRUD 异常组合、所有导出格式及长期多用户容量未逐项重跑。

## 发布前复核

后续仓库整理中补跑完整后端 **317 项通过**、前端 **69 项通过**及类型/生产构建；恢复测试明确选择原策略，避免将喷水等待误判为广播恢复故障。过程与部署缺口见 [发布记录](2026-11-10-repository-release.md)。
