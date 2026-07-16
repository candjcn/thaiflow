# ReelSpeak — 开发路线图
**版本**: v1.1 | **最后更新**: 2026-07-16

> 路线图记录产品阶段和实施顺序。**阶段顺序已锁定，不得随意调整。**
> 技术架构决策见 ARCHITECTURE.md。开发规范见 DEVELOPMENT_GOVERNANCE.md。

---

## 当前状态（已完成）✅

**产品功能**：
- 本地视频 / TikTok / YouTube 链接导入
- Groq Whisper + Azure Speech 语音识别（含 Combined 模式）
- DeepSeek / Gemini 翻译（含自动 Fallback）
- 逐句复读、三遍字幕模式（盲听→原文→双语）
- 影子跟读 + Azure 发音评分
- TTS 课程生成（Gemini / Azure / 有道子曰）
- 拼音 / 泰语罗马音
- SRT 导出 + 带字幕视频导出
- Cloudflare R2 音频存储
- 多语种界面（zh-CN / zh-TW / en / ja / ko / th）

**工程基础**：
- Railway 线上部署（https://reelspeak.517lang.com）
- P0 配置治理（config/ 统一入口）
- P1 AI 层重构（ai/ 按能力划分）
- P2 领域模型（domain/ 纯数据）
- Landing Page

---

## 第一阶段：已完成 ✅

部署上线，手机端可用，收集早期用户反馈。

---

## 第二阶段：用户体验打磨

**目标**：让产品好用到用户愿意付费。

- 用户系统（注册 / 登录，手机号或微信）
- 每个用户独立的学习记录和字幕库
- 手机端 UX 深度优化（手势、布局、PWA）
- 学习记录持久化（跟读得分历史、学习进度）
- 生词本（点词查词 + 收藏）
- 难句标记与集中复习

**数据库**：此阶段引入 PostgreSQL（用户数据需要持久化）。

---

## 第三阶段：商业化（当前设计阶段）

**目标**：完整的 AI Commerce Platform 上线，验证商业模式。

分两个子阶段：

### 子阶段 3A：Commerce Platform 基础设施

按以下顺序实施，每个 Phase 独立可测，完成后平台可正常运行：

```
Phase 0   数据基础
  ├─ Task 0.1  DB Schema（commerce.db + schema.sql）
  ├─ Task 0.2  Identity 模块（create_user, get_user_plan, anonymous）
  └─ Task 0.3  Seed 初始数据（plan_definitions, provider_costs, pricing_policies）

Phase 1   核心计费链
  ├─ Task 1.1  Wallet 模块（Reserve/Confirm/Release/Add/Refund，乐观锁）
  ├─ Task 1.2  Pricing Engine（Estimate，基于 capability + pricing_policy）
  └─ Task 1.3  Usage Log v2（结构化记录，替代 JSONL log_event，双写过渡）

Phase 2   路由与权限
  ├─ Task 2.1  Permission Engine（check/grant/revoke，plan→permissions 映射）
  └─ Task 2.2  AI Router（静态路由表 + Fallback Chain，兼容 preferred_provider）

Phase 3   API 集成
  ├─ Task 3.0  CommerceContext 中间件（编排完整调用链）
  ├─ Task 3.1  /api/transcribe 接入
  ├─ Task 3.2  /api/translate 接入
  ├─ Task 3.3  /api/tts-generate 接入
  ├─ Task 3.4  /api/pronounce 接入
  └─ Task 3.5  其余端点接入（retranscribe / word-define / romanize / ocr / export）

Phase 4   运营工具
  ├─ Task 4.1  Admin API（/api/admin/commerce/*）
  └─ Task 4.2  用户余额 API（/api/user/wallet, /api/user/usage）

Phase 5   生产加固
  ├─ Task 5.1  对账机制（Usage Log vs Wallet 每日核对）
  ├─ Task 5.2  Free 套餐 Rate Limiter（日调用上限）
  └─ Task 5.3  月末 Credits 重置 Cron
```

**注意**：Phase 0-5 全程不实现支付，不实现用户登录 UI。过渡期 `user_id = "anonymous"`。

### 子阶段 3B：支付接入

Commerce Platform 稳定后：

- 微信支付 / 支付宝（国内用户）
- Stripe（海外用户）
- 订单系统、会员状态管理
- 到期提醒、自动续费

---

## 第四阶段：扩展

**目标**：多语种、多平台、内容生态。

**多语种**：日语（日剧/动漫）→ 韩语 → 英语 → 西班牙语 / 法语

**多平台**：
- 微信小程序（覆盖微信生态）
- iOS / Android App（WebView 包装 或 原生）
- Chrome 插件（在 YouTube / TikTok 直接启动）

**内容生态**：
- 精选课程体系（按难度分级）
- 用户 UGC（分享学习视频）
- 老师入驻

**技术升级**（本阶段才触发）：
- 前端框架化（Vue.js 或 React）——**当前和商业化阶段严格禁止**
- 后端微服务化
- PostgreSQL + Redis 缓存
- CDN 全球加速

---

## 技术栈演进路线

| 阶段 | 前端 | 后端 | 数据库 | 部署 |
|------|------|------|--------|------|
| 当前 | 原生 HTML/CSS/JS | Flask | JSON + SQLite（Commerce）| Railway |
| 商业化阶段 | 原生 + Commerce UI | Flask | SQLite → PostgreSQL | Railway |
| 扩展阶段 | Vue.js 或 React | Flask / FastAPI | PostgreSQL + Redis | VPS 集群 |
| 大规模 | 多端 | 微服务 | PostgreSQL + Redis | K8s |

---

## 暂缓功能（有价值但不在当前路线）

### 双语音频课（Bilingual Audio Lesson）

灵感：泰语 + 中文交替音频，类似 Pimsleur / ThaiPod101 双语播客，无需看字幕即可理解。

**已做的预留**：`SubtitleFile.type` 字段已加入，默认 `"standard"`，新类型写 `"bilingual_audio"`，向后兼容。

**触发条件**：TTS 课程有稳定用户群 + 收到明确的"纯听学习"需求反馈后重启。

### AI Router Health Check 动态路由

当前 AI Router 为静态路由表。Health Check（后台 ping Provider，动态调整优先级）已设计，但属于优化而非必须。

**触发条件**：某 Provider 频繁出现故障导致用户投诉时引入。

---

## 风险备忘

| 风险 | 缓解 |
|------|------|
| 版权：下载/分发视频 | 用户自行提供链接，平台不存储分发原始视频 |
| API 成本失控 | Free 套餐 Rate Limiter + 每日成本告警 |
| Provider 大规模故障 | Fallback Chain + Wallet.Release（失败时自动退款）|
| Credits 估算偏差积累 | Cost Engine 监控偏差，定期优化估算参数 |
