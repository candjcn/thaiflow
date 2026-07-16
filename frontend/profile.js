/* profile.js — 账户页数据加载与渲染 */

// ── 常量 ────────────────────────────────────────────────────────
const CAP_LABEL = {
    transcription:  "视频识别",
    tts_synthesis:  "课程生成",
    pronunciation:  "发音评分",
    translation:    "字幕翻译",
    export:         "视频导出",
    romanize:       "罗马拼音",
    word_definition:"单词解释",
    ocr:            "图片识别",
};

const CAP_ICON = {
    transcription:  "🎙",
    tts_synthesis:  "🔊",
    pronunciation:  "📊",
    translation:    "🌐",
    export:         "📤",
    romanize:       "🔤",
    word_definition:"📖",
    ocr:            "🔍",
};

// ── 工具函数 ─────────────────────────────────────────────────────
function relativeTime(dateStr) {
    if (!dateStr) return "";
    const diff = Date.now() - new Date(dateStr + (dateStr.includes("T") ? "" : "Z")).getTime();
    const min  = Math.floor(diff / 60000);
    const hr   = Math.floor(diff / 3600000);
    const day  = Math.floor(diff / 86400000);
    if (min < 1)  return "刚刚";
    if (min < 60) return `${min} 分钟前`;
    if (hr  < 24) return `${hr} 小时前`;
    if (day < 7)  return `${day} 天前`;
    return new Date(dateStr + (dateStr.includes("T") ? "" : "Z")).toLocaleDateString("zh-CN");
}

function daysUntil(dateStr) {
    if (!dateStr) return null;
    const diff = new Date(dateStr + (dateStr.includes("T") ? "" : "Z")).getTime() - Date.now();
    return Math.ceil(diff / 86400000);
}

function formatDate(dateStr) {
    if (!dateStr) return "";
    return new Date(dateStr + (dateStr.includes("T") ? "" : "Z")).toLocaleDateString("zh-CN", {
        month: "short", day: "numeric"
    });
}

// ── 渲染：用户 Hero ──────────────────────────────────────────────
function renderUserHero(user, plan) {
    const planLabels = { free: "Free", plus: "Plus", pro: "Pro", enterprise: "Enterprise" };
    const planClass  = { free: "plan-free", plus: "plan-plus", pro: "plan-pro" };
    const label = planLabels[plan] || plan;
    const cls   = planClass[plan]  || "plan-free";

    const avatarHTML = user.picture_url
        ? `<img class="user-avatar" src="${user.picture_url}" alt="${user.name}" onerror="this.style.display='none';this.nextElementSibling.style.display='flex'">
           <div class="user-avatar-placeholder" style="display:none;">${(user.name || "?")[0].toUpperCase()}</div>`
        : `<div class="user-avatar-placeholder">${(user.name || "?")[0].toUpperCase()}</div>`;

    document.getElementById("userHero").innerHTML = `
        ${avatarHTML}
        <div class="user-info">
            <div class="user-name">${user.name || "用户"}</div>
            <div class="user-email">${user.email || ""}</div>
        </div>
        <span class="plan-badge ${cls}">${label}</span>
    `;
}

// ── 渲染：Credits ────────────────────────────────────────────────
function renderCredits(wallet) {
    const { balance, subscription_expires_at } = wallet;
    const total = balance.total || 0;

    // 总额
    document.getElementById("creditsTotal").innerHTML = `
        <div>
            <div class="credits-total-label">可用总额</div>
        </div>
        <div>
            <span class="credits-total-value">${total.toLocaleString()}</span>
            <span class="credits-total-unit">Credits</span>
        </div>
    `;

    // 三张卡片
    const giftRow    = wallet._gift_expires_at || null;
    const giftDays   = daysUntil(giftRow);
    const giftSoon   = giftDays !== null && giftDays <= 3;
    const giftExpiry = giftRow
        ? `<div class="credit-expiry ${giftSoon ? "soon" : ""}">${giftDays > 0 ? `${giftDays} 天后到期` : "即将到期"}</div>`
        : "";

    const subDays    = daysUntil(subscription_expires_at);
    const subExpiry  = subscription_expires_at && subDays !== null
        ? `<div class="credit-expiry">${subDays > 0 ? formatDate(subscription_expires_at) + " 到期" : "已到期"}</div>`
        : "";

    document.getElementById("creditsGrid").innerHTML = `
        <div class="credit-card gift">
            <div class="credit-icon">🎁</div>
            <div class="credit-amount">${(balance.gift || 0).toLocaleString()}</div>
            <div class="credit-label">赠送</div>
            ${giftExpiry}
        </div>
        <div class="credit-card sub">
            <div class="credit-icon">⭐</div>
            <div class="credit-amount">${(balance.subscription || 0).toLocaleString()}</div>
            <div class="credit-label">订阅</div>
            ${subExpiry}
        </div>
        <div class="credit-card paid">
            <div class="credit-icon">💳</div>
            <div class="credit-amount">${(balance.paid || 0).toLocaleString()}</div>
            <div class="credit-label">付费</div>
        </div>
    `;
}

