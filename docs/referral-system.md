# ReelSpeak — 邀请返利系统规划

> 创建时间：2026-07-17  
> 状态：待实施

---

## 一、产品设计

### 1.1 用户入口

用户在 **Profile 页**看到自己的专属邀请链接，一键复制：

```
https://reelspeak.517lang.com/app?ref=ABC12345
```

邀请码是根据用户 ID 派生的 8 位字母数字码（base62 哈希），固定不变，不需要单独生成和存储。

---

### 1.2 注册奖励

| 对象 | 奖励 | 触发条件 |
|------|------|---------|
| 邀请人（Referrer） | +300 Credits | 被邀请人首次使用任意 AI 功能 |
| 被邀请人（Referred） | +100 Credits | 同上 |

**触发定义：**  
被邀请人完成注册后，首次调用以下任意 AI 能力视为"有效激活"：
- 语音识别（transcription）
- TTS 课程生成（tts_content / tts_generate）
- 发音评分（pronunciation）

激活时机而非注册时机才发奖励，防止批量刷号。

---

### 1.3 购买返利

被邀请人每次**充值积分（Credits）**，邀请人获得充值金额的 **20%** 积分回扣。

示例：
- 被邀请人充值 1000 Credits → 邀请人得 200 Credits
- 被邀请人充值 5000 Credits → 邀请人得 1000 Credits

**规则：**
- 返利仅适用于直接充值，不适用于赠送积分或系统奖励
- 返利无上限，永久有效（只要邀请关系存在）
- 被邀请人的购买行为不影响被邀请人自己的积分

---

### 1.4 防滥用规则

| 规则 | 说明 |
|------|------|
| 激活门槛 | 注册后首次使用 AI 功能才触发奖励，不能注册即得 |
| 自我邀请 | 检测同设备 / 同邮箱，禁止用自己的邀请码注册 |
| 邀请关系唯一 | 每个被邀请人只能绑定一个邀请人（先到先得，注册时写入） |
| 邀请码有效性 | 注册时校验邀请码是否对应有效用户，无效则忽略（不报错） |

---

## 二、技术实现

### 2.1 数据库

新增 `referrals` 表（在 `commerce.db` 中）：

```sql
CREATE TABLE referrals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    referrer_id     TEXT NOT NULL,          -- 邀请人 user_id
    referred_id     TEXT NOT NULL UNIQUE,   -- 被邀请人 user_id（唯一，一人只能有一个邀请人）
    ref_code        TEXT NOT NULL,          -- 使用的邀请码
    status          TEXT NOT NULL DEFAULT 'pending',
                                            -- pending | activated | (future: churned)
    created_at      TEXT NOT NULL,          -- 被邀请人注册时间
    activated_at    TEXT,                   -- 首次 AI 使用时间（激活时间）
    referrer_rewarded INTEGER NOT NULL DEFAULT 0,  -- 邀请人注册奖励是否已发
    referred_rewarded INTEGER NOT NULL DEFAULT 0,  -- 被邀请人注册奖励是否已发
    FOREIGN KEY (referrer_id) REFERENCES users(id),
    FOREIGN KEY (referred_id) REFERENCES users(id)
);

CREATE INDEX idx_referrals_referrer ON referrals(referrer_id);
CREATE INDEX idx_referrals_ref_code ON referrals(ref_code);
```

购买返利不需要单独的表，在现有 `usage_log` 或支付记录里挂钩即可。

---

### 2.2 邀请码生成

邀请码从 user_id 派生，无需存储：

```python
import hashlib, base64, re

def get_ref_code(user_id: str) -> str:
    """从 user_id 生成固定 8 位邀请码（base62 字符集）"""
    digest = hashlib.sha256(f"ref:{user_id}:reelspeak".encode()).digest()
    b64 = base64.b64encode(digest).decode()
    code = re.sub(r'[^A-Za-z0-9]', '', b64)[:8].upper()
    return code
```

反查邀请码 → 用户：`SELECT user_id FROM users WHERE ref_code = ?`  
（users 表加一个虚拟列，或注册时写入 `ref_code` 字段）

