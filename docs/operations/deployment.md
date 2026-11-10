# 启动、配置与升级

## 本地开发

依赖 Python 3.11+、Node.js 22 和 npm。从仓库根目录复制 `.env.example` 为本地 `.env`，保留已有配置时不要覆盖。后端示例：

```powershell
Set-Location backend
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
$env:DATABASE_URL='sqlite+pysqlite:///./zhiyan-local.db'
.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

另开终端：

```powershell
Set-Location frontend
npm ci
npm run dev -- --host 127.0.0.1 --port 5173
```

访问 `http://127.0.0.1:5173`；健康检查为 `http://127.0.0.1:8000/api/v1/health`，接口说明为 `/docs`。开发账号取本地配置的 `BOOTSTRAP_ADMIN_USERNAME`、`BOOTSTRAP_ADMIN_PASSWORD`。

## Compose

安装 Docker Compose 后，在根目录运行 `docker compose up --build`。前端容器通过相对 `/api/v1` 代理到后端，数据库使用 PostgreSQL。`.env` 中的助手、语音和 Embedding 分别由 Compose 显式传入后端。生产构建时的 `VITE_API_BASE_URL` 决定浏览器接口地址，不能仅在容器运行后改变它。

## 配置责任

| 配置 | 作用 |
| --- | --- |
| `DATABASE_URL` | 本地后端连接串；Compose 按 PostgreSQL 配置生成内部连接串 |
| `APP_ENV`、`JWT_SECRET`、初始管理员密码 | 环境与认证；非开发环境拒绝默认或不合要求的值 |
| `CORS_ORIGINS` | 明确允许的前端地址；生产需 HTTPS，不能使用通配地址 |
| `ACCESS_TOKEN_EXPIRE_MINUTES`、`REFRESH_TOKEN_EXPIRE_DAYS` | 访问及刷新会话有效期 |
| `PARTICIPANT_INVITE_HOURS` | 参演邀请码有效期 |
| `ASSISTANT_*`、`SPEECH_*`、`KNOWLEDGE_EMBEDDING_*` | 独立外部能力，未配置时仍可文字输入与关键词检索 |

手机参演要求可访问的地址与 CORS；麦克风需要可信 HTTPS 或本机地址。局域网 HTTP 能打开页面不代表可以录音。具体接入见 [助手](../guides/assistant.md)、[语音](../guides/speech.md) 和 [知识库](../guides/knowledge-and-agent.md)。

## 升级与回滚

1. 备份数据库及本地 `.env`，停止旧进程或安排维护窗口。
2. 安装当前后端依赖、前端 `npm ci` 和 `npm run build`，再启动后端。
3. `initialize_schema()` 创建新增表并运行幂等字段/索引迁移；确认健康检查的数据库状态正常。
4. 当前刷新恢复迁移 `20261110_refresh_retry` 为 `auth_sessions` 添加两个可空字段：`previous_refresh_hash`、`previous_refresh_until`。旧会话可继续使用；短时重试不延长会话绝对期限。
5. 既有场次、成绩和已发布引用保持原样。档案补建由组织者显式执行，不后台重算历史。
6. 回滚旧应用时可保留新增可空字段。回退到不识别压缩快照的旧版前，按 [维护说明](maintenance.md) 恢复旧 JSON 编码。

`.env`、数据库、日志、缓存和构建产物不提交。第三方模型许可随运行资产保留。生产备份与 PostgreSQL 多进程部署需在具体环境验证，当前验证记录见 [验收报告](../reports/2026-11-10-acceptance.md)。
