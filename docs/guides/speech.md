# 语音输入

讯飞“语音听写大模型（中英）V1.0”接入使用 `wss://iat.xf-yun.com/v1`，负责语音转文字，与聊天模型和 Embedding 分别配置。

## 使用与配置

在助手的场景对话或目标计划中点击语音输入。浏览器采集音频，结束识别后把文字填入草稿，用户编辑后再发送或生成方案；不自动执行命令。取消录音不上传音频，关闭或切换视图释放麦克风。

在本地、被 Git 忽略的 `.env` 设置并重启后端：

```dotenv
SPEECH_PROVIDER=xfyun_iat_v1
SPEECH_APP_ID=<app-id>
SPEECH_API_KEY=<local-key>
SPEECH_API_SECRET=<local-secret>
```

停用使用 `SPEECH_PROVIDER=disabled`。Compose 显式传入这些字段；修改后需重新创建后端容器。供应商账号须具备相应能力；已配置不代表可用额度或识别效果已经验收。

## 采集与接口

麦克风要求可信 HTTPS 或本机地址，以及 AudioWorklet。普通局域网 HTTP 页面不能据此承诺手机可录音。采集后重采样为 16kHz、16 位小端单声道 PCM，最长 30 秒。

接口为 `GET /api/v1/speech/status` 与 `POST /api/v1/speech/transcribe`。后端要求登录、限制账号并发与请求频率、接受有限大小的 PCM；签名和供应商连接 URL 不返回前端。音频在内存处理，不写入项目数据库或文件。

转写处理动态替换、取消、超时、无内容及上游失败；识别字数超限需用户缩短。已经上传的音频可能已被供应商处理，取消等待不撤销此前服务调用。

浏览器朗读使用设备自身的语音合成能力，不是讯飞语音合成接入。本轮仓库交付未执行真实供应商音频转写；协议回归与隔离浏览器录音不能替代供应商识别质量验证。

协议参考：[讯飞文档](https://www.xfyun.cn/doc/spark/spark_zh_iat.html)。项目当前实际验证见 [验收记录](../reports/2026-11-10-acceptance.md)。