// ── 渲染：今日限额 ───────────────────────────────────────────────
function renderRateLimits(data) {
    const limits = data.rate_limits || {};
    const caps   = ["transcription", "tts_synthesis", "pronunciation"];

    const html = caps.map(cap => {
        const info = limits[cap];
        if (!info) return "";
        const { used, limit } = info;
        const pct   = limit > 0 ? Math.round((used / limit) * 100) : 0;
        const full  = used >= limit;
        const empty = used === 0;
        const fillClass = full ? "full" : empty ? "empty" : "";

        return `
        <div class="rate-item">
            <div class="rate-row">
                <div class="rate-cap">
                    <div class="rate-cap-icon">${CAP_ICON[cap] || "•"}</div>
                    ${CAP_LABEL[cap] || cap}
                </div>
                <div class="rate-count">${used} / ${limit} 次</div>
            </div>
            <div class="rate-bar-bg">
                <div class="rate-bar-fill ${fillClass}" style="width:${pct}%"></div>
            </div>
        </div>`;
    }).join("");

    document.getElementById("rateList").innerHTML = html || "<div style='color:#636366;font-size:14px;padding:12px 0;'>无限额数据</div>";
}

// ── 渲染：使用记录 ───────────────────────────────────────────────
function renderHistory(history) {
    if (!history || history.length === 0) {
        document.getElementById("historyList").innerHTML = `
            <div class="empty-history">暂无使用记录</div>
        `;
        return;
    }

    const html = history.map(item => {
        const cap     = item.capability || "";
        const label   = CAP_LABEL[cap]  || cap;
        const icon    = CAP_ICON[cap]   || "•";
        const credits = item.credits_charged || 0;
        const status  = item.status || "success";
        const time    = relativeTime(item.requested_at);
        const statusLabel = { success: "成功", failed: "失败", refunded: "已退款", timeout: "超时" }[status] || status;

        return `
        <div class="history-item">
            <div class="history-cap-icon">${icon}</div>
            <div class="history-main">
                <div class="history-cap-name">${label}</div>
                <div class="history-time">${time}</div>
            </div>
            <div class="history-right">
                <div class="history-credits ${credits > 0 ? "nonzero" : ""}">
                    ${credits > 0 ? "−" + credits : "0"} C
                </div>
                <div class="history-status ${status}">${statusLabel}</div>
            </div>
        </div>`;
    }).join("");

    document.getElementById("historyList").innerHTML = html;
}

// ── 主流程 ───────────────────────────────────────────────────────
async function loadProfile() {
    // 并发拉三个接口
    const [meRes, walletRes, rateRes, usageRes] = await Promise.all([
        fetch("/api/auth/me"),
        fetch("/api/user/wallet"),
        fetch("/api/user/rate-limits"),
        fetch("/api/user/usage?limit=20"),
    ]);

    const [me, wallet, rate, usage] = await Promise.all([
        meRes.json(), walletRes.json(), rateRes.json(), usageRes.json(),
    ]);

    // 未登录 → 跳回主页
    if (!me.logged_in) {
        location.href = "/app";
        return;
    }

    // 拿 gift_expires_at（wallet API 没有直接返回，从 wallet 里补充）
    // 暂时挂在 wallet 对象上，渲染时使用
    wallet._gift_expires_at = wallet.gift_expires_at || null;

    renderUserHero(me, wallet.plan || "free");
    renderCredits(wallet);
    renderRateLimits(rate);
    renderHistory(usage.history || []);
}

// ── 偏好设置 ────────────────────────────────────────────────────
function initSettings() {
    const uiLangSel      = document.getElementById("settingUiLang");
    const translateSel   = document.getElementById("settingTranslateLang");
    const exportDirInput = document.getElementById("settingExportDir");
    const exportSaved    = document.getElementById("exportDirSaved");

    // 读取已保存的值
    uiLangSel.value    = localStorage.getItem("ui-lang")          || "zh-CN";
    translateSel.value = localStorage.getItem("translate-lang")   || "";
    exportDirInput.value = localStorage.getItem("default-export-dir") || "";

    // 界面语言：切换后立即生效（当前页面 + 写入 localStorage）
    uiLangSel.addEventListener("change", () => {
        const lang = uiLangSel.value;
        localStorage.setItem("ui-lang", lang);
        I18N.setLang(lang);
    });

    // 翻译语言：即存即生效
    translateSel.addEventListener("change", () => {
        const val = translateSel.value;
        if (val) {
            localStorage.setItem("translate-lang", val);
        } else {
            localStorage.removeItem("translate-lang");
        }
    });

    // 默认保存路径：失去焦点时保存，显示「已保存」提示
    exportDirInput.addEventListener("blur", () => {
        const val = exportDirInput.value.trim();
        if (val) {
            localStorage.setItem("default-export-dir", val);
        } else {
            localStorage.removeItem("default-export-dir");
        }
        exportSaved.classList.add("show");
        setTimeout(() => exportSaved.classList.remove("show"), 1500);
    });
    exportDirInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") exportDirInput.blur();
    });
}

// ── 登出 ────────────────────────────────────────────────────────
document.getElementById("logoutBtn").addEventListener("click", async () => {
    await fetch("/api/auth/logout", { method: "POST" });
    location.href = "/app";
});

// ── Init ─────────────────────────────────────────────────────────
I18N.init();
initSettings();
loadProfile().catch(err => {
    console.error("profile load error:", err);
});
