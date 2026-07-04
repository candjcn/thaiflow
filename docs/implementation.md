# 短视频泰语学习播放器 — 实现方案

## 一、整体架构

```
┌─────────────────────────────────────┐
│         浏览器 (前端 UI)              │
│  HTML5 Video Player + 句子列表面板    │
│  双语字幕覆盖层                       │
└──────────────┬──────────────────────┘
               │ HTTP API
┌──────────────▼──────────────────────┐
│        Python 后端 (Flask)           │
│  ┌─────────────────┐ ┌───────────┐  │
│  │ 在线语音识别 API  │ │ DeepSeek  │  │
│  │ (断句+转写)      │ │ (翻译)    │  │
│  └─────────────────┘ └───────────┘  │
└─────────────────────────────────────┘
```

## 二、技术选型

### 语音识别（断句 + 转写）

**首选：Groq Whisper API（免费）**
- 使用 Groq 托管的 Whisper large-v3 模型
- 免费额度充足，速度极快（约实时的 10 倍）
- 支持泰语，返回带时间戳的逐句转写结果
- API 格式兼容 OpenAI Whisper API

**备选：OpenAI Whisper API（极低成本）**
- $0.006/分钟，一个 1 分钟短视频仅需约 ¥0.04
- 按量计费，无最低消费
- 同样支持泰语，返回格式相同

### 翻译

**DeepSeek API**
- 使用 `deepseek-chat` 模型
- 性价比高，中文翻译质量好
- 批量翻译所有句子，一次 API 调用即可

### 前端

- 原生 HTML/CSS/JavaScript，无需框架
- HTML5 `<video>` 元素播放 MP4
- 轻量，适合老机器运行

### 后端

- Python + Flask
- 轻量，仅作为 API 代理和文件服务

## 三、核心实现逻辑

### 3.1 语音识别与断句

```python
# 使用 Groq API（兼容 OpenAI 格式）
from openai import OpenAI

client = OpenAI(
    api_key="groq-api-key",
    base_url="https://api.groq.com/openai/v1"
)

def transcribe(video_path):
    with open(video_path, "rb") as f:
        result = client.audio.transcriptions.create(
            model="whisper-large-v3",
            file=f,
            response_format="verbose_json",
            timestamp_granularities=["segment"]
        )
    # result.segments = [{text, start, end}, ...]
    return result.segments
```

### 3.2 翻译

```python
import requests

def translate_sentences(sentences, source_lang="泰语"):
    prompt = f"将以下{source_lang}句子逐句翻译为中文，保持编号对应：\n"
    for i, s in enumerate(sentences):
        prompt += f"{i+1}. {s}\n"

    response = requests.post(
        "https://api.deepseek.com/chat/completions",
        headers={"Authorization": "Bearer <DEEPSEEK_API_KEY>"},
        json={
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": prompt}]
        }
    )
    # 解析返回的翻译结果
    return parse_translations(response.json())
```

### 3.3 按句重复播放（前端核心）

```javascript
let currentIndex = 0;
let repeatCount = 0;
let maxRepeat = 5;     // 用户可调
let sentences = [];    // [{text, translation, start, end}, ...]

video.addEventListener('timeupdate', () => {
    const sentence = sentences[currentIndex];
    if (!sentence) return;

    if (video.currentTime >= sentence.end) {
        repeatCount++;
        if (repeatCount < maxRepeat) {
            // 重复当前句
            video.currentTime = sentence.start;
            video.play();
        } else {
            // 进入下一句
            repeatCount = 0;
            currentIndex++;
            if (currentIndex < sentences.length) {
                video.currentTime = sentences[currentIndex].start;
                video.play();
            }
        }
    }
});
```

## 四、API 接口设计

### POST /api/transcribe
上传视频，返回断句结果。
```json
// 请求：multipart/form-data，字段 video
// 响应：
{
    "segments": [
        {"index": 0, "text": "สวัสดี", "start": 0.0, "end": 1.2},
        {"index": 1, "text": "คุณเป็นอย่างไร", "start": 1.5, "end": 3.0}
    ],
    "language": "th"
}
```

### POST /api/translate
翻译句子列表。
```json
// 请求：
{
    "segments": [
        {"index": 0, "text": "สวัสดี"},
        {"index": 1, "text": "คุณเป็นอย่างไร"}
    ],
    "source_lang": "th"
}
// 响应：
{
    "translations": [
        {"index": 0, "text": "สวัสดี", "translation": "你好"},
        {"index": 1, "text": "คุณเป็นอย่างไร", "translation": "你好吗"}
    ]
}
```

## 五、项目文件结构

```
videoplayer/
├── CLAUDE.md               # 项目上下文（给 Claude Code 参考）
├── docs/
│   ├── requirements.md     # 需求文档
│   └── implementation.md   # 实现方案（本文档）
├── backend/
│   ├── app.py              # Flask 主入口
│   ├── transcribe.py       # 语音识别模块
│   ├── translate.py        # 翻译模块
│   └── requirements.txt    # Python 依赖
├── frontend/
│   ├── index.html          # 主页面
│   ├── player.js           # 播放器逻辑
│   ├── subtitle.js         # 字幕逻辑
│   └── style.css           # 样式
└── videos/                 # 视频存放目录（gitignore）
```

## 六、实施计划

### 阶段一：P0 核心播放功能
1. 搭建 Flask 后端骨架
2. 接入 Groq Whisper API，实现断句
3. 实现前端视频播放器 + 按句重复播放
4. 实现句子列表面板（高亮、跳转）
5. 添加播放控制（上/下一句、速度调节）

### 阶段二：P1 双语字幕
6. 接入 DeepSeek API，实现翻译
7. 实现字幕覆盖层显示
8. 添加字幕显示/隐藏开关

### 阶段三：P2 断句编辑
9. 实现拖拽调整句子起止时间
10. 实现合并/拆分句子

## 七、依赖与环境

### Python 依赖
```
flask
flask-cors
openai          # 用于调用 Groq/OpenAI Whisper API
requests        # 用于调用 DeepSeek API
python-dotenv   # 环境变量管理
```

### 环境变量（.env）
```
GROQ_API_KEY=xxx          # Groq API key（首选语音识别）
OPENAI_API_KEY=xxx        # OpenAI API key（备选语音识别）
DEEPSEEK_API_KEY=xxx      # DeepSeek API key（翻译）
ASR_PROVIDER=groq         # 语音识别服务商：groq 或 openai
```
