# 贡献指南

本仓库采用“模块化单体 + 领域服务”的交付方式：保持一个可独立部署的演练系统，同时用明确边界避免三维、实时、评分和智能体逻辑相互缠绕。

## 开始前

1. 从 `main` 新建 `codex/<短描述>` 分支；一个分支只处理一个可验证的目标。
2. 不提交 `.env`、运行数据库、访问令牌、真实参演码或生成截图。
3. 修改状态规则前，先阅读 [架构总览](docs/architecture/README.md) 与对应领域测试。

## 依赖方向

```text
Vue 页面 / Three.js 表现层
          ↓
composables、domain 类型、API 客户端
          ↓ REST / WebSocket
FastAPI 路由（鉴权、输入校验、HTTP 映射）
          ↓
领域服务（演练、空间、车辆、智能体、评分）
          ↓
SQLAlchemy 模型、事件与快照
```

- 路由层不实现仿真规则；新增规则应进入 `backend/app/services/`。
- Three.js 只消费服务端确认的状态，不预测或直接修改演练结果。
- 写操作必须保留命令、事件或评分证据；不要只修改浏览器状态。
- 新增服务不得反向依赖 Vue 或 HTTP 细节。现有少数历史适配点列在 ADR 中，应逐步迁移而不是复制。

## 提交前检查

```powershell
# 后端
Set-Location backend
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider

# 前端
Set-Location ../frontend
npm run test
npm run build
```

若变更导演台、手机参演端或 Three.js 表现，还应检查 1440px、1024px、390px 宽度下的主操作路径；浮层应有独立滚动容器，不能遮挡当前必须操作的控件。

## Pull Request 要求

- 描述用户可观察到的行为改变，而不是只列出文件名。
- 说明状态如何写入、实时如何同步、失败如何反馈或回滚。
- 写明已运行的命令；未运行的检查要说明原因。
- 改动数据结构或接口时，同时更新 `docs/architecture/` 中相应说明。
