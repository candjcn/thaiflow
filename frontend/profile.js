/* profile.js — 账户页数据加载与渲染 */

// ── 常量 ────────────────────────────────────────────────────────
const CAP_LABEL_KEY = {
    transcription:  "cap.transcription",
    tts_synthesis:  "cap.tts_synthesis",
    pronunciation:  "cap.pronunciation",
    translation:    "cap.translation",
    export:         "cap.export",
    romanize:       "cap.romanize",
    word_definition:"cap.word_definition",
    ocr:            "cap.ocr",
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
    if (min < 1)  return I18N.t("time.justNow");
    if (min < 60) return I18N.t("time.minutesAgo", { n: min });
    if (hr  < 24) return I18N.t("time.hoursAgo",   { n: hr  });
    if (day < 7)  return I18N.t("time.daysAgo",    { n: day });
    const locale = { "zh-CN": "zh-CN", "zh-TW": "zh-TW", "ja": "ja-JP", "ko": "ko-KR", "th": "th-TH", "en": "en-US" }[I18N.currentLang] || "en-US";
    return new Date(dateStr + (dateStr.includes("T") ? "" : "Z")).toLocaleDateString(locale);
}

function daysUntil(dateStr) {
    if (!dateStr) return null;
    const diff = new Date(dateStr + (dateStr.includes("T") ? "" : "Z")).getTime() - Date.now();
    return Math.ceil(diff / 86400000);
}

