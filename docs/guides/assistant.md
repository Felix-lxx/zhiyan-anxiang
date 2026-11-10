# 助手配置与交互

## 使用入口

导演台打开“安巷指挥助手”，在同一个工作区切换“场景对话”和“目标计划”。对话负责解释与导航，目标计划负责提出可批准的行动。人员、任务、车辆与知识原文复用当前工作区，不并排增加多个浮窗。

对话按场次与账号保存，刷新可恢复，支持历史分页和明确清空；清空提升代次，旧请求不能重新写回。切换场次读取对应记录。外部模型授权不随对话恢复自动恢复。详见 [训练记录](training-records.md)。

## 服务配置

默认 `ASSISTANT_PROVIDER=offline`，读取真实快照与授权知识，不调用外部模型。使用兼容服务时，在本地 `.env` 设置：

```dotenv
ASSISTANT_PROVIDER=compatible
ASSISTANT_BASE_URL=https://<provider>/v1
ASSISTANT_MODEL=<available-model>
ASSISTANT_API_KEY=<local-secret>
ASSISTANT_TIMEOUT_SECONDS=60
```

服务端追加 `/chat/completions`，基础 URL 不重复包含该路径。远程地址要求 HTTPS，不接受 URL 账号、密码、查询参数或重定向。选择账号实际提供的模型名称；模型“已配置”仅表示字段完整。

本地进程可使用已安装的 Ollama：

```dotenv
ASSISTANT_PROVIDER=ollama
ASSISTANT_BASE_URL=http://127.0.0.1:11434
ASSISTANT_MODEL=<installed-model>
ASSISTANT_API_KEY=
```

Ollama 的 HTTP 例外仅允许本机地址。容器内 `127.0.0.1` 指容器自身，不能直接用上述地址指向宿主机服务。

配置修改后重启后端；Compose 使用 `docker compose up -d --build backend` 重新创建后端容器以载入配置。密钥只在后端读取，不写入前端或 Git。进入助手后明确授权再调用；失败时显示实际降级状态，不伪造模型回答。

## 资料与权限

每次查询先校验场次及社区归属，再读取当前或指定历史时刻。历史上下文不混入未来结果。现场、知识和工具结果分别显示来源；知识引用定位固定文档版本与片段。模型输入为有界摘要及用户提交内容，用户主动写入问题的敏感信息仍可能被发送。

目标计划使用受约束的只读工具，检查候选、路线、资源和引用。模型失败时保留领域计算结果，实际动作仍需人工批准并通过统一命令应用服务。

语音识别只填写草稿，参见 [语音输入](speech.md)。知识库配置见 [知识与智能体](knowledge-and-agent.md)，当前验证范围见 [最新验收](../reports/2026-11-10-acceptance.md)。
