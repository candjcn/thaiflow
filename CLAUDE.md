# 短视频泰语学习播放器

## 项目简介
一个帮助用户通过短视频学习泰语的 Web 应用。核心功能是自动断句并按句重复播放，辅以双语字幕。

## 技术栈
- **前端**: 原生 HTML/CSS/JavaScript（无框架，适配老机器）
- **后端**: Python + Flask
- **语音识别**: Groq Whisper API（免费）或 OpenAI Whisper API（备选）
- **翻译**: DeepSeek API（deepseek-chat 模型）
- **视频格式**: MP4

## 用户环境
- 2015 款 Mac，无 GPU
- 所有 AI 处理必须走在线 API，不能本地运行模型

## 关键设计决策
- 前端不使用任何框架，保持轻量
- 语音识别使用 Groq 托管的 Whisper，不在本地运行
- 翻译使用 DeepSeek，性价比最优

## 需求优先级
- P0: 自动断句 + 按句重复播放
- P1: 双语字幕（泰语/英语 → 中文）
- P2: 手动编辑断句时间点

## 项目结构
- `docs/` — 需求文档和实现方案
- `backend/` — Flask 后端
- `frontend/` — 前端页面
- `videos/` — 视频文件（不提交到 git）

## 开发规范
- API key 通过 .env 文件配置，不硬编码
- 后端 API 返回 JSON
- 前端与后端通过 HTTP API 通信
