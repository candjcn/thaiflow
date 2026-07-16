# ReelSpeak — Session Handoff Document

> 生成时间：2026-07-10  
> 本文件供下一个新 session 快速上手，涵盖项目全貌 + 近期改动 + 已知问题 + 下一步方向

---

## 一、项目定位

**ReelSpeak**（原名 ThaiFlow）：通过短视频学外语的 Web 应用。核心流程：
1. 贴视频链接（TikTok/YouTube）或上传本地视频
2. AI 自动语音识别 + 断句 + 翻译
3. 逐句重复播放 → 影子跟读 → AI 发音评分

当前阶段：**个人工具向产品过渡**，自用打磨中。

---

## 二、技术栈与项目结构

```
videoplayer/
├── frontend/
│   ├── index.html        # 播放器页面 (/app)
│   ├── landing.html      # 首页
│   ├── player.js         # 播放器核心逻辑（~3300行）
│   ├── style.css         # 播放器样式
│   ├── i18n.js           # 6语言国际化（zh-CN/zh-TW/en/ja/ko/th）
│   ├── landing.css
│   └── manifest.json     # PWA 配置
├── backend/
│   ├── app.py            # Flask 路由入口（全部 API）
│   ├── transcribe.py     # 语音识别 + 泰语分词
│   ├── translate.py      # DeepSeek 翻译
│   ├── tts.py            # 文字转语音（Gemini/Azure/有道）
│   ├── pronounce.py      # Azure 发音评分
│   ├── export.py         # 视频导出（ffmpeg）
│   └── r2.py             # Cloudflare R2 存储（句子收藏音频）
├── docs/
│   ├── requirements.md
│   ├── roadmap.md
│   └── session-handoff.md  ← 本文件
└── CLAUDE.md             # 项目规范（Claude 必读）
```

**前端原则**：纯原生 HTML/CSS/JS，零框架，适配 2015 款 Mac + 手机

---

## 三、部署

| 项目 | 值 |
|------|----|
| 线上地址 | https://reelspeak.517lang.com |
| 备用地址 | https://thaiflow.up.railway.app |
| 平台 | Railway（push main 自动部署） |
| GitHub | candjcn/thaiflow |
| 本地启动 | `python backend/app.py`，端口 5000 |
| 手机局域网 | http://192.168.1.3:5000 |

**注意**：
- Cloudflare 仅 DNS（橙云关闭），不走代理，SSL 由 Railway 签发
- Railway 已挂载 Volume（`/data`），`commerce.db` 持久化于此，重新部署不丢失
- 录音/全屏需要 HTTPS，本地测不了，须用线上地址

---

## 四、环境变量

在 `backend/.env` 和 Railway Variables 中：

```
GROQ_API_KEY=...           # Groq Whisper 识别
AZURE_SPEECH_KEY=...       # Azure 语音识别 + 发音评分
AZURE_SPEECH_REGION=...
DEEPSEEK_API_KEY=...       # 翻译
GEMINI_API_KEY=...         # 分句/TTS/OCR
OPENAI_API_KEY=...         # OpenAI Whisper 识别（最准）
ADMIN_KEY=...              # 管理接口鉴权
COMMERCE_DB_PATH=/data/commerce.db  # Railway Volume 持久化路径
CF_R2_*=...                # Cloudflare R2（句子收藏音频）
GEMINI_MODEL=gemini-2.0-flash  # 可选，默认即此值
```

---

## 五、本 Session 完成的主要改动

### 5.1 PWA（渐进式 Web 应用）
- 创建 `manifest.json`，图标 icon-180/192/512.png
- iOS Safari：检测到未安装 PWA 时，延迟 3 秒弹引导提示（底部横幅），指引"共享 → 添加到主屏幕"
- 微信浏览器：显示专属引导步骤（长按打开浏览器）
- Android：监听 `beforeinstallprompt`，弹出一键安装按钮
- PWA 独立模式下跳过 `requestFullscreen()`，避免 Chrome 弹系统通知
- 修复 iOS 刘海屏：`.phase-select` 加 `padding-top: calc(20px + env(safe-area-inset-top))`

### 5.2 系统级返回键支持（Android/iOS）
- 进入播放器 → `history.pushState({rs:"play"})`
- 打开句子列表 → 再 pushState；关闭按钮 → `replaceState`
- 打开影子跟读 → 再 pushState；关闭按钮 → `replaceState`
- `popstate` 事件处理优先级：影子跟读 → 句子列表 → 退出播放器
- 移动端返回按钮触发 `history.back()` 而非直接 `backToSelect()`

