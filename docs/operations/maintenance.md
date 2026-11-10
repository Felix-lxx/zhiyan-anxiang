# 数据维护与交付检查

## 派生快照

事件和冻结成绩是权威记录，快照是可重建缓存。服务兼容旧 JSON 与压缩快照，HTTP GZip 与 WebSocket 状态协议分别处理。

维护命令读取当前数据库配置。先确认数据库并备份；默认只估算，不写入：

```powershell
Set-Location backend
.venv/Scripts/python.exe -m app.maintenance.compact_snapshots
.venv/Scripts/python.exe -m app.maintenance.compact_snapshots --apply --batch-size 50
```

回退到不支持压缩格式的旧服务前执行：

```powershell
.venv/Scripts/python.exe -m app.maintenance.compact_snapshots --restore-json --apply
```

命令不删除事件或成绩、不自动执行 VACUUM；无法识别的缓存不强行转换。数据库逻辑体积变小不代表文件空间立即归还系统。

## 仓库检查

在根目录执行 `python scripts/check_repository.py`。检查暂存/已跟踪及未忽略新文件的相对文档链接、误入库运行文件、常见凭据特征、超大文件和完全相同的源码。只输出路径，不输出匹配凭据；重复源码属于人工审查提示，不自动删除。

`.gitignore` 只影响未跟踪文件；误入库文件仍需从版本中移除。不得删除正在使用的数据库来“清理仓库”。历史移除文件可由 Git 历史恢复，日常整理不重写提交历史。

构建和测试命令见 [贡献指南](../../CONTRIBUTING.md)。本地完整运行不等于 GitHub Actions 已成功，远端状态应以对应提交的实际检查结果为准。
