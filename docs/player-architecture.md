# player.js 架构规划

> 创建日期：2026-07-12  
> 当前状态：Phase 0 已完成

---

## 一、背景与问题

`player.js` 从单一功能文件逐渐演化到约 **4800 行**，涵盖 10 个功能领域，通过全局变量互相耦合。

### 已发生两次的同类崩溃

**根本原因：TDZ（Temporal Dead Zone）**

JavaScript 规则：
- `function` 声明 → 被引擎提升到顶部，随时可调用
- `let` / `const` → 不提升，声明前访问 → `ReferenceError` → 整个 JS 崩溃

触发模式：
```
第 143 行：renderFavorites()       ← function 声明，被提升，立即执行
...
第 2500 行：let _favActiveAudio    ← 在这里才初始化，上面访问 → 崩溃
            const _favIconPlay
```

- **第一次**：`LESSON_DB`（IndexedDB 实例）在调用点之后声明
- **第二次**：`_favActiveAudio` / `_favIconPlay` 在调用点之后声明

---

## 二、目标架构

### 文件结构

```
frontend/
├── player.js              ← 入口：DOM 获取、事件绑定、初始化调用（最底部）
├── i18n.js                ← 已独立（保持不变）
├── style.css              ← 已独立（保持不变）
└── modules/               ← 逐步拆出的功能模块
    ├── state.js           ← 共享状态（单一数据源）
    ├── lesson-db.js       ← IndexedDB 课程持久化
    ├── video-loader.js    ← 加载视频、本地文件、服务器列表
    ├── player-core.js     ← 播放控制、分句导航、速度
    ├── subtitles.js       ← 字幕渲染、Karaoke 高亮、拼音/罗马音
    ├── playback-modes.js  ← 复读模式、影子跟读模式
    ├── sentence-list.js   ← 句子列表面板
    ├── tts.js             ← TTS 面板、AI 内容生成
    ├── favorites.js       ← 收藏句子（bookmark + playback）
    ├── pronunciation.js   ← 录音、Azure 发音评分、波形显示
    └── export.js          ← SRT 导出、字幕导出
```

### 技术选择：原生 ES Modules

- `<script type="module" src="player.js">` —— 浏览器原生支持，无需构建工具
- 模块间用 `import` / `export`，无全局变量污染
- 完全符合"纯原生 HTML/CSS/JS"约束

### 共享状态：`state.js` 单一数据源

```js
// modules/state.js
export const state = {
    segments: [],          // 当前视频的字幕分句
    currentIndex: 0,       // 当前播放句子索引
    currentVideoName: "",  // 当前视频文件名
    repeatMode: 1,         // 复读遍数
    shadowMode: false,     // 影子跟读模式
    lang: "zh-CN",         // 界面语言
    // ... 随模块拆分逐步迁移
};
```

各模块通过 `import { state } from "./state.js"` 读写，不再靠全局变量。

---

## 三、迁移路线（渐进式）

### Phase 0 — 消除 TDZ 风险（已完成 2026-07-12）

**不拆文件，不改逻辑，只搬执行代码位置。**

规则：所有顶层执行语句（函数调用、IIFE）统一移到 `player.js` **最底部**，在所有 `let`/`const` 声明之后。

```js
// player.js 末尾（所有声明已就绪）
// ========== 启动初始化（必须在文件末尾，所有声明之后执行）==========
I18N.init();
loadVideoList();
renderFavorites();
loadLocalVideoList();
```

效果：无论以后在文件任何位置新增 `let`/`const`，都不会触发 TDZ。

---

### Phase 1 — 拆低依赖模块（触机而动）

下次需要修改以下模块时，顺手拆出：

| 模块 | 理由 |
|---|---|
| `lesson-db.js` | 自成一体，只操作 IndexedDB，无渲染依赖 |
| `favorites.js` | 边界清晰，刚整理过，依赖少 |
| `export.js` | 几乎纯函数，无副作用 |

拆出步骤：
1. 新建 `frontend/modules/xxx.js`，粘贴相关代码
2. 在模块顶部 `import { state } from "./state.js"`
3. 在 `player.js` 顶部 `import "./modules/xxx.js"`
4. 删除 `player.js` 里对应代码
5. 测试功能

---

### Phase 2 — 拆中等复杂模块

| 模块 | 依赖 |
|---|---|
| `tts.js` | state.segments（只读），DOM，API 调用 |
| `pronunciation.js` | state + MediaRecorder + Azure API |

---

### Phase 3 — 拆核心模块（最后做）

| 模块 | 复杂度 |
|---|---|
| `subtitles.js` | 与播放器高度耦合，需先稳定接口 |
| `player-core.js` | 依赖最多，最后处理 |
| `playback-modes.js` | 依赖 player-core，随核心一起拆 |

---

## 四、开发规则（写入 CLAUDE.md）

### 规则 1：初始化代码必须在文件末尾

`player.js` 中禁止在文件中段插入顶层执行语句。所有启动调用集中在文件最后的 `// ========== 启动初始化 ==========` 区块内。

违反示例（禁止）：
```js
const foo = "bar";
doSomething();           // ← 禁止：在中间调用函数
const baz = new Baz();
```

正确示例：
```js
const foo = "bar";
const baz = new Baz();
// ... 所有声明
// ========== 启动初始化 ==========
doSomething();           // ← 在最底部
```

### 规则 2：新功能独立领域 → 直接建模块文件

不往 `player.js` 主体继续堆代码。新的独立功能（如"每日复习"、"词汇本"）直接创建 `modules/xxx.js`。

### 规则 3：共享状态只通过 `state.js`

不新增全局变量（`window.xxx` 或文件顶层 `let/const` 用于跨模块通信）。

### 规则 4：单模块文件不超过 600 行

超过 600 行视为信号：该模块职责过多，需要再拆分。

---

## 五、何时启动 Phase 1

当满足以下任一条件时：
- `player.js` 超过 **5500 行**
- 某次修改 favorites / export / TTS 功能时发现需要理解超过 500 行上下文
- 出现第三次因为文件结构导致的崩溃

触发后，按"触机而动"原则：**改哪里，拆哪里**，不做整体重构。

---

## 六、当前功能领域分布（供拆分参考）

| 功能领域 | 大致行范围 | Phase |
|---|---|---|
| i18n 初始化 | 顶部 | 已独立 |
| DOM 元素获取 | 1–140 | 保留在 player.js |
| 收藏播放单例 | 141–145 | Phase 1 → favorites.js |
| 播放控制核心 | 160–600 | Phase 3 → player-core.js |
| 字幕渲染 | 600–900 | Phase 3 → subtitles.js |
| 影子跟读/发音 | 900–1300 | Phase 2 → pronunciation.js |
| 句子列表 | 1300–1500 | Phase 2 → sentence-list.js |
| TTS 面板 | 1500–1900 | Phase 2 → tts.js |
| 课程 DB | 1900–2100 | Phase 1 → lesson-db.js |
| 视频加载 | 2100–2400 | Phase 2 → video-loader.js |
| 收藏句子 | 2400–2600 | Phase 1 → favorites.js |
| 导出功能 | 2600–2800 | Phase 1 → export.js |
| 音频工具函数 | 2800–4839 | Phase 3 |