### 5.3 移动端底部 Tab 按钮调大
- `align-items: stretch`（等高）
- 字体：12px → 14px（tab），16px → 19px（列表按钮）

### 5.4 iOS/Android bug 修复
- **识别完成后弹文件查看器**：`saveToLocal()` 在移动端非交互式调用时直接 return，不触发 blob 下载
- **iOS 视频下载被屏蔽**：检测 `isIosSafari()` 时自动切仅下载字幕，并弹 toast 提示

### 5.5 i18n 补全
- `drawer.save`（句子列表"保存"按钮）
- `drawer.delete`（左滑删除按钮）
- PWA 引导相关 key：`pwa.title/desc/steps/steps.wechat/install`
- `ios.noVideoDownload`（iOS 视频下载限制提示）

### 5.6 TTS 引擎自动 fallback
- Gemini TTS 失败 → 自动切 Azure；Azure 失败 → 切 Gemini
- 逐句 fallback（不重启整课，已切换引擎继续生成后续句子）

### 5.7 Gemini 模型修复
- `gemini-2.5-flash` 对新用户已下线 → 全部改为 `gemini-2.0-flash`
- 涉及：`backend/tts.py`（3处）、`backend/transcribe.py`（1处）
- TTS 专用模型 `gemini-2.5-flash-preview-tts` 和图片模型 `gemini-2.5-flash-image` 保持不变

### 5.8 单词释义气泡重设计
- 背景从浅黄暖色改为 Apple iOS 白色毛玻璃：`rgba(255,255,255,0.82)` + `backdrop-filter: blur(20px)`
- 收藏星按钮改为关闭 × 按钮（`.word-popup-close`）
- 颜色体系改为 iOS 语义灰：`#111` / `#3c3c43` / `#8e8e93`

---

## 六、关键设计决策（勿推翻）

详见 `CLAUDE.md`，以下是最重要的几条：

1. **前端零框架**：只用原生 JS，不引入 React/Vue/Alpine 等
2. **视频不持久化，账号数据持久化**：视频/字幕 JSON 仍不持久化（工作流靠本地文件）；`commerce.db` 已挂 Railway Volume（`/data/commerce.db`）持久化，重新部署不丢失用户账号/积分数据
3. **识别引擎首选 OpenAI whisper-1**：泰语准确率最高，不做多引擎对比后处理
4. **泰语分句以源文空格为唯一切分点**：不用硬性词数上限
5. **手机调试优先加诊断**：在页面显示错误，不要盲目猜测修复
6. **字幕无底色 + 描边文字**：用户明确拒绝了黑色药丸背景
7. **默认播放一遍**（repeat=1），三遍复读/影子跟读是 toggle

---

## 七、已知待做事项

### 高优先（用户提到过但未做）
- [ ] **单词收藏/生词本功能**：`.word-popup-star` 代码占位在 player.js:3026，点击事件有 TODO 注释，但功能未实现
- [ ] **iOS 学习记录丢失问题**：Safari 7 天清 IndexedDB（PWA 模式下免疫，但普通浏览器用户有风险）

### 中优先
- [ ] OpenAI API 费用监控（whisper-1 按分钟计费）
- [ ] 使用日志统计：`/api/admin/logs?key=ADMIN_KEY`

### 低优先 / 待定
- [ ] 生词本后端存储（当前 R2 只存句子收藏音频）
- [ ] 多语言字幕导出（SRT 支持已做，其他格式按需）

---

## 八、常见 API 端点

| 端点 | 功能 |
|------|------|
| `POST /api/transcribe` | 视频语音识别（流式 SSE） |
| `POST /api/tts/generate` | 文字→语音课程（Gemini/Azure/有道） |
| `POST /api/translate` | 翻译单段字幕 |
| `POST /api/word/define` | 单词定义查询（词典/AI） |
| `POST /api/pronounce` | Azure 发音评分 |
| `GET  /api/videos` | 列出服务器上的视频 |
| `POST /api/download` | yt-dlp 下载 TikTok/YouTube |
| `GET  /api/admin/logs?key=KEY` | 使用日志 |

---

## 九、快速上手检查

新 session 开始时建议执行：
```bash
git log --oneline -5          # 看最近改了什么
python backend/app.py         # 本地启动
# 开浏览器 http://localhost:5000
```

如需调试手机端问题，记住：
- **页面底部会显示诊断版本号**（rev badge）
- **列表加载错误会显示在列表区域**（不再静默吞掉）
- 录音必须用 HTTPS 线上地址测试
