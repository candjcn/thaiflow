# ReelSpeak — 短视频外语学习播放器

## 项目定位
通过短视频学外语的 Web 应用：自动断句、按句复读、双语字幕、影子跟读 + AI 发音评分、音轨编辑。
**当前阶段：个人工具向产品过渡** —— 自用打磨中，目标做成面向公众的产品。快速迭代优先，但涉及多用户/隐私的功能要按产品标准考虑。

## 技术栈
- **前端**: 原生 HTML/CSS/JavaScript，无任何框架（硬性规定，适配 2015 老 Mac）
- **后端**: Python + Flask（`backend/app.py` 单入口）
- **语音识别**（整视频）: Groq Whisper / Azure Speech / combined（智能校准：Groq 断句 + Azure 文本）
- **单句二次识别**: Groq / Azure / Gemini（音轨编辑器里选择）
- **翻译**: DeepSeek API（目标语言跟随界面语言）
- **发音评分**: Azure Speech Pronunciation Assessment
- **泰语分词**: Gemini 自动在词间加空格（识别后处理，字符级安全校验）
- **视频下载**: yt-dlp（TikTok/YouTube 链接）

## 用户环境
- 开发机：2015 款 Mac，无 GPU，所有 AI 处理必须走在线 API
- 移动端判定：宽度 ≤1024px 或触屏（平板也用手机 UI）；CSS 用 `max-width: 1024px, (pointer: coarse)`

## 部署与运行
- **线上**: https://reelspeak.517lang.com （正式地址，Cloudflare 代理 + SSL Full 模式；备用 https://thaiflow.up.railway.app）
- GitHub `candjcn/thaiflow`，push main 自动部署到 Railway
- **本地**: `python backend/app.py`，端口 5000；手机局域网测试 `http://192.168.1.3:5000`
- **HTTPS 限制**: 录音（麦克风）和原生全屏在本地 HTTP 下不可用，必须用 Railway 线上测
- **环境变量**（backend/.env + Railway Variables）: GROQ_API_KEY、AZURE_SPEECH_KEY/REGION、DEEPSEEK_API_KEY、GEMINI_API_KEY、ADMIN_KEY
- **使用日志**: `/api/admin/logs?key=ADMIN_KEY`；Railway 控制台搜 `[USAGE]`

## 项目结构
- `frontend/` — landing.html（首页）、index.html（播放器 /app）、player.js、style.css、i18n.js
- `backend/` — app.py（路由）、transcribe.py（识别/分词）、translate.py、pronounce.py、export.py
- `videos/` — 视频与字幕 JSON（不提交 git；Railway 上重新部署即清空）
- `docs/` — 需求文档

## 开发规范
- 前端不引入任何框架/构建工具；新增 UI 文案必须同步 i18n.js 全部 5 种语言（zh-CN/zh-TW/en/ja/ko）
- API key 只走 .env，不硬编码；后端 API 返回 JSON（出错返回 `{error}` 而非 500 HTML）
- CSS 注意特异性：全局 `button, select` 规则在文件后部，组件规则需加父类前缀（如 `.controls .ctrl-btn:hover`）
- 许多按钮 id 被 JS 引用但已无 UI（藏在 index.html 的隐藏 div 里），删元素前先查引用

## 工作流（Claude 自动执行，无需询问）
1. 改动完成 → `node --check` / Python `ast.parse` 语法检查
2. 后端接口改动 → 本地起服务用 curl 实测
3. 检查通过 → **自动 commit 并 push origin main**（即部署 Railway）
4. UI 改动无法自行视觉验证时，明确告知用户需在浏览器/手机验收哪些点

## 关键决策记录（勿无意推翻）
- **视频不持久化（方案 C）**: Railway 不挂 Volume/对象存储。工作流以本地文件为主：识别完自动下载视频+JSON 到本地，SRT 由句子列表"保存"按钮获取（手机端一次全存）。
- **原生全屏优先**: Android 的"滑动退出全屏"系统提示无法去除，用户确认全屏效果更重要；HTTP 下降级 CSS 模拟全屏。
- **默认播放模式 = 播一遍**（repeat=1）；"三遍复读/影子跟读"是可再点取消的 toggle。
- **桌面播放控制纯键盘**: 空格/←→/R/↑↓/L/S/F/Esc，无实体播放按钮；快捷键用键帽（kbd）样式标注在界面上；底部栏 60% 宽悬浮，左=双模式入口，中=重复/速度，右=列表；返回/全屏在视频左上/右上角。
- **首页服务器视频列表保留显示**: 识别失败的视频靠它重试（曾因隐私移除后又恢复）。
- **界面语言自动检测**: zh-CN/zh-TW/ja/ko 有对应版本，其余默认英文；字幕翻译目标跟随界面语言。
- **影子跟读切句不打断**: 左右滑/上下句切换时保持跟读状态继续按遍数朗读。
- **跟读面板布局固定**: 按钮区不动，波形/评分向上扩展；录音无声音不自动回放、评分按钮回放结束后才可用。
- **手机端已确认 UX 勿回退**: 用户多次强调"之前我没让你改的，不要又改回去"。