function formatDate(dateStr) {
    if (!dateStr) return "";
    const locale = { "zh-CN": "zh-CN", "zh-TW": "zh-TW", "ja": "ja-JP", "ko": "ko-KR", "th": "th-TH", "en": "en-US" }[I18N.currentLang] || "en-US";
    return new Date(dateStr + (dateStr.includes("T") ? "" : "Z")).toLocaleDateString(locale, {
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
            <div class="user-name">${user.name || I18N.t("profile.navTitle")}</div>
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
            <div class="credits-total-label">${I18N.t("profile.creditsTotal")}</div>
            <a href="/usage" class="credits-history-link">${I18N.t("profile.viewHistory")} →</a>
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
        ? `<div class="credit-expiry ${giftSoon ? "soon" : ""}">${giftDays > 0 ? I18N.t("profile.daysLeft", { n: giftDays }) : I18N.t("profile.expired")}</div>`
        : "";

    const subDays    = daysUntil(subscription_expires_at);
    const subExpiry  = subscription_expires_at && subDays !== null
        ? `<div class="credit-expiry">${subDays > 0 ? I18N.t("profile.expiresOn", { date: formatDate(subscription_expires_at) }) : I18N.t("profile.expired")}</div>`
        : "";

    document.getElementById("creditsGrid").innerHTML = `
        <div class="credit-card gift">
            <div class="credit-icon">🎁</div>
            <div class="credit-amount">${(balance.gift || 0).toLocaleString()}</div>
            <div class="credit-label">${I18N.t("profile.gift")}</div>
            ${giftExpiry}
        </div>
        <div class="credit-card sub">
            <div class="credit-icon">⭐</div>
            <div class="credit-amount">${(balance.subscription || 0).toLocaleString()}</div>
            <div class="credit-label">${I18N.t("profile.subscription")}</div>
            ${subExpiry}
        </div>
        <div class="credit-card paid">
            <div class="credit-icon">💳</div>
            <div class="credit-amount">${(balance.paid || 0).toLocaleString()}</div>
            <div class="credit-label">${I18N.t("profile.paid")}</div>
        </div>
    `;
}

// ── 渲染：今日使用 ───────────────────────────────────────────────
function renderRateLimits(data) {
    const limits = data.rate_limits || {};
    const caps   = ["transcription", "tts_synthesis"];

    const html = caps.map(cap => {
        const info = limits[cap];
        if (!info) return `<div class="rate-item"></div>`;
        const { used, limit } = info;
        // limit=null 表示该套餐无限制，只显示次数不显示进度条
        const hasLimit  = limit !== null && limit !== undefined;
        const pct       = hasLimit && limit > 0 ? Math.round((used / limit) * 100) : 0;
        const full      = hasLimit && used >= limit;
        const empty     = used === 0;
        const fillClass = full ? "full" : empty ? "empty" : "";
        const countStr  = hasLimit ? `${used} / ${limit}` : `${used}`;

        return `
        <div class="rate-item">
            <div class="rate-cap" style="margin-bottom:12px;">
                <div class="rate-cap-icon">${CAP_ICON[cap] || "•"}</div>
                ${I18N.t(CAP_LABEL_KEY[cap] || cap)}
            </div>
            <div class="rate-count" style="margin-bottom:8px;">${countStr}</div>
            ${hasLimit ? `<div class="rate-bar-bg">
                <div class="rate-bar-fill ${fillClass}" style="width:${pct}%"></div>
            </div>` : ""}
        </div>`;
    }).join("");

    document.getElementById("rateList").innerHTML = html || `<div style='color:#636366;font-size:14px;padding:12px 0;'>${I18N.t("profile.noLimits")}</div>`;
}

// ── 渲染：使用记录 ───────────────────────────────────────────────
const HISTORY_PREVIEW = 5;   // 默认显示条数

function renderHistoryItem(item) {
    const cap     = item.capability || "";
    const label   = I18N.t(CAP_LABEL_KEY[cap] || cap);
    const icon    = CAP_ICON[cap]   || "•";
    const credits = item.credits_charged || 0;
    const status  = item.status || "success";
    const time    = relativeTime(item.requested_at);
    const statusLabel = {
        success:  I18N.t("profile.statusSuccess"),
        failed:   I18N.t("profile.statusFailed"),
        refunded: I18N.t("profile.statusRefunded"),
        timeout:  I18N.t("profile.statusTimeout"),
    }[status] || status;

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
}

function renderHistory(history) {
    const container = document.getElementById("historyList");
    if (!history || history.length === 0) {
        container.innerHTML = `<div class="empty-history">${I18N.t("profile.noHistory")}</div>`;
        return;
    }

    const preview  = history.slice(0, HISTORY_PREVIEW);
    const rest     = history.slice(HISTORY_PREVIEW);
    const hasMore  = rest.length > 0;

    let html = preview.map(renderHistoryItem).join("");

    if (hasMore) {
        html += `<div id="historyMore" style="display:none;">${rest.map(renderHistoryItem).join("")}</div>`;
        html += `<button id="historyToggle" class="history-toggle-btn">
            ${I18N.t("profile.historyShowMore", { n: rest.length })}
        </button>`;
    }

    container.innerHTML = html;

    if (hasMore) {
        document.getElementById("historyToggle").addEventListener("click", function () {
            const moreEl = document.getElementById("historyMore");
            const expanded = moreEl.style.display !== "none";
            moreEl.style.display = expanded ? "none" : "block";
            this.textContent = expanded
                ? I18N.t("profile.historyShowMore", { n: rest.length })
                : I18N.t("profile.historyShowLess");
        });
    }
}

// ── 主流程 ───────────────────────────────────────────────────────
async function loadProfile() {
    // 并发拉三个接口
    const [meRes, walletRes, rateRes] = await Promise.all([
        fetch("/api/auth/me"),
        fetch("/api/user/wallet"),
        fetch("/api/user/rate-limits"),
    ]);

    const [me, wallet, rate] = await Promise.all([
        meRes.json(), walletRes.json(), rateRes.json(),
    ]);

    // 未登录 → 跳回主页
    if (!me.logged_in) {
        location.href = "/app";
        return;
    }

    // 拿 gift_expires_at（wallet API 没有直接返回，从 wallet 里补充）
    // 暂时挂在 wallet 对象上，渲染时使用
    wallet._gift_expires_at = wallet.gift_expires_at || null;

    // 缓存数据，供语言切换时重渲染
    window._profileData = { me, wallet, rate };

    renderUserHero(me, wallet.plan || "free");
    renderCredits(wallet);
    renderRateLimits(rate);

    // 邀请统计
    loadReferralCard().catch(err => console.warn("[referral]", err));
}

// ── 偏好设置 ────────────────────────────────────────────────────

let _dirModalCurrentPath = "";
let _profileRecognitionModeListenerBound = false;

function getStoredRecognitionMode() {
    return localStorage.getItem("recognition-mode") || "balanced";
}

function setStoredRecognitionMode(value) {
    localStorage.setItem("recognition-mode", value);
}

function syncProfileRecognitionModeDescription(selectEl, descEl) {
    if (!selectEl || !descEl) return;
    const selected = selectEl.selectedOptions && selectEl.selectedOptions[0];
    descEl.textContent = (selected && selected.dataset && selected.dataset.description) || "";
}

function renderProfileRecognitionModes(selectEl, modes) {
    if (!selectEl) return;
    const saved = getStoredRecognitionMode();
    const nextValue = Array.isArray(modes) && modes.some(mode => mode.key === saved)
        ? saved
        : (modes && modes[0] && modes[0].key) || "balanced";

    selectEl.innerHTML = "";
    (modes || []).forEach(mode => {
        const opt = document.createElement("option");
        opt.value = mode.key;
        opt.textContent = mode.label;
        opt.dataset.description = mode.description || "";
        selectEl.appendChild(opt);
    });
    selectEl.value = nextValue;
    setStoredRecognitionMode(nextValue);
}

async function browseTo(path) {
    const res  = await fetch(`/api/browse-dir?path=${encodeURIComponent(path)}`);
    const data = await res.json();
    _dirModalCurrentPath = data.current;

    document.getElementById("dirModalCurrent").textContent = data.current;
    const list = document.getElementById("dirModalList");
    list.innerHTML = "";

    // 返回上级
    if (data.parent) {
        const up = document.createElement("div");
        up.className = "dir-modal-item up";
        up.innerHTML = `<span>⬆️</span><span>上级目录</span>`;
        up.addEventListener("click", () => browseTo(data.parent));
        list.appendChild(up);
    }

    if (data.dirs.length === 0) {
        const empty = document.createElement("div");
        empty.style.cssText = "padding:16px;color:#636366;font-size:13px;text-align:center;";
        empty.textContent = "没有子目录";
        list.appendChild(empty);
    } else {
        data.dirs.forEach(name => {
            const item = document.createElement("div");
            item.className = "dir-modal-item";
            item.innerHTML = `<span>📁</span><span>${name}</span>`;
            item.addEventListener("click", () => browseTo(data.current + "/" + name));
            list.appendChild(item);
        });
    }
}

function openDirModal(startPath) {
    document.getElementById("dirModalOverlay").classList.add("open");
    browseTo(startPath);
}

function closeDirModal() {
    document.getElementById("dirModalOverlay").classList.remove("open");
}

function saveExportDir(path) {
    localStorage.setItem("default-export-dir", path);
    document.getElementById("dirDisplayPath").textContent = path;
    const saved = document.getElementById("exportDirSaved");
    saved.classList.add("show");
    setTimeout(() => saved.classList.remove("show"), 1500);
}

function initSettings() {
    const uiLangSel    = document.getElementById("settingUiLang");
    const translateSel = document.getElementById("settingTranslateLang");
    const recognitionModeSel = document.getElementById("profileRecognitionMode");
    const recognitionModeDesc = document.getElementById("profileRecognitionModeDesc");

    // ── 界面语言 ──
    uiLangSel.value = localStorage.getItem("ui-lang") || "zh-CN";
    uiLangSel.addEventListener("change", () => {
        I18N.setLang(uiLangSel.value);
        document.title = I18N.t("profile.navTitle") + " — ReelSpeak";
        // 重渲染动态区块（Credits / RateLimits 用了 I18N.t()）
        if (window._profileData) {
            const { me, wallet, rate } = window._profileData;
            renderUserHero(me, wallet.plan || "free");
            renderCredits(wallet);
            renderRateLimits(rate);
        }
    });

    // ── 翻译语言 ──
    translateSel.value = localStorage.getItem("translate-lang") || "";
    translateSel.addEventListener("change", () => {
        const val = translateSel.value;
        val ? localStorage.setItem("translate-lang", val)
            : localStorage.removeItem("translate-lang");
    });

    // ── 识别模式（高级设置） ──
    if (recognitionModeSel) {
        const savedMode = getStoredRecognitionMode();
        recognitionModeSel.value = savedMode;
        syncProfileRecognitionModeDescription(recognitionModeSel, recognitionModeDesc);

        if (!_profileRecognitionModeListenerBound) {
            recognitionModeSel.addEventListener("change", () => {
                setStoredRecognitionMode(recognitionModeSel.value);
                syncProfileRecognitionModeDescription(recognitionModeSel, recognitionModeDesc);
            });
            _profileRecognitionModeListenerBound = true;
        }

        fetch("/api/recognition-modes")
            .then(r => r.ok ? r.json() : null)
            .then(data => {
                if (!data || !Array.isArray(data.modes) || !data.modes.length) return;
                renderProfileRecognitionModes(recognitionModeSel, data.modes);
                syncProfileRecognitionModeDescription(recognitionModeSel, recognitionModeDesc);
            })
            .catch(() => {});
    }

    // ── 默认保存路径 ──
    const savedDir = localStorage.getItem("default-export-dir");
    if (savedDir) {
        document.getElementById("dirDisplayPath").textContent = savedDir;
    } else {
        // 首次：读取服务端 Downloads 真实路径作为默认值
        fetch("/api/browse-dir?path=~/Downloads")
            .then(r => r.json())
            .then(data => {
                document.getElementById("dirDisplayPath").textContent = data.current;
                localStorage.setItem("default-export-dir", data.current);
            })
            .catch(() => {});
    }

    // 选择文件夹按钮
    document.getElementById("dirPickBtn").addEventListener("click", () => {
        const cur = localStorage.getItem("default-export-dir") || "~/Downloads";
        openDirModal(cur);
    });

    // Modal 关闭 / 取消
    document.getElementById("dirModalClose").addEventListener("click",  closeDirModal);
    document.getElementById("dirModalCancel").addEventListener("click", closeDirModal);
    document.getElementById("dirModalOverlay").addEventListener("click", (e) => {
        if (e.target === document.getElementById("dirModalOverlay")) closeDirModal();
    });

    // 确认选择
    document.getElementById("dirModalConfirm").addEventListener("click", () => {
        saveExportDir(_dirModalCurrentPath);
        closeDirModal();
    });
}

// ── 返回按钮：用 history.back() 触发 bfcache 还原，避免重新加载时出现登录按钮闪烁 ──
const _backBtn = document.querySelector(".back-btn");
if (_backBtn) {
    _backBtn.addEventListener("click", (e) => {
        e.preventDefault();
        // 有前驱历史记录则回退（player 页面从 bfcache 还原，保持登录态）
        // 否则直接跳 /app（防止直接访问 /profile 时回退到不相关页面）
        if (history.length > 1 && document.referrer.includes(location.host)) {
            history.back();
        } else {
            location.href = "/app";
        }
    });
}

// ── 登出 ────────────────────────────────────────────────────────
document.getElementById("logoutBtn").addEventListener("click", async () => {
    await fetch("/api/auth/logout", { method: "POST" });
    location.href = "/app";
});

// ── 邀请返利卡片 ─────────────────────────────────────────────────
async function loadReferralCard() {
    const input   = document.getElementById("referralLinkInput");
    const copyBtn = document.getElementById("referralCopyBtn");
    const statInv = document.getElementById("refStatInvited");
    const statAct = document.getElementById("refStatActivated");
    const statCred= document.getElementById("refStatCredits");

    let refUrl = "";

    try {
        const [codeRes, statsRes] = await Promise.all([
            fetch("/api/user/ref-code"),
            fetch("/api/user/referrals"),
        ]);

        if (!codeRes.ok || !statsRes.ok) throw new Error("api error");

        const { code } = await codeRes.json();
        const stats    = await statsRes.json();
        refUrl = `${location.origin}/app?ref=${code}`;

        if (input)    { input.value = refUrl; input.removeAttribute("placeholder"); }
        if (copyBtn)  copyBtn.removeAttribute("disabled");
        if (statInv)  statInv.textContent  = stats.total_invited   ?? 0;
        if (statAct)  statAct.textContent  = stats.total_activated ?? 0;
        if (statCred) statCred.textContent = stats.credits_earned  ?? 0;
    } catch (_) {
        if (input) input.placeholder = "—";
        if (statInv)  statInv.textContent  = "—";
        if (statAct)  statAct.textContent  = "—";
        if (statCred) statCred.textContent = "—";
    }

    if (copyBtn && refUrl) {
        copyBtn.addEventListener("click", async () => {
            try {
                await navigator.clipboard.writeText(refUrl);
            } catch (_) {
                if (input) { input.select(); document.execCommand("copy"); }
            }
            copyBtn.textContent = I18N.t("profile.referral.copied");
            copyBtn.classList.add("copied");
            setTimeout(() => {
                copyBtn.textContent = I18N.t("profile.referral.copy");
                copyBtn.classList.remove("copied");
            }, 2000);
        });
    }
}

// ── Init ─────────────────────────────────────────────────────────
I18N.init();
document.title = I18N.t("profile.navTitle") + " — ReelSpeak";
initSettings();
loadProfile().catch(err => {
    console.error("profile load error:", err);
});