---

### 2.3 前端流程

**步骤 1：访客点击邀请链接**
```
/app?ref=ABC12345
```
前端在 `player.js` 启动时读取 `?ref=` 参数存入 `localStorage`：
```javascript
const ref = new URLSearchParams(location.search).get("ref");
if (ref) localStorage.setItem("pending-ref", ref);
```

**步骤 2：用户完成 Google 登录**  
OAuth 回调时，后端从 session / cookie 取到 `pending-ref`，前端登录成功后把它发给后端。

具体做法：登录成功后调 `/api/auth/bind-referral`：
```javascript
const pendingRef = localStorage.getItem("pending-ref");
if (pendingRef) {
    await fetch("/api/auth/bind-referral", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ref_code: pendingRef })
    });
    localStorage.removeItem("pending-ref");
}
```

**步骤 3：Profile 页展示邀请链接**
```javascript
const refCode = await fetch("/api/user/ref-code").then(r => r.json());
const refUrl = `${location.origin}/app?ref=${refCode.code}`;
```

---

### 2.4 后端接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/auth/bind-referral` | 注册后绑定邀请人（幂等，只生效一次） |
| GET  | `/api/user/ref-code` | 获取当前用户的邀请码 |
| GET  | `/api/user/referrals` | 获取邀请记录列表（已邀请人数、已激活数、获得积分） |

---

### 2.5 激活触发点

在 `app.py` 的 AI 能力 API 中，调用成功后检查是否需要激活邀请奖励：

```python
def try_activate_referral(referred_id: str):
    """首次 AI 使用时激活邀请关系，发放双方注册奖励"""
    ref = db.get_pending_referral(referred_id)
    if not ref:
        return
    # 发放奖励
    wallet.credit(ref["referrer_id"], 300, source="referral_register")
    wallet.credit(referred_id,        100, source="referral_welcome")
    db.activate_referral(ref["id"])
```

在 `transcription`、`tts_generate`、`pronunciation` 三个端点的成功路径末尾调用此函数。

---

### 2.6 购买返利触发点

在积分充值结算（`settle_purchase`）时，检查买家是否有邀请人：

```python
def settle_purchase(user_id: str, credits_purchased: int):
    # ... 正常发放积分 ...
    
    # 检查邀请返利
    referrer_id = db.get_referrer(user_id)
    if referrer_id:
        cashback = int(credits_purchased * 0.20)
        wallet.credit(referrer_id, cashback, source="referral_cashback")
        # 记录到 usage_log 方便查账
```

---

## 三、Profile 页 UI

在设置区块下方新增"邀请好友"卡片：

```
┌─────────────────────────────────────────┐
│  邀请好友，共同获益                          │
│                                         │
│  好友通过你的链接注册后首次使用 AI 功能：         │
│  • 你获得 300 Credits                    │
│  • 好友获得 100 Credits 欢迎礼             │
│  • 好友每次充值，你额外获得 20% 积分回扣        │
│                                         │
│  你的专属链接：                             │
│  [https://reelspeak.517lang.com/app?... ]│
│                           [复制链接]      │
│                                         │
│  已邀请 3 人 · 已激活 2 人 · 共获 700 Credits│
└─────────────────────────────────────────┘
```

---

## 四、实施顺序

1. **数据库**：`referrals` 表 + users 表加 `ref_code` 字段
2. **后端基础**：邀请码生成、`bind-referral`、`ref-code` 接口
3. **前端链接捕获**：`?ref=` 参数 → localStorage → 登录后绑定
4. **激活逻辑**：三个 AI 端点加 `try_activate_referral()`
5. **购买返利**：结算流程加 `cashback` 逻辑
6. **Profile UI**：邀请卡片 + 统计数据

---

## 五、待定事项

- [ ] 邀请统计是否需要展示在 Admin 后台
- [ ] 是否有邀请上限（比如每个用户最多邀请 N 人获得奖励）
- [ ] 返利是否有时效（比如仅限被邀请人注册后 1 年内的购买）
