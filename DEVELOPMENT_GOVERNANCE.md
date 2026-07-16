# ReelSpeak — 开发治理文档
**版本**: v1.2 | **最后更新**: 2026-07-16
**变更说明**: v1.2 加入架构讨论定论（Commerce 调用链修订、SQLite 范围、测试策略、Blueprint、状态库）

> **每次实施前必须阅读本文件及 ARCHITECTURE.md。**
> 本文件回答 HOW（怎么做）。VISION.md 回答 WHY，ARCHITECTURE.md 回答 WHAT，ROADMAP.md 回答 WHEN。
> 与 CLAUDE.md 冲突时，以本文件为准（本文件是 CLAUDE.md 的超集）。

---

## 目录

1. [硬性约束（绝对禁止）](#1-硬性约束绝对禁止)
2. [配置与日志规范](#2-配置与日志规范)
3. [Commerce 模块开发规范](#3-commerce-模块开发规范)
4. [前端开发规范](#4-前端开发规范)
5. [代码质量规范](#5-代码质量规范)
6. [测试规范](#6-测试规范)
7. [部署与工作流](#7-部署与工作流)
8. [关键决策记录](#8-关键决策记录)
9. [架构讨论定论](#9-架构讨论定论)
10. [变更流程](#10-变更流程)

---

## 1. 硬性约束（绝对禁止）

以下约束一经确定不得违反，即使有充分理由也必须经过完整讨论后才能修改。

### 前端

| 禁止项 | 理由 |
|--------|------|
| 引入 React / Vue / Svelte 等框架 | 适配 2015 老 Mac，零构建复杂度；第四阶段扩展时才允许 |
| 引入 webpack / vite 等构建工具 | 同上 |
| 引入 Zustand / Redux 等状态库 | 违反框架约束；原生 state.js 已足够 |
| 全局 `let`/`const` 声明前的顶层执行语句 | 引发 TDZ 崩溃（已发生两次）|

### 后端

| 禁止项 | 理由 |
|--------|------|
| 在 `app.py` 路由函数中写业务逻辑 | 路由只做分发和序列化 |
| 直接调用 `os.getenv()` | 绕过 config/ 统一入口 |
| 在 ai/provider/ 以外的代码中直接 import Provider 并调用 | 绕过能力层抽象 |
| 引入 ORM | 违反设计克制原则 |
| 引入消息队列框架 | 同上 |
| 在 ai/ 或 domain/ 层中加入 Commerce 逻辑 | 违反层间调用规则 |

### Commerce 层

| 禁止项 | 理由 |
|--------|------|
| Billing 层感知具体 Provider（Groq/Azure 等）| 核心解耦原则 |
| `commerce/` 之外出现 `if VIP` 或 `if plan ==` | 权限必须经 Permission Engine |
| Wallet.Settle(actual_amount) 同步等待 Provider 返回 | 见第 9 节架构修订 |
| 为 video/subtitle JSON 文件引入 SQLite | 没有并发写入需求，迁移收益 < 成本 |

---

## 2. 配置与日志规范

### 配置（config 包是唯一入口）

```python
# 正确
from config import settings, providers, get_logger
api_key = providers.Groq.API_KEY
timeout = settings.TIMEOUT_GROQ

# 禁止
import os
key = os.getenv("GROQ_API_KEY")      # ← 禁止
BASE_URL = "https://api.groq.com"    # ← 禁止硬编码
```

### 日志

```python
# 正确
from config import get_logger
logger = get_logger(__name__)
logger.info("[TTS] 生成完成")
logger.warning("[翻译] DeepSeek 失败，降级到 Gemini")
logger.error(f"[Wallet] Reserve 失败: {e}")

# 禁止
print("处理完成")    # ← 绝对禁止，不得新增任何 print()
```

---

## 3. Commerce 模块开发规范

### 3.1 调用链顺序（不可颠倒，不可跳过）

完整顺序见 ARCHITECTURE.md §5.2。关键规则：

1. `Permission.check` 必须在 `Wallet.Reserve` 之前
2. `Wallet.Reserve` 必须在 `AI Router` 之前
3. `Wallet.Release` 必须在任何 Provider 失败路径上触发
4. `Usage Log.Record` 必须在 `Wallet.Confirm` 之前（先有记录，再确认消费）
5. **`Wallet.Confirm` 不重新计算 Credits**，直接使用 Reserve 时的 estimate

### 3.2 Provider 边界（Commerce 层不能越过）

```python
# commerce/ 代码中：
# 正确 — 路由选择
handle = router.route(capability="transcription", ...)

# 禁止 — 直接调用 Provider
from ai.provider import groq
groq.transcribe_file(path)    # ← Commerce 层禁止直接调 Provider
```

### 3.3 Credits 消费顺序（固定，不可改）

```
Subscription Credits → Gift Credits → Paid Credits
```

各自的过期规则：
- Subscription Credits：月末 UTC 00:00 清零
- Gift Credits：创建时指定 `expires_at`，默认 30 天
- Paid Credits：永不过期

### 3.4 乐观锁规范（Wallet）

`wallets` 表有 `version` 字段。所有修改余额的操作必须：

```sql
UPDATE wallets
SET subscription_credits = subscription_credits - ?,
    version = version + 1
WHERE wallet_id = ? AND version = ?
```

若 `rowcount == 0`（并发冲突），重试最多 3 次，仍失败抛出异常。

### 3.5 失败处理规范

```python
ctx = CommerceContext(...)
reservation_id = ctx.reserve(input_metadata)

try:
    result = call_provider(handle)
    ctx.record_usage(actual_units, latency_ms, status="success")
    ctx.confirm()
except Exception as e:
    ctx.release()            # ← 必须，否则 Credits 永久锁定
    ctx.record_usage(None, latency_ms, status="failed", error=str(e))
    raise
```

---

## 4. 前端开发规范

### 4.1 player.js TDZ 防护规则

**所有顶层执行语句必须在文件末尾。**

```js
// 文件中段：只允许声明
const foo = "bar";
let baz = null;

function doSomething() { ... }

// ========== 启动初始化（文件末尾，所有声明之后）==========
I18N.init();
loadVideoList();
renderFavorites();
```

### 4.2 模块化规则

- 拆出新模块前在 `frontend/modules/` 下新建文件
- 新模块通过 `import { state } from "./state.js"` 读写共享状态
- 新模块在 `player.js` 顶部 `import "./modules/xxx.js"` 引入
- 拆出后删除 `player.js` 中对应代码，保持等价行为

### 4.3 CSS 规范

- 全局 `button, select` 规则在 `style.css` 文件后部
- 组件规则加父类前缀（如 `.controls .ctrl-btn:hover`）
- 删除元素前先 `grep id` 检查 JS 引用（许多 id 藏在隐藏 div 里）

### 4.4 i18n 规范

新增任何 UI 文案，必须同步 `i18n.js` 全部 6 种语言：

```
zh-CN / zh-TW / en / ja / ko / th
```

---

## 5. 代码质量规范

### 5.1 只做被要求的事

- 不添加未被要求的 docstring、注释、类型注解
- Bug 修复不附带周边代码清理
- 简单功能不增加额外可配置性
- 不为假想的未来需求预留扩展点

### 5.2 安全规范

```python
# 防止命令注入：参数列表而非字符串拼接
subprocess.run(["ffmpeg", "-i", path, ...])         # 正确
subprocess.run(f"ffmpeg -i {path} ...")              # 禁止

# 防止路径穿越
root = os.path.realpath(VIDEOS_DIR)
target = os.path.realpath(os.path.join(VIDEOS_DIR, user_input))
if not target.startswith(root + os.sep):
    raise ValueError("非法路径")
```

### 5.3 错误响应规范

```python
# 正确：JSON 错误响应
return jsonify({"error": "缺少 video 参数"}), 400

# 禁止：让 Flask 返回 500 HTML
raise ValueError("缺少参数")    # ← 未捕获异常 → 500 HTML
```

---

## 6. 测试规范

### 6.1 分层策略

| 层级 | 工具 | 时机 | 覆盖范围 |
|------|------|------|---------|
| Commerce 单元测试 | **pytest（现在引入）** | 每个 Task 完成时 | Wallet 并发、Pricing 公式、Permission 映射、Router 选择 |
| API 集成测试 | curl | 接口改动后 | 本地起服务实测关键路径 |
| 语法检查 | ast.parse / node --check | 每次改动后 | Python / JS 文件 |
| 前端回归 | 手动 checklist | UI 改动后 | 浏览器 + 手机验收 |
| E2E 测试 | Playwright（延后）| 产品稳定后 | 完整用户流程 |

### 6.2 Commerce 模块必测用例

以下用例必须有 pytest 覆盖，否则不允许上线：

**Wallet**：
- `test_reserve_deducts_subscription_first` — 消费顺序正确
- `test_reserve_crosses_credit_types` — 跨类型消费
- `test_reserve_insufficient_raises` — 余额不足抛出异常
- `test_release_restores_balance` — 失败后余额完全恢复
- `test_concurrent_reserve_no_double_spend` — 并发不超发（乐观锁）

**Pricing Engine**：
- `test_pricing_policy_not_expose_provider` — 同 capability 不同 provider，Credits 相同
- `test_romanize_zh_is_free` — 中文拼音 = 0 Credits
- `test_estimate_never_less_than_calculate` — 估算值 ≥ 精确值（含 buffer）

**Permission Engine**：
- `test_free_user_cannot_tts` — 套餐限制生效
- `test_manual_grant_overrides_plan` — 手动授权优先级最高

### 6.3 为什么 pytest 现在就必须引入

Wallet 的乐观锁逻辑、Pricing 的 Credits 计算、Permission 的套餐映射——这些错误**静默发生**（账目错误没有崩溃，不跑并发测试无法发现）。手工测试或 curl 测试无法覆盖这些场景。

---

## 7. 部署与工作流

### 7.1 环境

| 环境 | 地址 | 触发方式 |
|------|------|---------|
| 线上正式 | https://reelspeak.517lang.com | push main 自动部署 |
| 线上备用 | https://thaiflow.up.railway.app | 同上 |
| 本地开发 | http://localhost:5000 | `python backend/app.py` |
| 手机局域网 | http://192.168.1.3:5000 | 手机连同一 WiFi |

**Git 仓库**：`candjcn/thaiflow`，`main` 分支即生产。

### 7.2 Claude 自动执行工作流（无需询问）

```
1. 改动完成
2. 语法检查：Python ast.parse / node --check
3. Commerce 模块改动 → 运行相关 pytest 用例
4. 后端接口改动 → 本地起服务 curl 实测
5. 检查通过 → commit + push origin main（触发 Railway 部署）
6. UI 改动无法自行视觉验证 → 明确告知用户需在浏览器/手机验收哪些点
```

### 7.3 环境变量清单

```
# AI API Keys
GROQ_API_KEY
OPENAI_API_KEY
AZURE_SPEECH_KEY
AZURE_SPEECH_REGION
DEEPSEEK_API_KEY
GEMINI_API_KEY
CF_AI_API_TOKEN

# 存储
R2_ACCOUNT_ID
R2_ACCESS_KEY_ID
R2_SECRET_ACCESS_KEY
R2_BUCKET_NAME
R2_PUBLIC_URL

# 应用
ADMIN_KEY                   # 管理员接口鉴权
YOUTUBE_COOKIES             # 可选，YouTube 反爬兜底

# 可选覆盖（有默认值）
GEMINI_MODEL                # 默认 gemini-3.1-flash-lite
GEMINI_TTS_MODEL            # 默认 gemini-3.1-flash-tts-preview
GEMINI_IMAGE_MODEL          # 默认 gemini-3.1-flash-lite-image
DEBUG                       # 1 = 开启详细日志
LOG_FILE                    # 写入日志文件路径
PORT                        # 默认 5000
DATABASE_URL                # 生产 PostgreSQL（Commerce Phase 0 起）
```

---

## 8. 关键决策记录

> 这些决策已做出并验证，**不得在没有明确用户指令的情况下推翻**。

### 产品 UX 决策

| 决策 | 内容 |
|------|------|
| 视频不持久化 | Railway 不挂 Volume；工作流以本地文件为主，识别完下载 JSON 到本地 |
| 原生全屏优先 | Android 系统提示无法去除，全屏效果 > 美观；HTTP 下降级 CSS 模拟 |
| 默认播放模式 | repeat=1（播一遍）；三遍复读/影子跟读是可取消的 toggle |
| 桌面纯键盘控制 | 空格/←→/R/↑↓/L/S/F/Esc；底部栏 60% 宽悬浮 |
| 首页服务器视频列表 | 识别失败的视频靠它重试；保留显示（曾移除后又恢复）|
| 界面语言自动检测 | zh-CN/zh-TW/ja/ko 有对应版本，其余默认英文 |
| 影子跟读切句不打断 | 左右滑切换时保持跟读状态继续按遍数朗读 |
| 跟读面板布局固定 | 按钮区不动，波形/评分向上扩展；无声录音不自动回放 |
| 手机端 UX 已确认 | 多次确认的手机端交互不得回退，改动前需明确说明范围 |

### Commerce 架构决策

| 决策 | 内容 |
|------|------|
| TTS 拆分为两个子能力 | content_gen（per_token）/ tts_synthesis（per_char），各记一条 Usage Log |
| Combined 转录计费 | 两次 Provider 调用，两条 Usage Log，Credits 合并预扣 |
| Romanize 分段计费 | 中文/pypinyin = 0 Credits；泰语/Gemini = Credits > 0 |
| SQLite 范围 | Commerce 数据必须用 SQLite；视频/字幕 JSON 不迁移 |
| Wallet 方法 | Reserve / Confirm / Release / Add / Refund（无 Settle(actual)）|

---

## 9. 架构讨论定论

本节记录经过讨论形成定论的架构决策，附理由。

### 9.1 Commerce 调用链修订（v1.1，2026-07-16）

**结论**：Wallet 使用 `Confirm` 而非 `Settle(actual_amount)`；Cost Engine 改为离线分析工具。

**原问题（旧设计 `Pricing.Calculate → Wallet.Settle`）**：

1. SSE 长流（/api/transcribe 跑 30 秒）内存在开放 billing 事务，连接异常时状态不一致
2. Fallback（Groq 超时 → Azure 接替）时，哪个 Provider 的 actual_units 用于计算？逻辑复杂
3. Provider Adapter 必须返回 `ActualUsage` 结构，增加每个 Provider 的实现负担

**新设计**：

```
调用前  → Wallet.Reserve(estimate)         Credits 在调用前预扣，用 estimate
Provider → 执行 AI 调用
Usage Log → record(actual_units, ...)      记录实际用量（秒/字符/Token）
Wallet   → Confirm(reservation_id)         仅标记 reserved→consumed，不重新计算

[离线]  Cost Engine 读 Usage Log
        → 计算真实 API 成本（运营分析用）
        → 偏差 > 20% 记录异常并优化估算参数
        → 不回写用户 Credits
```

**代价**：用户扣的是 estimate 而非精确值（偏差通常 < 15%）。当前阶段可接受；等 Credits 变成真实货币时，Cost Engine 可升级为同步计算，不影响其他模块。

### 9.2 SQLite vs JSON 范围划定（2026-07-16）

**结论**：

- **视频/字幕 JSON → 保持不变**。工作流以本地文件为主，无并发写入需求，迁移收益 < 成本。等真正有多用户同步需求时再评估。
- **Commerce 数据 → 必须用 SQLite**。`Wallet.Reserve` 需要乐观锁防并发双重扣款，JSON 文件无法做原子 read-modify-write。

### 9.3 Flask Blueprint 决策（2026-07-16）

**结论**：当前不引入 Blueprint。

Blueprint 是组织手段，不是边界手段。Commerce 接入后路由本身会变薄（逻辑全移到 `CommerceContext`），`app.py` 不会因为行数增加而变得难以维护。

**触发条件**：`app.py` 突破 2000 行 **且** 路由逻辑本身难以导航时引入，一步可达。

### 9.4 测试工具决策（2026-07-16）

**结论**：pytest 现在引入；Playwright 延后。

| 工具 | 决策 | 理由 |
|------|------|------|
| pytest | **现在引入** | Wallet 并发、Pricing 边界无法用手工测试验证，错误静默 |
| Playwright | **延后** | E2E 测试是后期工程化，产品稳定后引入 |

### 9.5 前端状态管理（2026-07-16）

**结论**：不引入 Zustand、Redux 等任何状态库。

理由：所有状态库需要 npm 构建链，直接违反"永远不引入前端框架和构建工具"的硬性约束。`frontend/modules/state.js` 的单一数据源模式用原生 ES Modules 实现，已覆盖当前和中期需求。

---

## 10. 变更流程

### 10.1 可以直接改（无需确认）

- Bug 修复（不改 API 契约）
- 样式调整（不改布局逻辑）
- 新增 i18n 词条（需同步全 6 语言）
- 修改 `provider_costs` 或 `pricing_policies` 数据
- 新增 Provider（遵循 Provider Adapter 协议，不影响 Billing 层）
- Commerce Phase 0-5 各 Task（已在任务列表中的实施内容）

### 10.2 需要用户确认后才改

- HTTP API 路径、参数名、响应格式
- 新增或移除套餐层级
- 调整路线图阶段顺序
- 引入新的第三方 Python 包
- 修改已有数据库字段（Schema 变更）
- 任何涉及手机端已确认 UX 的改动

### 10.3 永远不能改（需完整讨论后才能提议）

- 引入前端框架（第四阶段前）
- 引入 ORM
- 让 Billing 层感知具体 Provider
- 在 `commerce/` 之外出现 `if VIP` 或 `if plan ==` 判断
- 在 `ai/provider/` 或 `domain/` 中添加 Commerce 逻辑
- 用 `Wallet.Settle(actual)` 同步等待 Provider 返回（已被讨论否定）
