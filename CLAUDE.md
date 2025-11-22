# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

Dify on WeChat 是一个将 Dify LLMOps 平台接入微信生态的机器人项目，是 chatgpt-on-wechat 的下游分支。支持多种通道（个人微信、企业微信、公众号等）和多种 AI 模型（Dify、Coze、OpenAI、DeepSeek 等）。

## 常用命令

```bash
# 启动应用
python app.py

# 后台运行
nohup python3 app.py & tail -f nohup.out

# 安装依赖
pip3 install -r requirements.txt
pip3 install -r requirements-optional.txt

# Docker 部署
cd docker && docker compose up -d
docker logs -f dify-on-wechat
```

## 核心架构

### 入口和配置
- `app.py` - 应用入口，初始化配置和启动通道
- `config.py` - 配置定义和验证（只读，不要修改此文件的值）
- `config.json` - 实际生效的配置文件

### 分层架构

**Channel 层** (`channel/`)
处理不同消息平台的接入：
- `gewechat/` - 个人微信 (推荐，基于 iPad 协议)
- `wechat/` - 个人微信 (itchat，已不稳定)
- `wework/` - 企业微信个人号
- `wechatcom/` - 企业微信应用
- `wechatmp/` - 微信公众号
- `chat_channel.py` - 通道基类，处理消息分发

**Bot 层** (`bot/`)
对接不同 AI 服务：
- `dify/` - Dify 平台 (支持 chatbot/agent/workflow)
- `openai/` - OpenAI API
- `deepseek/` - DeepSeek
- `bot_factory.py` - Bot 工厂，根据配置创建对应 bot

**Plugin 层** (`plugins/`)
插件系统，扩展功能：
- `plugin_manager.py` - 插件管理器
- `godcmd/` - 管理员命令
- `group_chat_summary/` - 群聊总结
- `jina_sum/` - 链接内容总结
- `custom_dify_app/` - 按群切换 Dify 应用

### 消息流程
1. Channel 接收消息 → 2. Bridge 路由 → 3. Bot 处理 → 4. 插件处理 → 5. Channel 发送回复

## 关键配置项

```json
{
  "channel_type": "gewechat",  // 通道类型
  "model": "dify",             // AI 模型
  "dify_api_base": "https://api.dify.ai/v1",
  "dify_api_key": "app-xxx",
  "dify_app_type": "chatbot"   // chatbot/agent/workflow
}
```

## 开发注意事项

- 使用 `common/log.py` 中的 `logger` 进行日志记录
- 配置值在 `config.py` 中定义格式，在 `config.json` 中设置实际值
- 插件开发参考 `plugins/README.md` 和现有插件结构
- gewechat 通道需要同省服务器部署
- 语音功能需要安装 ffmpeg
