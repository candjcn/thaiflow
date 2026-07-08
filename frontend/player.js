const APP_REV = "20260708i"; // 与 index.html 的 ?v= 同步更新

// ========== i18n 初始化 ==========
I18N.init();
document.querySelectorAll(".lang-switcher-select").forEach(sel => {
    sel.addEventListener("change", () => {
        I18N.setLang(sel.value);
    });
});

// ========== 获取用户翻译目标语言 ==========
function getTargetLang() {
    // 跟随界面语言（右上角下拉切换），不再依赖浏览器上报语言
    const uiLang = I18N.currentLang || "zh-CN";
    if (uiLang === "zh-CN") return "中文";
    if (uiLang === "zh-TW") return "繁體中文";
    if (uiLang === "ja") return "日本語";
    if (uiLang === "ko") return "한국어";
    // 界面为英文时，按浏览器语言细分目标语言
    const lang = navigator.language || navigator.userLanguage || "en";
    if (lang.startsWith("zh")) {
        if (lang === "zh-TW" || lang === "zh-HK" || lang === "zh-Hant") {
            return "繁體中文";
        }
        return "中文";
    }
    // 常见语言映射
    const map = {
        "th": "ไทย",
        "en": "English",
        "ja": "日本語",
        "ko": "한국어",
        "fr": "Français",
        "de": "Deutsch",
        "es": "Español",
        "pt": "Português",
        "ru": "Русский",
        "it": "Italiano",
        "vi": "Tiếng Việt",
        "id": "Bahasa Indonesia",
        "ms": "Bahasa Melayu",
        "ar": "العربية",
        "hi": "हिन्दी",
    };
    const shortLang = lang.split("-")[0];
    return map[shortLang] || "English";
}

// ========== 状态 ==========
let segments = [];
let currentIndex = -1;
let repeatCount = 0;
let sentenceMode = false;
let language = "";
let currentVideoName = "";
let isLoading = false;

// ========== DOM 元素 ==========
const phaseSelect = document.getElementById("phaseSelect");
const phasePlay = document.getElementById("phasePlay");
const video = document.getElementById("videoPlayer");
const videoContainer = document.getElementById("videoContainer");
const videoListEl = document.getElementById("videoList");
const loadingOverlay = document.getElementById("loadingOverlay");
const loadingTip = document.getElementById("loadingTip");
const pauseIndicator = document.getElementById("pauseIndicator");
const sentenceList = document.getElementById("sentenceList");
const sentenceDrawer = document.getElementById("sentenceDrawer");
const btnPrev = document.getElementById("btnPrev");
const btnNext = document.getElementById("btnNext");
const btnPause = document.getElementById("btnPause");
const btnRepeat = document.getElementById("btnRepeat");
const btnBack = document.getElementById("btnBack");
const btnList = document.getElementById("btnList");
const btnFullscreen = document.getElementById("btnFullscreen");
const btnExport = document.getElementById("btnExport");
const btnCloseDrawer = document.getElementById("btnCloseDrawer");
const btnTranslate = document.getElementById("btnTranslate");
const repeatCountSelect = document.getElementById("repeatCount");
const playbackRateSelect = document.getElementById("playbackRate");
const chkOriginal = document.getElementById("chkOriginal");
const chkTranslation = document.getElementById("chkTranslation");
const subtitleOriginal = document.getElementById("subtitleOriginal");
const subtitleTranslation = document.getElementById("subtitleTranslation");
const repeatInfo = document.getElementById("repeatInfo");
const subtitleOverlay = document.getElementById("subtitleOverlay");
const transcribeProvider = document.getElementById("transcribeProvider");
const segmentTarget = document.getElementById("segmentTarget");
const exportOverlay = document.getElementById("exportOverlay");
const exportProgressBar = document.getElementById("exportProgressBar");
const exportPct = document.getElementById("exportPct");
const exportModal = document.getElementById("exportModal");
const exportDirInput = document.getElementById("exportDir");
const exportPrefixInput = document.getElementById("exportPrefix");
const exportHint = document.getElementById("exportHint");
const btnExportCancel = document.getElementById("btnExportCancel");
const btnExportConfirm = document.getElementById("btnExportConfirm");
const exportTypeSelect = document.getElementById("exportType");
const timeDisplay = document.getElementById("timeDisplay");
const btnFollowRead = document.getElementById("btnFollowRead");
const followReadPanel = document.getElementById("followReadPanel");
const frReference = document.getElementById("frReference");
const frTranslation = document.getElementById("frTranslation");
const btnFrClose = document.getElementById("btnFrClose");
const btnFrPlayOriginal = document.getElementById("btnFrPlayOriginal");
const btnFrRecord = document.getElementById("btnFrRecord");
const btnFrPlayback = document.getElementById("btnFrPlayback");
const btnFrScore = document.getElementById("btnFrScore");
const frTimer = document.getElementById("frTimer");
const frWaveform = document.getElementById("frWaveform");
const frOverlay = document.getElementById("frOverlay");
const frResult = document.getElementById("frResult");
const frScoreNum = document.getElementById("frScoreNum");
const frAccuracy = document.getElementById("frAccuracy");
const frFluency = document.getElementById("frFluency");
const frCompleteness = document.getElementById("frCompleteness");
const frWords = document.getElementById("frWords");
const videoUrlInput = document.getElementById("videoUrlInput");
const btnDownloadUrl = document.getElementById("btnDownloadUrl");
const urlStatus = document.getElementById("urlStatus");
const btnBrowseDir = document.getElementById("btnBrowseDir");
const dirBrowser = document.getElementById("dirBrowser");
const dirCurrent = document.getElementById("dirCurrent");
const dirList = document.getElementById("dirList");
const btnDirUp = document.getElementById("btnDirUp");
const btnDirSelect = document.getElementById("btnDirSelect");
const btnDirCancel = document.getElementById("btnDirCancel");

// ========== 初始化 ==========
loadVideoList();
// 注意：loadLocalVideoList() 的启动调用在文件末尾——
// 它依赖后面声明的 const（LESSON_DB 等），在这里调用会踩 TDZ
// 页面版本标识（排查缓存问题用）
(() => {
    const rev = document.createElement("div");
    rev.style.cssText = "text-align:center;font-size:10px;color:#333;padding:8px;";
    rev.textContent = "rev " + APP_REV;
    document.getElementById("videoListPanel").appendChild(rev);
})();

btnPrev.addEventListener("click", prevSentence);
btnNext.addEventListener("click", nextSentence);
btnPause.addEventListener("click", togglePause);
btnRepeat.addEventListener("click", repeatCurrent);
btnTranslate.addEventListener("click", translateAll);
btnBack.addEventListener("click", backToSelect);
btnList.addEventListener("click", toggleDrawer);
btnFullscreen.addEventListener("click", toggleFullscreen);
btnExport.addEventListener("click", showExportModal);
btnExportCancel.addEventListener("click", () => {
    exportModal.style.display = "none";
    dirBrowser.style.display = "none";
});
btnExportConfirm.addEventListener("click", doExport);
btnBrowseDir.addEventListener("click", () => openDirBrowser(exportDirInput.value || "~"));
btnDirUp.addEventListener("click", () => {
    const parent = btnDirUp.dataset.parent;
    if (parent) openDirBrowser(parent);
});
btnDirSelect.addEventListener("click", () => {
    exportDirInput.value = dirCurrent.textContent;
    dirBrowser.style.display = "none";
    updateExportHint();
});
btnDirCancel.addEventListener("click", () => { dirBrowser.style.display = "none"; });
btnFollowRead.addEventListener("click", openFollowRead);
document.getElementById("btnSaveLocal").addEventListener("click", () => saveToLocal(false, true, "all"));
btnDownloadUrl.addEventListener("click", downloadFromUrl);
document.getElementById("localFiles").addEventListener("change", openLocalFiles);
btnFrClose.addEventListener("click", closeFollowRead);
btnFrPlayOriginal.addEventListener("click", toggleShadowRead);
btnFrRecord.addEventListener("click", toggleRecording);
btnFrPlayback.addEventListener("click", playbackRecording);
btnFrScore.addEventListener("click", submitForScoring);
btnCloseDrawer.addEventListener("click", () => {
    sentenceDrawer.style.display = "none";
});

// 句子列表：下载字幕到本地（JSON + SRT）
document.getElementById("btnDrawerSave").addEventListener("click", () => {
    saveToLocal(true, true, "all"); // 用户点击保存：JSON + 两个 SRT + 封面
});

playbackRateSelect.addEventListener("change", () => {
    video.playbackRate = parseFloat(playbackRateSelect.value);
});

chkOriginal.addEventListener("change", updateSubtitleVisibility);
chkTranslation.addEventListener("change", updateSubtitleVisibility);

// ========== 移动端控件 ==========
const mobileControls = document.getElementById("mobileControls");
const btnModeStudy = document.getElementById("btnModeStudy");
const btnModeFollow = document.getElementById("btnModeFollow");
const mModeBg = document.getElementById("mModeBg");
const mBtnPause = document.getElementById("mBtnPause");
const mBtnList = document.getElementById("mBtnList");
const mRepeatInfo = document.getElementById("mRepeatInfo");
const mBtnBack = document.getElementById("mBtnBack");
const mBtnFullscreen = document.getElementById("mBtnFullscreen");
const mTopStatus = document.getElementById("mTopStatus");
const mTopStatusSentence = document.getElementById("mTopStatusSentence");
const mTopStatusRepeat = document.getElementById("mTopStatusRepeat");
const mOverlayControls = document.getElementById("mOverlayControls");
const mCenterPlayBtn = document.getElementById("mCenterPlayBtn");
const mOvPrev = document.getElementById("mOvPrev");
const mOvNext = document.getElementById("mOvNext");
const mSpeedBtn = document.getElementById("mSpeedBtn");
const mRepeatBtn = document.getElementById("mRepeatBtn");
const mSpeedPicker = document.getElementById("mSpeedPicker");
const mRepeatPicker = document.getElementById("mRepeatPicker");

mBtnList.addEventListener("click", toggleDrawer);

// 返回按钮
mBtnBack.addEventListener("click", () => {
    backToSelect();
});

// 全屏按钮
function isNativeFullscreen() {
    return !!(document.fullscreenElement || document.webkitFullscreenElement);
}

function isCssFullscreen() {
    return phasePlay.classList.contains("css-fullscreen");
}

function enterFullscreen() {
    const el = document.documentElement;
    if (el.requestFullscreen) {
        el.requestFullscreen({ navigationUI: "hide" }).then(() => {
            console.log("[Fullscreen] native OK");
        }).catch((e) => {
            console.log("[Fullscreen] native failed:", e.message);
        });
    } else if (el.webkitRequestFullscreen) {
        el.webkitRequestFullscreen();
    }
    // CSS 后备（原生全屏不可用时）
    setTimeout(() => {
        if (!isNativeFullscreen()) {
            phasePlay.classList.add("css-fullscreen");
            mBtnFullscreen.classList.add("is-fullscreen");
        }
    }, 400);
}

function exitFullscreen() {
    if (isNativeFullscreen()) {
        if (document.exitFullscreen) {
            document.exitFullscreen().catch(() => {});
        } else if (document.webkitExitFullscreen) {
            document.webkitExitFullscreen();
        }
    }
    phasePlay.classList.remove("css-fullscreen");
    mBtnFullscreen.classList.remove("is-fullscreen");
}

mBtnFullscreen.addEventListener("click", () => {
    if (isNativeFullscreen() || isCssFullscreen()) {
        exitFullscreen();
    } else {
        enterFullscreen();
    }
});

// 同步全屏按钮图标状态（原生全屏事件）
document.addEventListener("fullscreenchange", () => {
    mBtnFullscreen.classList.toggle("is-fullscreen", isNativeFullscreen());
});
document.addEventListener("webkitfullscreenchange", () => {
    mBtnFullscreen.classList.toggle("is-fullscreen", isNativeFullscreen());
});

/// Overlay controls: play/pause, prev, next
mCenterPlayBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    if (followReadPanel.style.display !== "none") {
        toggleShadowRead();
    } else {
        togglePause();
    }
});
mOvPrev.addEventListener("click", (e) => {
    e.stopPropagation();
    prevSentence();
});
mOvNext.addEventListener("click", (e) => {
    e.stopPropagation();
    nextSentence();
});

// Speed picker
mSpeedBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    mRepeatPicker.style.display = "none";
    mSpeedPicker.style.display = mSpeedPicker.style.display === "none" ? "flex" : "none";
});

mSpeedPicker.querySelectorAll(".m-picker-opt").forEach(opt => {
    opt.addEventListener("click", () => {
        const speed = parseFloat(opt.dataset.speed);
        video.playbackRate = speed;
        playbackRateSelect.value = String(speed);
        mSpeedBtn.textContent = opt.textContent;
        mSpeedPicker.querySelectorAll(".m-picker-opt").forEach(o => o.classList.remove("active"));
        opt.classList.add("active");
        // Also sync desktop speed buttons if they exist
        document.querySelectorAll(".speed-btn").forEach(b => {
            b.classList.toggle("active", parseFloat(b.dataset.speed) === speed);
        });
        mSpeedPicker.style.display = "none";
    });
});

// Repeat count picker
mRepeatBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    mSpeedPicker.style.display = "none";
    mRepeatPicker.style.display = mRepeatPicker.style.display === "none" ? "flex" : "none";
});

mRepeatPicker.querySelectorAll(".m-picker-opt").forEach(opt => {
    opt.addEventListener("click", () => {
        const val = opt.dataset.repeat;
        repeatCountSelect.value = val;
        // Update button label
        if (val === "9999") {
            mRepeatBtn.textContent = "\u221E";
        } else {
            mRepeatBtn.textContent = val + t("ctrl.repeat.unit");
        }
        mRepeatPicker.querySelectorAll(".m-picker-opt").forEach(o => o.classList.remove("active"));
        opt.classList.add("active");
        mRepeatPicker.style.display = "none";
        // Re-trigger repeat info update
        updateRepeatInfo(parseInt(repeatCountSelect.value) || 3);
    });
});

// Close pickers when tapping elsewhere
document.addEventListener("click", (e) => {
    if (!mSpeedBtn.contains(e.target) && !mSpeedPicker.contains(e.target)) {
        mSpeedPicker.style.display = "none";
    }
    if (!mRepeatBtn.contains(e.target) && !mRepeatPicker.contains(e.target)) {
        mRepeatPicker.style.display = "none";
    }
});

// 模式切换：三遍复读 / 影子跟读（再次点击取消回到默认）
btnModeStudy.addEventListener("click", () => {
    switchMode(btnModeStudy.classList.contains("active") ? "normal" : "study");
});
btnModeFollow.addEventListener("click", () => {
    switchMode(btnModeFollow.classList.contains("active") ? "normal" : "follow");
});

// 桌面模式 tabs（与移动端 tabs 状态同步）
const dModeStudy = document.getElementById("dModeStudy");
const dModeFollow = document.getElementById("dModeFollow");
dModeStudy.addEventListener("click", () => {
    switchMode(dModeStudy.classList.contains("active") ? "normal" : "study");
});
dModeFollow.addEventListener("click", () => {
    switchMode(dModeFollow.classList.contains("active") ? "normal" : "follow");
});

function switchMode(mode) {
    [btnModeStudy, btnModeFollow, dModeStudy, dModeFollow].forEach(b => b.classList.remove("active"));
    mModeBg.dataset.pos = "";
    if (mode === "normal") {
        // 默认模式：从头到尾播放一遍，不重复
        repeatCountSelect.value = "1";
        mRepeatBtn.textContent = "1" + t("ctrl.repeat.unit");
        mRepeatPicker.querySelectorAll(".m-picker-opt").forEach(o => {
            o.classList.toggle("active", o.dataset.repeat === "1");
        });
        // 关闭跟读面板
        if (followReadPanel.style.display !== "none") {
            followReadPanel.style.display = "none";
        }
        mobileControls.classList.remove("follow-mode");
    } else if (mode === "study") {
        btnModeStudy.classList.add("active");
        dModeStudy.classList.add("active");
        mModeBg.dataset.pos = "0";
        repeatCountSelect.value = "3";
        // Sync mobile repeat button
        mRepeatBtn.textContent = "3" + t("ctrl.repeat.unit");
        mRepeatPicker.querySelectorAll(".m-picker-opt").forEach(o => {
            o.classList.toggle("active", o.dataset.repeat === "3");
        });
        // 关闭跟读面板
        if (followReadPanel.style.display !== "none") {
            followReadPanel.style.display = "none";
        }
        mobileControls.classList.remove("follow-mode");
        if (currentIndex >= 0) {
            jumpToSentence(currentIndex);
            video.play();
        }
    } else if (mode === "follow") {
        btnModeFollow.classList.add("active");
        dModeFollow.classList.add("active");
        mModeBg.dataset.pos = "1";
        openFollowRead();
    }
}

// 移动端/平板判断
function isMobile() {
    return window.innerWidth <= 1024 || "ontouchstart" in window;
}

// 进入播放界面时自动全屏（移动端）
function tryMobileFullscreen() {
    if (!isMobile()) return;
    enterFullscreen();
}

// 移动端浮动控制层逻辑
let mOverlayTimer = null;
let mOverlaysInitialized = false;

function showMobileOverlays() {
    if (!isMobile()) return;
    // 更新播放/暂停状态
    syncOverlayPlayState();
    // 显示控制层（带入场动画）
    mOverlayControls.classList.remove("fading");
    mOverlayControls.classList.add("visible");
    // 播放中时 3 秒后自动隐藏
    resetOverlayTimer();
}

function syncOverlayPlayState() {
    mCenterPlayBtn.classList.remove("paused", "playing", "ended");
    if (video.paused) {
        mCenterPlayBtn.classList.add("paused");
    } else {
        mCenterPlayBtn.classList.add("playing");
    }
}

function resetOverlayTimer() {
    clearTimeout(mOverlayTimer);
    if (!video.paused) {
        mOverlayTimer = setTimeout(() => {
            mOverlayControls.classList.add("fading");
            setTimeout(() => {
                mOverlayControls.classList.remove("visible", "fading");
            }, 400);
        }, 3000);
    }
}

function hideMobileOverlays() {
    mOverlayControls.classList.remove("visible", "fading");
    clearTimeout(mOverlayTimer);
}

function initMobileOverlays() {
    if (mOverlaysInitialized) return;
    mOverlaysInitialized = true;
    showMobileOverlays();
}

// 同步移动端状态
video.addEventListener("play", () => {
    mBtnPause.textContent = "\u23F8";
    if (isMobile()) {
        syncOverlayPlayState();
        resetOverlayTimer();
    }
});
video.addEventListener("pause", () => {
    if (!isLoading) {
        mBtnPause.textContent = "\u25B6";
        if (isMobile()) {
            syncOverlayPlayState();
            // 暂停时显示控制层且不自动隐藏
            mOverlayControls.classList.add("visible");
            mOverlayControls.classList.remove("fading");
            clearTimeout(mOverlayTimer);
        }
    }
});

// 视频自然播放到末尾（timeupdate 可能没触发最后一句结束的判断）
video.addEventListener("ended", () => {
    if (isLoading || segments.length === 0) return;

    const maxRepeat = parseInt(repeatCountSelect.value) || 3;

    // 还在句子模式且不是最后一句：跳到下一句继续
    if (sentenceMode && currentIndex >= 0 && currentIndex < segments.length - 1) {
        repeatCount++;
        if (repeatCount < maxRepeat) {
            // 当前句还没复读够遍数，重播当前句
            video.currentTime = segments[currentIndex].start;
            video.play();
        } else {
            jumpToSentence(currentIndex + 1);
            video.play();
        }
        updateRepeatInfo(maxRepeat);
        return;
    }

    // 最后一句：检查复读遍数是否播够
    if (sentenceMode && currentIndex === segments.length - 1) {
        repeatCount++;
        updateRepeatInfo(maxRepeat);
        if (repeatCount < maxRepeat) {
            // 遍数未满，重播最后一句
            video.currentTime = segments[currentIndex].start;
            video.play();
            return;
        }
    }

    // 所有句子、所有遍数都播完：自动从第一句重新开始（无限循环）
    if (sentenceMode && segments.length > 0) {
        jumpToSentence(0);
        video.play();
    }
});

// 滑动手势：左右滑动切换句子
let touchStartX = 0;
let touchStartY = 0;
videoContainer.addEventListener("touchstart", (e) => {
    touchStartX = e.touches[0].clientX;
    touchStartY = e.touches[0].clientY;
}, { passive: true });
videoContainer.addEventListener("touchend", (e) => {
    const dx = e.changedTouches[0].clientX - touchStartX;
    const dy = e.changedTouches[0].clientY - touchStartY;
    // 水平滑动距离 > 50px 且大于垂直滑动
    if (Math.abs(dx) > 50 && Math.abs(dx) > Math.abs(dy) * 1.5) {
        if (dx > 0) prevSentence();
        else nextSentence();
        // Show overlay briefly after swipe
        showMobileOverlays();
    }
});

video.addEventListener("timeupdate", () => {
    onTimeUpdate();
    updateTimeDisplay();
});

// 点击视频区域暂停/播放
videoContainer.addEventListener("click", (e) => {
    if (isLoading) return;
    if (e.target.closest(".subtitle-overlay")) return;
    if (e.target.closest(".m-top-btn")) return;
    if (e.target.closest(".m-ov-btn")) return;
    if (isMobile()) {
        // 保底：还没进入全屏时，借用这次点击手势进入全屏
        if (!isNativeFullscreen() && !isCssFullscreen()) {
            enterFullscreen();
        }
        // 跟读面板打开时，点击视频同步影子跟读
        if (followReadPanel.style.display !== "none") {
            toggleShadowRead();
        } else {
            togglePause();
        }
        showMobileOverlays();
        return;
    }
    togglePause();
});

// 键盘快捷键（桌面键盘优先操作）
const SPEED_STEPS = [0.5, 0.75, 1, 1.25, 1.5];

function stepSpeed(dir) {
    const cur = parseFloat(playbackRateSelect.value);
    const i = SPEED_STEPS.indexOf(cur);
    const next = SPEED_STEPS[Math.min(SPEED_STEPS.length - 1, Math.max(0, i + dir))];
    playbackRateSelect.value = String(next);
    video.playbackRate = next;
    // 同步移动端速度按钮
    if (mSpeedBtn) mSpeedBtn.textContent = next + "x";
}

// 按键 → 对应按钮闪光反馈（键盘与界面联动）
function flashKeyButton(code) {
    const btn = document.querySelector(`.ctrl-btn[data-key="${code}"]`);
    if (!btn) return;
    btn.classList.add("kbd-flash");
    setTimeout(() => btn.classList.remove("kbd-flash"), 200);
}

document.addEventListener("keydown", (e) => {
    if (phasePlay.style.display === "none") return;
    if (e.target.tagName === "SELECT" || e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;

    switch (e.code) {
        case "Space":
            e.preventDefault();
            togglePause();
            flashKeyButton("Space");
            break;
        case "ArrowLeft":
            e.preventDefault();
            prevSentence();
            flashKeyButton("ArrowLeft");
            break;
        case "ArrowRight":
            e.preventDefault();
            nextSentence();
            flashKeyButton("ArrowRight");
            break;
        case "ArrowUp":
            e.preventDefault();
            stepSpeed(1);
            break;
        case "ArrowDown":
            e.preventDefault();
            stepSpeed(-1);
            break;
        case "KeyR":
            e.preventDefault();
            repeatCurrent();
            flashKeyButton("KeyR");
            break;
        case "KeyL":
            e.preventDefault();
            toggleDrawer();
            flashKeyButton("KeyL");
            break;
        case "KeyS":
            e.preventDefault();
            switchMode(followReadPanel.style.display === "none" ? "follow" : "normal");
            break;
        case "Enter":
            // 跟读面板打开时：按住 Enter 录音，松开停止
            if (followReadPanel.style.display !== "none") {
                e.preventDefault();
                if (!e.repeat && !frIsRecording) {
                    frEnterHold = true;
                    toggleRecording();
                }
            }
            break;
        case "KeyF":
            e.preventDefault();
            toggleFullscreen();
            flashKeyButton("KeyF");
            break;
        case "Escape":
            // 原生全屏时 Esc 由浏览器处理退出全屏；非全屏时返回选择页
            if (!isNativeFullscreen()) {
                if (isCssFullscreen()) {
                    exitFullscreen();
                } else {
                    backToSelect();
                }
                flashKeyButton("Escape");
            }
            break;
    }
});

// 松开 Enter 停止录音（长按录音模式）
let frEnterHold = false;
document.addEventListener("keyup", (e) => {
    if (e.code === "Enter" && frEnterHold) {
        frEnterHold = false;
        if (frIsRecording) stopRecording();
    }
});


// 同步暂停按钮图标（SVG 切换）
video.addEventListener("play", () => { btnPause.classList.add("playing"); });
video.addEventListener("pause", () => {
    if (!isLoading) btnPause.classList.remove("playing");
});

// 字幕宽度跟随视频实际渲染宽度；纯音频课程跟随封面图宽度
function updateSubtitleWidth() {
    const containerRect = videoContainer.getBoundingClientRect();

    if (video.videoWidth > 0) {
        // 有视频画面：按视频渲染宽度
        const videoRect = video.getBoundingClientRect();
        const videoDisplayWidth = videoRect.width;
        subtitleOverlay.style.width = (videoDisplayWidth * 0.92) + "px";
        subtitleOverlay.style.top = ""; // 清理课程模式的残留定位
        // 确保字幕水平居中于视频而非容器
        const videoLeft = videoRect.left - containerRect.left;
        const videoCenter = videoLeft + videoDisplayWidth / 2;
        const containerCenter = containerRect.width / 2;
        const offset = videoCenter - containerCenter;
        subtitleOverlay.style.left = `calc(50% + ${offset}px)`;
        return;
    }

    // 纯音频课程：字幕卡放在封面下方的空白区（画归画，字归字），
    // 宽度为封面实际渲染宽度的 80%
    subtitleOverlay.style.left = "50%";
    const coverVisible = lessonCover.style.display !== "none" && lessonCover.naturalWidth > 0;
    if (coverVisible) {
        // object-fit: contain 的实际显示尺寸
        const scale = Math.min(
            containerRect.width / lessonCover.naturalWidth,
            containerRect.height / lessonCover.naturalHeight
        );
        const coverDisplayWidth = lessonCover.naturalWidth * scale;
        const coverDisplayHeight = lessonCover.naturalHeight * scale;
        subtitleOverlay.style.width = (coverDisplayWidth * 0.8) + "px";

        // 封面下边缘以下的空白区居中放字幕卡；空间不足时退到画面下部 72%
        const coverBottom = (containerRect.height + coverDisplayHeight) / 2;
        const spaceBelow = containerRect.height - coverBottom;
        if (spaceBelow >= 150) {
            subtitleOverlay.style.top = (coverBottom + spaceBelow / 2) + "px";
        } else {
            subtitleOverlay.style.top = (containerRect.height * 0.72) + "px";
        }
    } else {
        // 无封面：容器宽度的 80%，垂直居中
        subtitleOverlay.style.width = (containerRect.width * 0.8) + "px";
        subtitleOverlay.style.top = (containerRect.height * 0.5) + "px";
    }
}

video.addEventListener("loadedmetadata", () => {
    // 纯音频（朗读课程）：切换到"字幕为主角"的呈现模式
    videoContainer.classList.toggle("lesson-mode", video.videoWidth === 0);
    updateSubtitleWidth();
});
video.addEventListener("resize", updateSubtitleWidth);
window.addEventListener("resize", updateSubtitleWidth);
document.addEventListener("fullscreenchange", () => {
    setTimeout(updateSubtitleWidth, 100);
});

// ========== 暂停/播放 ==========
function togglePause() {
    if (isLoading) return;
    if (video.paused) {
        // 播放完毕后再次点击，从头开始
        if (!sentenceMode && segments.length > 0) {
            sentenceMode = true;
            jumpToSentence(0);
        }
        video.play();
        showPauseIcon("▶");
    } else {
        video.pause();
        showPauseIcon("⏸");
    }
}

function showPauseIcon(icon) {
    pauseIndicator.textContent = icon;
    pauseIndicator.className = "pause-indicator show";
    setTimeout(() => {
        pauseIndicator.className = "pause-indicator fade";
    }, 300);
    setTimeout(() => {
        pauseIndicator.className = "pause-indicator";
    }, 600);
}

// ========== 全屏 ==========
function toggleFullscreen() {
    if (isNativeFullscreen() || isCssFullscreen()) {
        exitFullscreen();
    } else {
        enterFullscreen();
    }
}

// ========== 加载进度步骤 ==========
function setStep(stepId, state) {
    const el = document.getElementById(stepId);
    el.className = "step " + state;
    const icon = el.querySelector(".step-icon");
    if (state === "active") icon.textContent = "⏳";
    else if (state === "done") icon.textContent = "✅";
    else if (state === "error") icon.textContent = "❌";
    else icon.textContent = "⏳";
}

function setTip(text) {
    loadingTip.textContent = text;
}

// ========== 视频列表 ==========
const myVideosSection = document.getElementById("myVideosSection");

async function loadVideoList() {
    try {
        const res = await fetch("/api/videos");
        const data = await res.json();
        videoListEl.innerHTML = "";

        if (data.videos.length === 0) {
            myVideosSection.style.display = "none";
            return;
        }

        myVideosSection.style.display = "block";

        // 已识别的视频排在前面
        const sorted = [...data.videos].sort((a, b) => {
            if (a.has_subtitle && !b.has_subtitle) return -1;
            if (!a.has_subtitle && b.has_subtitle) return 1;
            return 0;
        });

        sorted.forEach((v) => {
            const item = document.createElement("div");
            item.className = "video-item" + (v.has_subtitle ? " ready" : "");

            const info = document.createElement("div");
            info.className = "video-info";

            const name = document.createElement("div");
            name.className = "video-name";
            // 去掉 .mp4 后缀显示
            name.textContent = v.name.replace(/\.mp4$/i, "");

            const status = document.createElement("div");
            status.className = "video-status";
            status.textContent = v.has_subtitle ? t("status.ready") : t("status.notReady");

            info.appendChild(name);
            info.appendChild(status);

            const actions = document.createElement("div");
            actions.className = "video-actions";

            if (v.has_subtitle) {
                // 整个卡片可点击播放
                item.addEventListener("click", (e) => {
                    if (e.target.tagName === "BUTTON") return;
                    loadSaved(v.name);
                });
                item.style.cursor = "pointer";

                const btnRedo = document.createElement("button");
                btnRedo.textContent = t("status.redo");
                btnRedo.className = "btn-redo";
                btnRedo.addEventListener("click", (e) => {
                    e.stopPropagation();
                    startLoading(v.name);
                });
                actions.appendChild(btnRedo);
            } else {
                // 未识别/识别失败的视频：可点击重新识别
                const btnNew = document.createElement("button");
                btnNew.textContent = t("status.recognize");
                btnNew.className = "btn-new";
                btnNew.addEventListener("click", () => startLoading(v.name));
                actions.appendChild(btnNew);
            }

            item.appendChild(info);
            item.appendChild(actions);
            videoListEl.appendChild(item);
        });
    } catch (e) {
        console.error("加载视频列表失败:", e);
    }
}

// ========== 从 URL 下载视频 ==========
async function downloadFromUrl() {
    const url = videoUrlInput.value.trim();
    if (!url) {
        urlStatus.textContent = t("status.enterUrl");
        urlStatus.className = "url-status error";
        return;
    }

    btnDownloadUrl.disabled = true;
    btnDownloadUrl.textContent = t("status.downloading");
    urlStatus.textContent = t("status.fetchingInfo");
    urlStatus.className = "url-status";

    try {
        const res = await fetch("/api/download-video", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ url }),
        });

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let downloadedName = null;

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n");
            buffer = lines.pop();

            for (const line of lines) {
                if (!line.startsWith("data: ")) continue;
                const data = JSON.parse(line.slice(6));

                if (data.progress) {
                    urlStatus.textContent = data.progress;
                    urlStatus.className = "url-status";
                }
                if (data.done) {
                    downloadedName = data.name;
                    urlStatus.textContent = data.message + "：" + data.name;
                    urlStatus.className = "url-status success";
                }
                if (data.error) {
                    urlStatus.textContent = data.error;
                    urlStatus.className = "url-status error";
                }
            }
        }

        // 刷新视频列表
        await loadVideoList();

        // 下载成功后自动开始识别翻译
        if (downloadedName) {
            videoUrlInput.value = "";
            startLoading(downloadedName);
        }

    } catch (e) {
        urlStatus.textContent = t("status.downloadFail") + e.message;
        urlStatus.className = "url-status error";
    }

    btnDownloadUrl.disabled = false;
    btnDownloadUrl.textContent = t("app.add.url.btn");
}

// 回车键触发下载
videoUrlInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") downloadFromUrl();
});

// ========== 粘贴文本生成朗读课程 ==========
const ttsContent = document.getElementById("ttsContent");
const ttsStatus = document.getElementById("ttsStatus");
const btnTtsGenerate = document.getElementById("btnTtsGenerate");

document.getElementById("btnTtsToggle").addEventListener("click", () => {
    ttsContent.style.display = ttsContent.style.display === "none" ? "flex" : "none";
});

// 隐藏测试功能：文本框里直接粘贴图片 → 预览 + 转圈 → OCR 识别成文字
const ttsImgPreview = document.getElementById("ttsImgPreview");
const ttsImgThumb = document.getElementById("ttsImgThumb");
const ttsImgClose = document.getElementById("ttsImgClose");
let ttsImgAutoCloseTimer = null;

function closeTtsImgPreview() {
    clearTimeout(ttsImgAutoCloseTimer);
    ttsImgPreview.style.display = "none";
    ttsImgPreview.classList.remove("loading");
    if (ttsImgThumb.src.startsWith("blob:")) URL.revokeObjectURL(ttsImgThumb.src);
    ttsImgThumb.removeAttribute("src");
}

ttsImgClose.addEventListener("click", closeTtsImgPreview);

document.getElementById("ttsText").addEventListener("paste", async (e) => {
    const items = e.clipboardData && e.clipboardData.items;
    if (!items) return;
    const imgItem = Array.from(items).find(it => it.type.startsWith("image/"));
    if (!imgItem) return; // 纯文字粘贴走默认行为

    e.preventDefault();
    const blob = imgItem.getAsFile();

    // 1. 显示图片预览 + 转圈（识别中）
    closeTtsImgPreview();
    ttsImgThumb.src = URL.createObjectURL(blob);
    ttsImgPreview.style.display = "block";
    ttsImgPreview.classList.add("loading");
    ttsStatus.textContent = "识别图片文字中...";
    ttsStatus.className = "url-status";

    try {
        const formData = new FormData();
        formData.append("image", blob, "paste.png");
        formData.append("language", document.getElementById("ttsLang").value);
        const res = await fetch("/api/ocr", { method: "POST", body: formData });
        const data = await res.json();

        ttsImgPreview.classList.remove("loading");

        if (data.error) {
            ttsStatus.textContent = "图片识别失败: " + data.error;
            ttsStatus.className = "url-status error";
            return; // 保留预览，手动关闭
        }

        // 2. 识别结果填入文本框（已有文字则追加）
        const ta = document.getElementById("ttsText");
        ta.value = ta.value ? ta.value + "\n" + (data.text || "") : (data.text || "");
        ttsStatus.textContent = data.text ? "" : "图片中没有识别到文字";
        ttsStatus.className = "url-status";

        // 3. 成功后 2 秒自动关闭预览（也可手动点 ✕）
        if (data.text) {
            ttsImgAutoCloseTimer = setTimeout(closeTtsImgPreview, 2000);
        }
    } catch (err) {
        ttsImgPreview.classList.remove("loading");
        ttsStatus.textContent = "图片识别失败: " + err.message;
        ttsStatus.className = "url-status error";
    }
});

btnTtsGenerate.addEventListener("click", async () => {
    const text = document.getElementById("ttsText").value.trim();
    if (!text) {
        ttsStatus.textContent = t("tts.needText");
        ttsStatus.className = "url-status error";
        return;
    }

    btnTtsGenerate.disabled = true;
    ttsStatus.textContent = t("tts.generating");
    ttsStatus.className = "url-status";

    try {
        const res = await fetch("/api/tts-generate", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                text,
                language: document.getElementById("ttsLang").value,
                engine: document.getElementById("ttsEngine").value,
                target_lang: getTargetLang(),
            }),
        });
        const data = await res.json();
        if (data.error) {
            ttsStatus.textContent = t("tts.fail") + data.error;
            ttsStatus.className = "url-status error";
            return;
        }
        ttsStatus.textContent = "";
        document.getElementById("ttsText").value = "";
        // 进入播放器（音频 + 字幕 JSON 已在服务器）
        await loadSaved(data.name);
        // 自动保存到本地：音频 + JSON（本地回放学习用）
        saveToLocal(false, false, "json");
    } catch (e) {
        ttsStatus.textContent = t("tts.fail") + e.message;
        ttsStatus.className = "url-status error";
    } finally {
        btnTtsGenerate.disabled = false;
    }
});

// ========== 保存到本地 ==========
// SRT 时间格式：00:00:01,000
function toSrtTime(sec) {
    const h = String(Math.floor(sec / 3600)).padStart(2, "0");
    const m = String(Math.floor((sec % 3600) / 60)).padStart(2, "0");
    const s = String(Math.floor(sec % 60)).padStart(2, "0");
    const ms = String(Math.round((sec % 1) * 1000)).padStart(3, "0");
    return `${h}:${m}:${s},${ms}`;
}

// 生成 SRT 文本；field 为 "text"（原文）或 "translation"（译文）
function generateSrt(field) {
    return segments
        .map((seg, i) => {
            const content = (seg[field] || "").trim();
            return `${i + 1}\n${toSrtTime(seg.start)} --> ${toSrtTime(seg.end)}\n${content}\n`;
        })
        .join("\n");
}

// ========== 保存目录记忆（File System Access API，Chrome/Edge 桌面） ==========
function fsIdb(mode, key, val) {
    return new Promise((resolve) => {
        const req = indexedDB.open("thaiflow-fs", 1);
        req.onupgradeneeded = () => req.result.createObjectStore("kv");
        req.onerror = () => resolve(null);
        req.onsuccess = () => {
            const db = req.result;
            const tx = db.transaction("kv", mode === "get" ? "readonly" : "readwrite");
            const store = tx.objectStore("kv");
            const r = mode === "get" ? store.get(key) : store.put(val, key);
            r.onsuccess = () => resolve(mode === "get" ? r.result : true);
            r.onerror = () => resolve(null);
        };
    });
}

// interactive: 是否处于用户手势中（选目录/请求权限需要手势）
async function getSaveDir(interactive) {
    if (!window.showDirectoryPicker) return null; // Safari 等不支持

    let handle = await fsIdb("get", "saveDir");
    if (handle) {
        try {
            let perm = await handle.queryPermission({ mode: "readwrite" });
            if (perm === "granted") return handle;
            if (interactive) {
                perm = await handle.requestPermission({ mode: "readwrite" });
                if (perm === "granted") return handle;
            } else {
                return null; // 无手势无法请求权限，回退下载
            }
        } catch (e) { /* handle 失效，重新选 */ }
    }

    if (!interactive) return null;
    try {
        handle = await window.showDirectoryPicker({ mode: "readwrite" });
        await fsIdb("put", "saveDir", handle);
        return handle;
    } catch (e) {
        return null; // 用户取消
    }
}

async function writeFileToDir(dir, filename, blob) {
    const fh = await dir.getFileHandle(filename, { create: true });
    const w = await fh.createWritable();
    await w.write(blob);
    await w.close();
}

// 轻量提示条
function showToast(text) {
    let el = document.getElementById("appToast");
    if (!el) {
        el = document.createElement("div");
        el.id = "appToast";
        el.className = "app-toast";
        document.body.appendChild(el);
    }
    el.textContent = text;
    el.classList.add("show");
    clearTimeout(el._timer);
    el._timer = setTimeout(() => el.classList.remove("show"), 3000);
}

// subtitleOnly: 为 true 时只保存字幕（用户本地已有视频文件时）
// interactive: 是否由用户点击触发（首次可弹目录选择框）
// mode: 字幕文件范围
//   "all"  — JSON + 原文SRT + 中文SRT + 封面（句子列表"保存"按钮）
//   "json" — 仅 JSON（桌面端自动保存：本应用回放用）
//   "srt"  — 仅原文 SRT（手机端自动保存：可直接导入剪映）
async function saveToLocal(subtitleOnly, interactive, mode) {
    if (!currentVideoName || segments.length === 0) return;
    mode = mode || "all";

    const baseName = currentVideoName.replace(/\.[^.]+$/, "");
    const files = [];

    if (mode === "all" || mode === "json") {
        // JSON（本应用回放用：含译文和语言信息）
        files.push([baseName + ".json",
            new Blob([JSON.stringify({ segments, language }, null, 2)], { type: "application/json" })]);
    }
    if (mode === "all" || mode === "srt") {
        // SRT 原文（可导入剪映等编辑软件）
        files.push([baseName + "_原文.srt",
            new Blob([generateSrt("text")], { type: "text/plain" })]);
    }
    if (mode === "all" && segments.some(s => s.translation)) {
        // SRT 中文译文
        files.push([baseName + "_中文.srt",
            new Blob([generateSrt("translation")], { type: "text/plain" })]);
    }

    // 朗读课程封面（仅完整保存时附带）
    if (mode === "all" && currentCover) {
        try {
            const res = await fetch(`/videos/${encodeURIComponent(currentCover)}`);
            if (res.ok) files.push([currentCover, await res.blob()]);
        } catch (e) { /* 封面缺失不影响保存 */ }
    }

    // 优先：写入记住的目录（只选一次，之后自动保存）
    const dir = await getSaveDir(interactive === true);
    if (dir) {
        try {
            if (!subtitleOnly) {
                const res = await fetch(`/videos/${encodeURIComponent(currentVideoName)}`);
                files.unshift([currentVideoName, await res.blob()]);
            }
            for (const [name, blob] of files) {
                await writeFileToDir(dir, name, blob);
            }
            showToast(t("save.savedToDir", { n: files.length, dir: dir.name }));
            loadLocalVideoList();
            return;
        } catch (e) {
            console.log("[Save] 目录写入失败，回退下载:", e);
        }
    }

    // 回退：浏览器下载（Safari / 未授权目录时）
    if (!subtitleOnly) {
        const videoLink = document.createElement("a");
        videoLink.href = `/videos/${encodeURIComponent(currentVideoName)}`;
        videoLink.download = currentVideoName;
        videoLink.click();
    }
    let delay = subtitleOnly ? 0 : 500;
    files.forEach(([name, blob], i) => {
        const link = document.createElement("a");
        link.href = URL.createObjectURL(blob);
        link.download = name;
        setTimeout(() => link.click(), delay + i * 500);
    });
}

// ========== 播放本地视频+字幕（公共入口：文件选择器 / 本地列表） ==========
async function playLocalWithSubtitle(videoFile, subtitleFile, coverFile) {
    currentVideoName = videoFile.name;
    localVideoFile = videoFile; // 供波形编辑器解码音频用

    // 先隐藏所有遮罩，再显示播放界面，避免一闪而过
    loadingOverlay.style.display = "none";
    exportOverlay.style.display = "none";
    followReadPanel.style.display = "none";

    phaseSelect.style.display = "none";
    phasePlay.style.display = "flex";
    tryMobileFullscreen();

    // 封面：有图片就显示，否则隐藏
    currentCover = "";
    setLessonCover(coverFile ? URL.createObjectURL(coverFile) : "");

    // 用本地 URL 播放（不上传）
    video.src = URL.createObjectURL(videoFile);
    video.load();

    try {
        const text = await subtitleFile.text();
        const data = JSON.parse(text);
        segments = data.segments || [];
        language = data.language || "";
    } catch (e) {
        alert(t("status.subtitleParseFail") + e.message);
        return;
    }

    await waitForVideo();
    isLoading = false;
    btnTranslate.disabled = false;
    renderSentenceList();
    sentenceMode = true;
    jumpToSentence(0);
    video.play();
    initMobileOverlays();
    openDrawerIfDesktop();
    // 手机端：手动打开的本地文件也存入课程库（下次列表直接点开，不用再翻文件夹）
    saveLessonToLibrary(videoFile, coverFile || null);
}

// ========== 浏览器内置课程库（IndexedDB，手机端本地列表数据源） ==========
const LESSON_DB = "reelspeak-lessons";
const MAX_LESSONS = 20; // 超出后删最旧的，控制存储占用

// 拆库设计：meta（名字/字幕/缩略图，几十KB）与 media（视频大文件）分开。
// 列表只读 meta，避免冷启动一次性载入几百 MB 大文件导致读取失败。
function lessonsOp(stores, mode, fn) {
    return new Promise((resolve, reject) => {
        const timer = setTimeout(() => reject(new Error("IndexedDB 超时")), 8000);
        const done = (fnDone) => (...a) => { clearTimeout(timer); fnDone(...a); };
        resolve = done(resolve);
        reject = done(reject);
        const req = indexedDB.open(LESSON_DB, 2);
        req.onblocked = () => reject(new Error("数据库被其他页面占用"));
        req.onupgradeneeded = () => {
            const db = req.result;
            const tx = req.transaction;
            if (!db.objectStoreNames.contains("meta")) {
                db.createObjectStore("meta", { keyPath: "name" });
            }
            if (!db.objectStoreNames.contains("media")) {
                db.createObjectStore("media", { keyPath: "name" });
            }
            // v1 迁移：旧 lessons 记录拆分到新库
            if (db.objectStoreNames.contains("lessons")) {
                const old = tx.objectStore("lessons");
                const meta = tx.objectStore("meta");
                const media = tx.objectStore("media");
                old.openCursor().onsuccess = (ev) => {
                    const cur = ev.target.result;
                    if (cur) {
                        const r = cur.value;
                        meta.put({ name: r.name, savedAt: r.savedAt, coverName: r.coverName || "",
                                   thumbBlob: r.thumbBlob || null, subtitle: r.subtitle });
                        media.put({ name: r.name, videoBlob: r.videoBlob, coverBlob: r.coverBlob || null });
                        cur.continue();
                    } else {
                        db.deleteObjectStore("lessons");
                    }
                };
            }
        };
        req.onerror = () => reject(req.error);
        req.onsuccess = () => {
            const db = req.result;
            let result;
            try {
                const tx = db.transaction(stores, mode);
                const r = fn(tx);
                if (r) r.onsuccess = () => { result = r.result; };
                tx.oncomplete = () => { db.close(); resolve(result); };
                tx.onerror = () => { db.close(); reject(tx.error); };
                tx.onabort = () => { db.close(); reject(tx.error || new Error("tx aborted")); };
            } catch (e) {
                db.close();
                reject(e);
            }
        };
    });
}

function metaGetAll() {
    return lessonsOp(["meta"], "readonly", tx => tx.objectStore("meta").getAll())
        .then(r => r || []);
}

function metaGet(name) {
    return lessonsOp(["meta"], "readonly", tx => tx.objectStore("meta").get(name)).catch(() => null);
}

function mediaGet(name) {
    return lessonsOp(["media"], "readonly", tx => tx.objectStore("media").get(name)).catch(() => null);
}

function lessonsPut(metaRec, mediaRec) {
    return lessonsOp(["meta", "media"], "readwrite", tx => {
        tx.objectStore("meta").put(metaRec);
        tx.objectStore("media").put(mediaRec);
        return null;
    });
}

function lessonsDelete(name) {
    return lessonsOp(["meta", "media"], "readwrite", tx => {
        tx.objectStore("meta").delete(name);
        tx.objectStore("media").delete(name);
        return null;
    }).catch(() => false);
}

// 申请持久化存储：阻止浏览器在存储压力下清除课程库
if (isMobile() && navigator.storage && navigator.storage.persist) {
    navigator.storage.persist().then(granted => {
        console.log("[Library] 持久化存储:", granted ? "已授予" : "尽力而为模式");
    });
}

// 截取当前视频画面做缩略图（纯音频返回 null，改用封面）
function captureVideoThumb() {
    return new Promise((resolve) => {
        if (video.videoWidth === 0) { resolve(null); return; }
        try {
            const canvas = document.createElement("canvas");
            const w = 320;
            const h = Math.round(w * video.videoHeight / video.videoWidth);
            canvas.width = w;
            canvas.height = h;
            canvas.getContext("2d").drawImage(video, 0, 0, w, h);
            canvas.toBlob(b => resolve(b), "image/jpeg", 0.7);
        } catch (e) {
            resolve(null); // 异常时无缩略图
        }
    });
}

// 课程完成/打开后存入浏览器课程库（手机端专用；桌面用文件夹列表）
// localVideoBlob/localCoverBlob：本地播放场景直接用手里的文件，不走服务器
async function saveLessonToLibrary(localVideoBlob, localCoverBlob) {
    if (!isMobile() || !currentVideoName || segments.length === 0) return;
    try {
        // 已存在则复用大文件，只更新字幕
        const existingMeta = await metaGet(currentVideoName);

        let videoBlob = localVideoBlob;
        let coverBlob = localCoverBlob;
        if (existingMeta) {
            const existingMedia = await mediaGet(currentVideoName);
            if (existingMedia) {
                videoBlob = videoBlob || existingMedia.videoBlob;
                coverBlob = coverBlob || existingMedia.coverBlob;
            }
        }
        if (!videoBlob) {
            const res = await fetch(`/videos/${encodeURIComponent(currentVideoName)}`);
            if (!res.ok) return;
            videoBlob = await res.blob();
        }
        if (!coverBlob && currentCover) {
            try {
                const res = await fetch(`/videos/${encodeURIComponent(currentCover)}`);
                if (res.ok) coverBlob = await res.blob();
            } catch (e) { /* 无封面 */ }
        }

        // 缩略图：视频截帧，音频用封面
        let thumbBlob = existingMeta && existingMeta.thumbBlob;
        if (!thumbBlob) {
            await delay(600); // 等首帧渲染
            thumbBlob = await captureVideoThumb() || coverBlob || null;
        }

        await lessonsPut(
            {
                name: currentVideoName,
                coverName: currentCover || "",
                thumbBlob: thumbBlob || null,
                subtitle: { segments, language },
                savedAt: Date.now(),
            },
            {
                name: currentVideoName,
                videoBlob,
                coverBlob: coverBlob || null,
            }
        );

        // 超量清理：删最旧
        const all = await metaGetAll();
        if (all.length > MAX_LESSONS) {
            all.sort((a, b) => a.savedAt - b.savedAt);
            for (const old of all.slice(0, all.length - MAX_LESSONS)) {
                await lessonsDelete(old.name);
            }
        }
        loadLocalVideoList();
    } catch (e) {
        console.log("[Library] 入库失败:", e);
    }
}

// 手机端：从课程库渲染本地列表（只读轻量 meta，点击时才取大文件）
async function loadLessonLibraryList(section, listEl) {
    let all;
    try {
        all = await metaGetAll();
    } catch (e) {
        // 读取失败：可见地显示错误（便于排查），不再静默隐藏
        section.style.display = "block";
        listEl.innerHTML = "";
        const err = document.createElement("div");
        err.className = "local-play-hint";
        err.textContent = "本地列表读取失败: " + (e && e.message || e);
        listEl.appendChild(err);
        return;
    }
    if (all.length === 0) {
        section.style.display = "none";
        return;
    }
    all.sort((a, b) => b.savedAt - a.savedAt);
    listEl.innerHTML = "";
    section.style.display = "block";

    for (const rec of all) {
        const item = document.createElement("div");
        item.className = "video-item ready";
        item.style.cursor = "pointer";

        if (rec.thumbBlob) {
            const img = document.createElement("img");
            img.className = "video-thumb";
            img.src = URL.createObjectURL(rec.thumbBlob);
            item.appendChild(img);
        }

        const info = document.createElement("div");
        info.className = "video-info";
        const name = document.createElement("div");
        name.className = "video-name";
        name.textContent = rec.name.replace(/\.[^.]+$/, "");
        const status = document.createElement("div");
        status.className = "video-status";
        status.textContent = t("status.ready");
        info.appendChild(name);
        info.appendChild(status);
        item.appendChild(info);

        // 删除按钮
        const actions = document.createElement("div");
        actions.className = "video-actions";
        const btnDel = document.createElement("button");
        btnDel.textContent = "✕";
        btnDel.className = "btn-lesson-del";
        btnDel.addEventListener("click", async (e) => {
            e.stopPropagation();
            await lessonsDelete(rec.name);
            loadLocalVideoList();
        });
        actions.appendChild(btnDel);
        item.appendChild(actions);

        item.addEventListener("click", async () => {
            // 点击时才读取大文件
            const media = await mediaGet(rec.name);
            if (!media || !media.videoBlob) {
                alert(t("status.subtitleFail") + "媒体数据缺失，请重新打开原文件");
                return;
            }
            const ext = rec.name.split(".").pop();
            const mime = ext === "m4a" ? "audio/mp4" : "video/mp4";
            const videoFile = new File([media.videoBlob], rec.name, { type: mime });
            const subtitleFile = new File(
                [JSON.stringify(rec.subtitle)], rec.name.replace(/\.[^.]+$/, "") + ".json",
                { type: "application/json" });
            const coverFile = media.coverBlob
                ? new File([media.coverBlob], rec.coverName || "cover.jpg", { type: "image/jpeg" })
                : null;
            playLocalWithSubtitle(videoFile, subtitleFile, coverFile);
        });
        listEl.appendChild(item);
    }
}

// ========== 本地视频列表 ==========
// 桌面：枚举记忆的保存目录；手机：读取浏览器课程库
async function loadLocalVideoList() {
    const section = document.getElementById("localVideosSection");
    const listEl = document.getElementById("localVideoList");

    // 手机端（或不支持目录 API 的浏览器）：用浏览器课程库
    if (isMobile() || !window.showDirectoryPicker) {
        loadLessonLibraryList(section, listEl);
        return;
    }

    const handle = await fsIdb("get", "saveDir");
    if (!handle) return;

    let perm;
    try {
        perm = await handle.queryPermission({ mode: "read" });
    } catch (e) {
        return; // handle 失效
    }

    listEl.innerHTML = "";
    section.style.display = "block";

    if (perm !== "granted") {
        // 需要用户手势授权才能读取目录
        const btn = document.createElement("button");
        btn.className = "btn-local-play";
        btn.textContent = t("app.locallist.load");
        btn.addEventListener("click", async () => {
            const req = await handle.requestPermission({ mode: "read" });
            if (req === "granted") loadLocalVideoList();
        });
        listEl.appendChild(btn);
        return;
    }

    // 枚举目录：视频/音频 + 同名 JSON（识别过的才展示）
    const media = {};   // base -> {name, handle, mtime}
    const jsons = {};   // base -> handle
    const images = {};  // base -> handle
    try {
        for await (const entry of handle.values()) {
            if (entry.kind !== "file") continue;
            const name = entry.name;
            const lower = name.toLowerCase();
            const base = name.replace(/\.[^.]+$/, "");
            if (/\.(mp4|m4a|mp3|mov|webm)$/.test(lower)) {
                media[base] = { name, handle: entry };
            } else if (lower.endsWith(".json")) {
                jsons[base] = entry;
            } else if (/\.(jpg|jpeg|png|webp)$/.test(lower)) {
                images[base] = entry;
            }
        }
    } catch (e) {
        console.log("[LocalList] 枚举目录失败:", e);
        section.style.display = "none";
        return;
    }

    const bases = Object.keys(media).filter(b => jsons[b]);
    if (bases.length === 0) {
        section.style.display = "none";
        return;
    }

    // 按文件修改时间倒序（最近的在前）
    const items = [];
    for (const b of bases) {
        let mtime = 0;
        try {
            const f = await media[b].handle.getFile();
            mtime = f.lastModified;
        } catch (e) { /* ignore */ }
        items.push({ base: b, mtime });
    }
    items.sort((a, b) => b.mtime - a.mtime);

    for (const { base } of items) {
        const item = document.createElement("div");
        item.className = "video-item ready";
        item.style.cursor = "pointer";

        // 缩略图占位（异步填充）
        const img = document.createElement("img");
        img.className = "video-thumb";
        item.appendChild(img);
        fillDirThumb(img, base, media, images);

        const info = document.createElement("div");
        info.className = "video-info";
        const name = document.createElement("div");
        name.className = "video-name";
        name.textContent = base;
        const status = document.createElement("div");
        status.className = "video-status";
        status.textContent = t("status.ready");
        info.appendChild(name);
        info.appendChild(status);
        item.appendChild(info);

        item.addEventListener("click", async () => {
            try {
                const videoFile = await media[base].handle.getFile();
                const subtitleFile = await jsons[base].getFile();
                const coverFile = images[base] ? await images[base].getFile() : null;
                playLocalWithSubtitle(videoFile, subtitleFile, coverFile);
            } catch (e) {
                alert(t("status.subtitleFail") + e.message);
            }
        });
        listEl.appendChild(item);
    }
}

// 桌面目录列表缩略图：同名图片优先，否则视频截帧（结果缓存到 IndexedDB）
async function fillDirThumb(img, base, media, images) {
    try {
        // 1. 同名封面图片
        if (images[base]) {
            const f = await images[base].getFile();
            img.src = URL.createObjectURL(f);
            return;
        }
        // 2. 缓存的截帧
        const cached = await fsIdb("get", "thumb:" + base);
        if (cached instanceof Blob) {
            img.src = URL.createObjectURL(cached);
            return;
        }
        // 3. 从视频截帧并缓存
        const f = await media[base].handle.getFile();
        if (!f.type.startsWith("video/") && !/\.(mp4|mov|webm)$/i.test(f.name)) {
            img.style.display = "none"; // 纯音频且无封面
            return;
        }
        const blob = await thumbFromVideoFile(f);
        if (blob) {
            img.src = URL.createObjectURL(blob);
            fsIdb("put", "thumb:" + base, blob);
        } else {
            img.style.display = "none";
        }
    } catch (e) {
        img.style.display = "none";
    }
}

// 从视频文件截取一帧生成缩略图 blob
function thumbFromVideoFile(file) {
    return new Promise((resolve) => {
        const v = document.createElement("video");
        v.muted = true;
        v.preload = "metadata";
        v.src = URL.createObjectURL(file);
        const cleanup = (result) => {
            URL.revokeObjectURL(v.src);
            v.removeAttribute("src");
            resolve(result);
        };
        v.addEventListener("loadeddata", () => { v.currentTime = 0.5; });
        v.addEventListener("seeked", () => {
            try {
                const canvas = document.createElement("canvas");
                const w = 320;
                const h = Math.round(w * v.videoHeight / v.videoWidth) || 180;
                canvas.width = w;
                canvas.height = h;
                canvas.getContext("2d").drawImage(v, 0, 0, w, h);
                canvas.toBlob(b => cleanup(b), "image/jpeg", 0.7);
            } catch (e) {
                cleanup(null);
            }
        }, { once: true });
        v.addEventListener("error", () => cleanup(null));
        setTimeout(() => cleanup(null), 8000); // 超时保底
    });
}

// ========== 打开本地文件（直接播放，不上传） ==========
async function openLocalFiles() {
    const input = document.getElementById("localFiles");
    const files = Array.from(input.files);
    if (files.length === 0) return;

    let videoFile = null;
    let subtitleFile = null;
    let coverFile = null;

    for (const f of files) {
        const lower = f.name.toLowerCase();
        if (f.type.startsWith("video/") || f.type.startsWith("audio/") ||
            lower.endsWith(".mp4") || lower.endsWith(".m4a") || lower.endsWith(".mp3")) {
            videoFile = f;
        } else if (lower.endsWith(".json")) {
            subtitleFile = f;
        } else if (f.type.startsWith("image/")) {
            coverFile = f;
        }
    }

    if (!videoFile) {
        alert(t("status.selectVideo"));
        return;
    }

    if (subtitleFile) {
        await playLocalWithSubtitle(videoFile, subtitleFile, coverFile);
    } else {
        // 没有字幕文件：先上传到服务器，再走与"粘贴链接"完全一致的识别翻译流程
        currentVideoName = videoFile.name;
        localVideoFile = videoFile;
        exportOverlay.style.display = "none";
        followReadPanel.style.display = "none";
        phaseSelect.style.display = "none";
        phasePlay.style.display = "flex";
        tryMobileFullscreen();
        currentCover = "";
        setLessonCover("");
        video.src = URL.createObjectURL(videoFile);
        video.load();

        isLoading = true;
        loadingOverlay.style.display = "flex";
        setStep("step1", "active");
        setTip(t("status.uploadingServer"));

        let serverName;
        try {
            const formData = new FormData();
            formData.append("video", videoFile);
            const res = await fetch("/api/upload-video", { method: "POST", body: formData });
            const data = await res.json();
            if (data.error) {
                setStep("step1", "error");
                setTip(t("status.uploadFail") + data.error);
                return;
            }
            serverName = data.name;
        } catch (e) {
            setStep("step1", "error");
            setTip(t("status.uploadFail") + e.message);
            return;
        }

        // 统一流程：与链接下载/重新识别使用同一个 startLoading
        // subtitleOnly=true：用户本地已有视频文件，完成后只下载字幕
        await startLoading(serverName, true);
    }

    input.value = "";
}

// ========== 显示播放界面并加载视频首帧 ==========
function showPlayerWithVideo(videoName) {
    currentVideoName = videoName;
    isLoading = true;

    // 切换到播放界面
    phaseSelect.style.display = "none";
    phasePlay.style.display = "flex";
    tryMobileFullscreen();
    currentCover = "";
    setLessonCover("");

    // 加载视频（显示首帧）
    video.src = `/videos/${encodeURIComponent(videoName)}`;
    video.load();

    // 显示加载遮罩
    loadingOverlay.style.display = "flex";
    setStep("step1", "");
    setStep("step2", "");
    setStep("step3", "");
    setTip("");
}

// ========== 朗读课程封面 ==========
const lessonCover = document.getElementById("lessonCover");
let currentCover = ""; // 服务器上的封面文件名

function setLessonCover(src) {
    if (src) {
        lessonCover.src = src;
        lessonCover.style.display = "block";
    } else {
        lessonCover.style.display = "none";
        lessonCover.removeAttribute("src");
    }
    updateSubtitleWidth();
}

// 封面图加载完成后按其实际宽度重排字幕
lessonCover.addEventListener("load", updateSubtitleWidth);

// ========== 加载已保存的字幕 ==========
async function loadSaved(videoName) {
    currentVideoName = videoName;
    isLoading = true;

    // 切换到播放界面（不显示加载遮罩）
    phaseSelect.style.display = "none";
    loadingOverlay.style.display = "none";
    phasePlay.style.display = "flex";
    tryMobileFullscreen();

    video.src = `/videos/${encodeURIComponent(videoName)}`;
    video.load();

    // 并行加载视频和字幕
    const subtitlePromise = fetch(`/api/subtitle/${encodeURIComponent(videoName)}`)
        .then(res => res.json());

    await waitForVideo();

    try {
        const data = await subtitlePromise;
        segments = data.segments || [];
        language = data.language || "";
        // 朗读课程封面
        currentCover = data.cover || "";
        setLessonCover(currentCover ? `/videos/${encodeURIComponent(currentCover)}` : "");
    } catch (e) {
        alert(t("status.subtitleFail") + e.message);
        return;
    }

    isLoading = false;
    btnTranslate.disabled = false;
    renderSentenceList();
    sentenceMode = true;
    jumpToSentence(0);
    video.play();
    initMobileOverlays();
    openDrawerIfDesktop();
    // 手机端：存入浏览器课程库（服务器被清空后仍可重播）
    saveLessonToLibrary();
}

// ========== 完整加载流程 ==========
async function startLoading(videoName, subtitleOnly) {
    showPlayerWithVideo(videoName);

    // 步骤 1：加载视频
    setStep("step1", "active");
    setTip(t("status.loadingVideo"));
    await waitForVideo();
    setStep("step1", "done");

    // 步骤 2：语音识别
    const provider = transcribeProvider.value;
    const providerLabels = {
        groq: t("status.providerGroq"),
        azure: t("status.providerAzure"),
        combined: t("status.providerCombined"),
    };
    const providerLabel = providerLabels[provider] || provider;
    setStep("step2", "active");
    setTip(t("status.callingProvider", { provider: providerLabel }));
    try {
        const segTarget = segmentTarget.value || null;
        const res = await fetch("/api/transcribe", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ video: videoName, provider, segment_target: segTarget }),
        });
        const data = await res.json();
        if (data.error) {
            setStep("step2", "error");
            setTip(t("status.recognizeFail") + data.error);
            return;
        }
        segments = data.segments || [];
        language = data.language || "";
        setStep("step2", "done");
        setTip(t("status.recognizeDone", { n: segments.length }));
    } catch (e) {
        setStep("step2", "error");
        setTip(t("status.recognizeFail") + e.message);
        return;
    }

    // 步骤 3：翻译
    setStep("step3", "active");
    setTip(t("status.translating"));
    const langMap = { th: "泰语", en: "英语", ja: "日语", ko: "韩语", fr: "法语", de: "德语", es: "西班牙语", pt: "葡萄牙语", ru: "俄语", it: "意大利语" };
    const sourceLang = langMap[language] || "外语";
    try {
        const res = await fetch("/api/translate", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                segments: segments.map((s) => ({ index: s.index, text: s.text })),
                source_lang: sourceLang,
                target_lang: getTargetLang(),
            }),
        });
        const data = await res.json();
        if (data.error) {
            setStep("step3", "error");
            setTip(t("status.translateFail") + data.error + t("status.translateRetry"));
        } else {
            (data.translations || []).forEach((tr) => {
                if (segments[tr.index]) segments[tr.index].translation = tr.translation;
            });
            setStep("step3", "done");
            setTip(t("status.allReady"));
        }
    } catch (e) {
        setStep("step3", "error");
        setTip(t("status.translateFail") + e.message + t("status.translateRetry"));
    }

    // 保存字幕
    await saveSubtitle();

    await delay(500);
    finishLoading();

    // 处理完成后自动下载到本地（subtitleOnly: 用户本地已有视频，只下字幕）
    // 自动保存只下 2 个文件：视频 + JSON（本地回放学习用，两端一致）
    // SRT 等其余字幕格式由句子列表"保存"按钮获取
    saveToLocal(subtitleOnly === true, false, "json");
    // 手机端：同时存入浏览器课程库（首页"本地视频"列表，点击即播）
    saveLessonToLibrary();
}

// ========== 等待视频可播放 ==========
function waitForVideo() {
    return new Promise((resolve) => {
        if (video.readyState >= 2) {
            resolve();
            return;
        }
        const onReady = () => {
            video.removeEventListener("loadeddata", onReady);
            video.removeEventListener("error", onError);
            resolve();
        };
        const onError = () => {
            video.removeEventListener("loadeddata", onReady);
            video.removeEventListener("error", onError);
            setStep("step1", "error");
            setTip(t("status.videoLoadFail"));
        };
        video.addEventListener("loadeddata", onReady);
        video.addEventListener("error", onError);
    });
}

// 桌面端：句子列表默认展开
function openDrawerIfDesktop() {
    if (!isMobile()) {
        sentenceDrawer.style.display = "flex";
    }
}

// ========== 加载完成，进入播放 ==========
function finishLoading() {
    isLoading = false;
    loadingOverlay.style.display = "none";
    btnTranslate.disabled = false;

    renderSentenceList();
    sentenceMode = true;
    jumpToSentence(0);
    video.play();
    initMobileOverlays();
    openDrawerIfDesktop();

    // 识别完成后自动进入全屏（移动端）
    // video.play() 算 user-activation 延续，此时可以请求全屏
    tryMobileFullscreen();
}

// ========== 保存字幕 ==========
async function saveSubtitle() {
    try {
        await fetch(`/api/subtitle/${encodeURIComponent(currentVideoName)}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ segments, language }),
        });
    } catch (e) {
        console.error("保存字幕失败:", e);
    }
}

// ========== 返回选择 ==========
function backToSelect() {
    // 退出全屏
    exitFullscreen();
    video.pause();
    video.src = "";
    sentenceMode = false;
    isLoading = false;
    segments = [];
    currentIndex = -1;
    phasePlay.style.display = "none";
    phaseSelect.style.display = "flex";
    sentenceDrawer.style.display = "none";
    loadingOverlay.style.display = "none";
    // 重置移动端模式到默认（播放一遍）
    switchMode("normal");
    // Reset mobile overlays
    mOverlaysInitialized = false;
    hideMobileOverlays();
    loadVideoList();
    loadLocalVideoList();
}

// ========== 句子列表抽屉 ==========
function toggleDrawer() {
    if (sentenceDrawer.style.display === "none") {
        sentenceDrawer.style.display = "flex";
        highlightSentence(currentIndex);
    } else {
        sentenceDrawer.style.display = "none";
    }
}

// ========== 渲染句子列表 ==========
function renderSentenceList() {
    sentenceList.innerHTML = "";
    segments.forEach((seg, i) => {
        const div = document.createElement("div");
        div.className = "sentence-item";
        div.dataset.index = i;
        const mergeBtn = i < segments.length - 1
            ? `<button class="sentence-merge-btn" title="与下一句合并">
                   <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                       <line x1="12" y1="4" x2="12" y2="15"/>
                       <polyline points="6,10 12,16 18,10"/>
                       <line x1="5" y1="20" x2="19" y2="20"/>
                   </svg>
               </button>`
            : "";
        div.innerHTML = `
            <div class="sentence-content">
                <span class="seq">${i + 1}</span>
                <div class="text-group">
                    <div class="time">${formatTime(seg.start)} - ${formatTime(seg.end)}</div>
                    <div class="original">${escapeHtml(seg.text)}</div>
                    <div class="translation">${escapeHtml(seg.translation || "")}</div>
                </div>
                <div class="sentence-actions">
                    <button class="sentence-edit-btn" title="编辑">✎</button>
                    ${mergeBtn}
                    <button class="sentence-wave-btn" title="音轨编辑">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="3" y1="9" x2="3" y2="15"/><line x1="7" y1="5" x2="7" y2="19"/><line x1="11" y1="9" x2="11" y2="15"/><line x1="15" y1="3" x2="15" y2="21"/><line x1="19" y1="8" x2="19" y2="16"/></svg>
                    </button>
                </div>
            </div>
            <button class="sentence-delete-btn">删除</button>
        `;
        div.addEventListener("click", (e) => {
            if (e.target.closest(".sentence-edit-btn")) return;
            if (e.target.closest(".sentence-merge-btn")) return;
            if (e.target.closest(".sentence-delete-btn")) return;
            if (div.classList.contains("editing")) return;
            // 已滑出删除状态时，点击先收回
            if (div.classList.contains("swiped")) {
                closeSwipedItems();
                return;
            }
            sentenceMode = true;
            jumpToSentence(i);
            video.play();
        });
        div.querySelector(".sentence-edit-btn").addEventListener("click", (e) => {
            e.stopPropagation();
            closeSwipedItems();
            enterEditMode(div, i);
        });
        const mBtn = div.querySelector(".sentence-merge-btn");
        if (mBtn) {
            mBtn.addEventListener("click", (e) => {
                e.stopPropagation();
                mergeSentenceDown(i);
            });
        }
        div.querySelector(".sentence-delete-btn").addEventListener("click", (e) => {
            e.stopPropagation();
            deleteSentence(i);
        });
        div.querySelector(".sentence-wave-btn").addEventListener("click", (e) => {
            e.stopPropagation();
            closeSwipedItems();
            openWaveEditor(i);
        });
        attachSwipeToDelete(div);
        sentenceList.appendChild(div);
    });
}

// ========== 左滑删除 ==========
function closeSwipedItems() {
    sentenceList.querySelectorAll(".sentence-item.swiped").forEach((el) => {
        el.classList.remove("swiped");
        el.querySelector(".sentence-content").style.transform = "";
    });
}

function attachSwipeToDelete(div) {
    const content = div.querySelector(".sentence-content");
    let startX = 0, startY = 0, swiping = false;

    div.addEventListener("touchstart", (e) => {
        startX = e.touches[0].clientX;
        startY = e.touches[0].clientY;
        swiping = false;
    }, { passive: true });

    div.addEventListener("touchmove", (e) => {
        if (div.classList.contains("editing")) return;
        const dx = e.touches[0].clientX - startX;
        const dy = e.touches[0].clientY - startY;
        // 水平滑动为主时才触发（不干扰列表垂直滚动）
        if (!swiping && Math.abs(dx) > 10 && Math.abs(dx) > Math.abs(dy) * 1.5) {
            swiping = true;
            div.classList.add("swiping");
        }
        if (swiping && dx < 0) {
            content.style.transform = `translateX(${Math.max(dx, -80)}px)`;
        } else if (swiping && dx > 0) {
            // 右滑视觉暗示（最多 40px），松手后打开波形编辑器
            content.style.transform = `translateX(${Math.min(dx, 40)}px)`;
        }
    }, { passive: true });

    div.addEventListener("touchend", (e) => {
        if (!swiping) return;
        div.classList.remove("swiping");
        const dx = e.changedTouches[0].clientX - startX;
        if (dx < -40) {
            // 左滑：滑出删除按钮
            closeSwipedItems();
            div.classList.add("swiped");
            content.style.transform = "translateX(-80px)";
        } else if (dx > 60) {
            // 右滑：打开波形音轨编辑器
            closeSwipedItems();
            content.style.transform = "";
            openWaveEditor(parseInt(div.dataset.index));
        } else {
            div.classList.remove("swiped");
            content.style.transform = "";
        }
    });
}

// ========== 向下合并句子 ==========
async function mergeSentenceDown(i) {
    if (i >= segments.length - 1) return;
    if (!confirm(`确定将第 ${i + 1} 句与第 ${i + 2} 句合并吗？`)) return;

    const a = segments[i];
    const b = segments[i + 1];
    a.text = (a.text + " " + b.text).trim();
    a.translation = ((a.translation || "") + (b.translation || "")).trim();
    a.end = b.end;
    segments.splice(i + 1, 1);

    // 调整当前播放位置
    if (currentIndex > i) currentIndex--;

    renderSentenceList();
    highlightSentence(currentIndex);
    updateRepeatInfo(parseInt(repeatCountSelect.value) || 3);
    if (currentIndex === i) updateSubtitle(segments[i]);
    await saveSubtitle();
}

// ========== 删除句子 ==========
async function deleteSentence(i) {
    segments.splice(i, 1);

    if (segments.length === 0) {
        currentIndex = -1;
    } else if (currentIndex >= segments.length) {
        currentIndex = segments.length - 1;
    } else if (currentIndex > i) {
        currentIndex--;
    }

    renderSentenceList();
    highlightSentence(currentIndex);
    updateRepeatInfo(parseInt(repeatCountSelect.value) || 3);
    await saveSubtitle();
}

// ========== 编辑句子（原文/译文） ==========
function enterEditMode(div, i) {
    if (div.classList.contains("editing")) return;
    // 进入编辑模式：停止自动按句播放
    if (frShadowMode) stopShadowRead();
    video.pause();
    div.classList.add("editing");
    const seg = segments[i];
    const textGroup = div.querySelector(".text-group");
    const origHtml = textGroup.innerHTML;

    textGroup.innerHTML = `
        <div class="time">${formatTime(seg.start)} - ${formatTime(seg.end)}</div>
        <textarea class="edit-original" rows="2">${escapeHtml(seg.text)}</textarea>
        <textarea class="edit-translation" rows="2">${escapeHtml(seg.translation || "")}</textarea>
        <div class="edit-actions">
            <button class="edit-save">✓ 保存</button>
            <button class="edit-cancel">✕ 取消</button>
        </div>
    `;

    textGroup.querySelector(".edit-save").addEventListener("click", async (e) => {
        e.stopPropagation();
        seg.text = textGroup.querySelector(".edit-original").value.trim();
        seg.translation = textGroup.querySelector(".edit-translation").value.trim();
        div.classList.remove("editing");
        // 同步列表显示
        textGroup.innerHTML = `
            <div class="time">${formatTime(seg.start)} - ${formatTime(seg.end)}</div>
            <div class="original">${escapeHtml(seg.text)}</div>
            <div class="translation">${escapeHtml(seg.translation || "")}</div>
        `;
        // 同步当前字幕显示
        if (i === currentIndex) updateSubtitle(seg);
        // 同步跟读面板
        if (followReadPanel.style.display !== "none" && i === currentIndex) {
            updateFollowReadContent();
        }
        // 保存到服务器
        await saveSubtitle();
    });

    textGroup.querySelector(".edit-cancel").addEventListener("click", (e) => {
        e.stopPropagation();
        div.classList.remove("editing");
        textGroup.innerHTML = origHtml;
    });
}

// ========== 按句播放核心逻辑 ==========
function onTimeUpdate() {
    if (!sentenceMode || segments.length === 0 || currentIndex < 0) return;

    const seg = segments[currentIndex];
    if (!seg) return;

    const maxRepeat = parseInt(repeatCountSelect.value) || 3;

    updateSubtitle(seg);

    if (video.currentTime >= seg.end - 0.05) {
        // 跟读面板打开时
        if (followReadPanel.style.display !== "none") {
            if (frShadowMode) {
                // 影子跟读模式：按重复次数播放，播完跳下一句
                repeatCount++;
                updateRepeatInfo(maxRepeat);
                if (repeatCount < maxRepeat) {
                    video.currentTime = seg.start;
                    video.play();
                } else {
                    onShadowSentenceEnd();
                }
            } else {
                // 非影子跟读：播完当前句就暂停
                video.pause();
            }
            return;
        }

        repeatCount++;
        updateRepeatInfo(maxRepeat);

        if (repeatCount < maxRepeat) {
            video.currentTime = seg.start;
            video.play();
        } else {
            if (currentIndex + 1 < segments.length) {
                const nextSeg = segments[currentIndex + 1];
                // 连续播放（1遍模式）且下一句紧接当前句时，不 seek，避免卡顿
                if (maxRepeat === 1 && Math.abs(nextSeg.start - seg.end) < 0.3) {
                    currentIndex++;
                    repeatCount = 0;
                    updateRepeatInfo(maxRepeat);
                    updateSubtitle(nextSeg);
                    highlightSentence(currentIndex);
                    // 同步跟读面板
                    if (followReadPanel.style.display !== "none") {
                        updateFollowReadContent();
                    }
                } else {
                    jumpToSentence(currentIndex + 1);
                    video.play();
                }
            } else {
                // 最后一句播完：自动从第一句重新开始（无限循环）
                jumpToSentence(0);
                video.play();
            }
        }
    }
}

function jumpToSentence(index) {
    if (index < 0 || index >= segments.length) return;
    currentIndex = index;
    repeatCount = 0;
    const seg = segments[index];
    video.currentTime = seg.start;
    updateRepeatInfo(parseInt(repeatCountSelect.value) || 3);
    updateSubtitle(seg);
    highlightSentence(index);

    // 跟读面板打开时，同步更新显示的句子
    if (followReadPanel.style.display !== "none") {
        updateFollowReadContent();
    }
}

function prevSentence() {
    if (currentIndex > 0) {
        sentenceMode = true;
        jumpToSentence(currentIndex - 1);
        if (frShadowMode) {
            // 影子跟读中切句：保持跟读状态，继续按遍数朗读
            playShadowSentence();
        } else {
            video.play();
        }
    }
}

function nextSentence() {
    if (currentIndex < segments.length - 1) {
        sentenceMode = true;
        jumpToSentence(currentIndex + 1);
        if (frShadowMode) {
            playShadowSentence();
        } else {
            video.play();
        }
    }
}

function repeatCurrent() {
    if (currentIndex >= 0) {
        sentenceMode = true;
        jumpToSentence(currentIndex);
        video.play();
    }
}

// ========== 字幕显示逻辑 ==========
// 根据当前重复次数和设定的总重复次数，决定字幕显示方式：
// - 重复3次：第1遍盲听、第2遍原文、第3遍双语
// - 重复1~2次：始终显示双语
// - 重复4次及以上：前3遍按上述规则，第4遍起显示双语
function getSubtitleMode() {
    const maxRepeat = parseInt(repeatCountSelect.value) || 3;
    if (maxRepeat !== 3) {
        // 非3次模式：1~2次全显示，4+次前3遍按规则其余全显示
        if (maxRepeat <= 2) return "both";
        // maxRepeat >= 4
        if (repeatCount === 0) return "none";
        if (repeatCount === 1) return "original";
        return "both";
    }
    // 恰好3次模式
    if (repeatCount === 0) return "none";
    if (repeatCount === 1) return "original";
    return "both";
}

// ========== 卡拉OK逐词高亮（原文字幕） ==========
// 词级时间按字符数比例在句子时长内插值（无需词级时间戳，任何语言/引擎通用）
let kwSegKey = null;   // 当前已渲染句子的标识
let kwSpans = [];      // 词 span 元素
let kwBounds = [];     // 每词归一化结束位置 (0,1]
let kwActive = -1;
let kwRaf = null;

function renderKaraoke(seg) {
    const text = seg.text || "";
    const key = `${seg.index ?? -1}|${text}`;
    if (kwSegKey === key) return; // 同句复读时不重建
    kwSegKey = key;
    kwActive = -1;
    kwSpans = [];
    kwBounds = [];
    subtitleOriginal.textContent = "";

    if (!text) return;

    // 分词：有空格按词分（英/泰-已分词等）；无空格按字符分（中/日等）
    const tokens = text.includes(" ")
        ? text.split(/\s+/).filter(Boolean)
        : Array.from(text);
    const spaced = text.includes(" ");

    const weights = tokens.map(tk => Math.max(1, tk.length));
    const total = weights.reduce((a, b) => a + b, 0);

    let cum = 0;
    tokens.forEach((tk, i) => {
        const span = document.createElement("span");
        span.className = "kw";
        span.textContent = tk;
        subtitleOriginal.appendChild(span);
        if (spaced && i < tokens.length - 1) {
            subtitleOriginal.appendChild(document.createTextNode(" "));
        }
        cum += weights[i];
        kwSpans.push(span);
        kwBounds.push(cum / total);
    });
}

function updateKaraoke() {
    if (currentIndex < 0 || !segments[currentIndex] || kwSpans.length === 0) return;
    if (subtitleOriginal.style.display === "none") return;
    const seg = segments[currentIndex];
    const dur = seg.end - seg.start;
    if (dur <= 0) return;

    let p = (video.currentTime - seg.start) / dur;
    if (p < 0) p = 0;
    if (p >= 1) p = 0.999;

    let idx = kwBounds.findIndex(b => p < b);
    if (idx === -1) idx = kwSpans.length - 1;

    if (idx !== kwActive) {
        if (kwActive >= 0 && kwSpans[kwActive]) kwSpans[kwActive].classList.remove("kw-active");
        kwSpans[idx].classList.add("kw-active");
        kwActive = idx;
    }
}

function kwLoop() {
    updateKaraoke();
    kwRaf = requestAnimationFrame(kwLoop);
}

video.addEventListener("play", () => {
    cancelAnimationFrame(kwRaf);
    kwLoop();
});
video.addEventListener("pause", () => {
    cancelAnimationFrame(kwRaf);
});

function updateSubtitle(seg) {
    renderKaraoke(seg);
    subtitleTranslation.textContent = seg.translation || "";
    updateSubtitleVisibility();
}

function clearSubtitle() {
    subtitleOriginal.textContent = "";
    subtitleTranslation.textContent = "";
    kwSegKey = null;
    kwSpans = [];
    kwBounds = [];
    kwActive = -1;
}

function updateSubtitleVisibility() {
    const mode = getSubtitleMode();
    // 课程模式下原文/译文是统一卡片内的整行（block），视频模式是独立药丸（inline-block）
    const shown = videoContainer.classList.contains("lesson-mode") ? "block" : "inline-block";
    // 盲听遍：课程模式下连卡片背景一起隐藏
    subtitleOverlay.classList.toggle("sub-empty", mode === "none");
    if (mode === "none") {
        subtitleOriginal.style.display = "none";
        subtitleTranslation.style.display = "none";
    } else if (mode === "original") {
        subtitleOriginal.style.display = shown;
        subtitleTranslation.style.display = "none";
    } else {
        subtitleOriginal.style.display = shown;
        subtitleTranslation.style.display = shown;
    }
    // 同步勾选框状态作为视觉反馈
    chkOriginal.checked = (mode !== "none");
    chkTranslation.checked = (mode === "both");
}

// ========== 高亮句子 ==========
function highlightSentence(index) {
    document.querySelectorAll(".sentence-item").forEach((el) => {
        el.classList.toggle("active", parseInt(el.dataset.index) === index);
    });
    const activeEl = sentenceList.querySelector(".sentence-item.active");
    if (activeEl) {
        activeEl.scrollIntoView({ behavior: "smooth", block: "center" });
    }
}

// ========== 翻译（手动重试） ==========
async function translateAll() {
    if (segments.length === 0) return;

    btnTranslate.disabled = true;
    btnTranslate.textContent = t("status.translatingBtn");

    const langMap = { th: "泰语", en: "英语", ja: "日语", ko: "韩语", fr: "法语", de: "德语", es: "西班牙语", pt: "葡萄牙语", ru: "俄语", it: "意大利语" };
    const sourceLang = langMap[language] || "外语";

    try {
        const res = await fetch("/api/translate", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                segments: segments.map((s) => ({ index: s.index, text: s.text })),
                source_lang: sourceLang,
                target_lang: getTargetLang(),
            }),
        });
        const data = await res.json();
        if (data.error) {
            alert(t("status.translateFail") + data.error);
        } else {
            (data.translations || []).forEach((tr) => {
                if (segments[tr.index]) segments[tr.index].translation = tr.translation;
            });
            renderSentenceList();
            highlightSentence(currentIndex);
            if (currentIndex >= 0) updateSubtitle(segments[currentIndex]);
            await saveSubtitle();
        }
    } catch (e) {
        alert(t("status.translateFail") + e.message);
    }
    btnTranslate.textContent = t("status.retranslate");
    btnTranslate.disabled = false;
}

// ========== 导出设置弹窗 ==========
function showExportModal() {
    if (!currentVideoName) return;
    video.pause();

    const base = currentVideoName.replace(/\.[^.]+$/, "");
    exportPrefixInput.value = base;
    if (!exportDirInput.value) {
        exportDirInput.value = "/Users/apple/Desktop";
    }
    dirBrowser.style.display = "none";
    updateExportHint();
    exportPrefixInput.addEventListener("input", updateExportHint);
    exportTypeSelect.addEventListener("change", updateExportHint);

    exportModal.style.display = "flex";
}

// ========== 目录浏览器 ==========
async function openDirBrowser(path) {
    try {
        const res = await fetch(`/api/browse-dir?path=${encodeURIComponent(path)}`);
        const data = await res.json();

        dirCurrent.textContent = data.current;
        btnDirUp.dataset.parent = data.parent || "";
        btnDirUp.disabled = !data.parent;

        dirList.innerHTML = "";
        if (data.dirs.length === 0) {
            dirList.innerHTML = `<div class="dir-item" style="color:#666;">${t("export.dir.noSub")}</div>`;
        } else {
            data.dirs.forEach((name) => {
                const item = document.createElement("div");
                item.className = "dir-item";
                item.innerHTML = `<span class="dir-item-icon">📁</span><span>${escapeHtml(name)}</span>`;
                item.addEventListener("click", () => {
                    openDirBrowser(data.current + "/" + name);
                });
                dirList.appendChild(item);
            });
        }

        dirBrowser.style.display = "block";
    } catch (e) {
        console.error("浏览目录失败:", e);
    }
}

function updateExportHint() {
    const prefix = exportPrefixInput.value.trim() || t("hint.videoName");
    const type = exportTypeSelect.value;
    if (type === "srt") {
        exportHint.textContent = t("hint.srtFiles", { prefix });
    } else {
        exportHint.textContent = t("hint.allFiles", { prefix });
    }
}

// ========== 执行导出 ==========
async function doExport() {
    const exportDir = exportDirInput.value.trim();
    const filePrefix = exportPrefixInput.value.trim();
    const exportType = exportTypeSelect.value;

    if (!exportDir) {
        alert(t("status.enterExportDir"));
        return;
    }

    exportModal.style.display = "none";
    btnExport.disabled = true;

    // 仅导出字幕
    if (exportType === "srt") {
        try {
            const res = await fetch("/api/export-srt", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    video: currentVideoName,
                    export_dir: exportDir,
                    file_prefix: filePrefix,
                }),
            });
            const data = await res.json();
            if (data.error) {
                alert(t("status.exportFail") + data.error);
            } else {
                alert(t("status.srtExportDone", { dir: data.dir, files: data.files.join(", ") }));
            }
        } catch (e) {
            alert(t("status.exportFail") + e.message);
        }
        btnExport.disabled = false;
        return;
    }

    // 带字幕视频导出（含进度条）
    exportOverlay.style.display = "flex";
    exportProgressBar.style.width = "0%";
    exportPct.textContent = "0%";

    try {
        const res = await fetch("/api/export", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                video: currentVideoName,
                export_dir: exportDir,
                file_prefix: filePrefix,
            }),
        });

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let result = null;

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n");
            buffer = lines.pop();

            for (const line of lines) {
                if (!line.startsWith("data: ")) continue;
                const data = JSON.parse(line.slice(6));

                if (data.progress !== undefined) {
                    exportProgressBar.style.width = data.progress + "%";
                    exportPct.textContent = data.progress + "%";
                }
                if (data.done) {
                    result = data;
                }
                if (data.error) {
                    throw new Error(data.error);
                }
            }
        }

        exportProgressBar.style.width = "100%";
        if (result) {
            exportPct.textContent = t("status.exportDone") + result.dir;
        } else {
            exportPct.textContent = "100%";
        }
        await delay(1500);
    } catch (e) {
        alert(t("status.exportFail") + e.message);
    }

    exportOverlay.style.display = "none";
    btnExport.disabled = false;
}

// ========== 时间显示 ==========
function updateTimeDisplay() {
    const current = video.currentTime || 0;
    const total = video.duration || 0;
    timeDisplay.textContent = `${formatTimeMM(current)} / ${formatTimeMM(total)}`;
}

function formatTimeMM(seconds) {
    if (!isFinite(seconds)) return "0:00";
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${String(s).padStart(2, "0")}`;
}

// ========== 工具函数 ==========
function formatTime(seconds) {
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    const ms = Math.floor((seconds % 1) * 10);
    return `${m}:${String(s).padStart(2, "0")}.${ms}`;
}

function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}

function updateRepeatInfo(maxRepeat) {
    const modeLabels = { none: t("mode.none"), original: t("mode.original"), both: t("mode.both") };
    const mode = getSubtitleMode();
    const label = modeLabels[mode];
    const info = `${currentIndex + 1}/${segments.length} | ${repeatCount + 1}/${maxRepeat} ${label}`;
    repeatInfo.textContent = info;
    // 同步移动端隐藏元素（JS仍需要）
    if (mRepeatInfo) mRepeatInfo.textContent = info;
    // 更新移动端顶部状态栏
    if (mTopStatusSentence) {
        mTopStatusSentence.textContent = `${currentIndex + 1}/${segments.length}`;
    }
    if (mTopStatusRepeat) {
        const displayMax = maxRepeat >= 9999 ? "\u221E" : maxRepeat;
        mTopStatusRepeat.textContent = t("mobile.repeat.status", { current: repeatCount + 1, total: displayMax });
    }
}

function delay(ms) {
    return new Promise((r) => setTimeout(r, ms));
}

// ========== 统一波形绘制（剪映式竖条） ==========
// amps: 0..1 振幅数组，每个元素一根竖条，从垂直中心镜像伸展
function drawBars(ctx, w, h, amps, opts) {
    const o = opts || {};
    const color = o.color || "#e94560";
    const gap = (o.gap !== undefined ? o.gap : 1) * (window.devicePixelRatio || 1);
    const barW = (o.barW !== undefined ? o.barW : 2) * (window.devicePixelRatio || 1);
    const minH = 2 * (window.devicePixelRatio || 1);
    if (o.clear !== false) ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = color;
    const step = barW + gap;
    const count = Math.min(amps.length, Math.floor(w / step));
    const cy = h / 2;
    for (let i = 0; i < count; i++) {
        const amp = Math.min(1, Math.max(0, amps[i]));
        const bh = Math.max(minH, amp * h * 0.9);
        const x = i * step;
        // 圆角竖条
        const r = Math.min(barW / 2, bh / 2);
        ctx.beginPath();
        if (ctx.roundRect) {
            ctx.roundRect(x, cy - bh / 2, barW, bh, r);
        } else {
            ctx.rect(x, cy - bh / 2, barW, bh);
        }
        ctx.fill();
    }
}

// 把时域样本（Uint8Array，128 为中心）分桶转为每根竖条的振幅
function timeDomainToAmps(timeDomain, barCount) {
    const amps = new Float32Array(barCount);
    const bucket = Math.max(1, Math.floor(timeDomain.length / barCount));
    for (let i = 0; i < barCount; i++) {
        let sum = 0;
        const base = i * bucket;
        for (let j = 0; j < bucket; j++) {
            const v = (timeDomain[base + j] - 128) / 128;
            sum += v * v;
        }
        // RMS 放大到可视范围
        amps[i] = Math.min(1, Math.sqrt(sum / bucket) * 3);
    }
    return amps;
}

// ========== 跟读功能 ==========
// 更新跟读按钮的文字标签（按钮内含 SVG 图标 + 文字）
function setFrBtnLabel(btn, text) {
    const label = btn.querySelector(".fr-btn-label");
    if (label) label.textContent = text;
}

let frMediaRecorder = null;
let frRecordedChunks = [];
let frRecordedBlob = null;
let frRecordedExt = "webm";
let frRecordingTimer = null;
let frRecordingStart = 0;
let frIsRecording = false;
let frAudioPlayer = null;
let frAudioContext = null;
let frSilenceTimer = null;
let frHasSpoken = false;
let frWaveAnimId = null;
let frShadowMode = false;  // 影子跟读是否正在进行

function openFollowRead() {
    if (currentIndex < 0 || segments.length === 0) return;

    video.pause();
    followReadPanel.style.display = "block";
    mobileControls.classList.add("follow-mode");
    updateFollowReadContent();
}

function updateFollowReadContent() {
    if (currentIndex < 0 || segments.length === 0) return;

    // 停止正在进行的录音
    if (frIsRecording) stopRecording();
    // 停止回放
    if (frAudioPlayer) {
        frAudioPlayer.pause();
        frAudioPlayer = null;
    }

    const seg = segments[currentIndex];
    frReference.textContent = seg.text || "";
    frTranslation.textContent = seg.translation || "";
    frResult.style.display = "none";
    frOverlay.classList.remove("active");
    frTimer.textContent = "";
    btnFrPlayback.disabled = true;
    btnFrScore.disabled = true;
    btnFrPlayback.classList.remove("on");
    setFrBtnLabel(btnFrRecord, t("follow.record"));
    btnFrRecord.classList.remove("on");
    frRecordedBlob = null;
}

function closeFollowRead() {
    stopShadowRead();
    if (frIsRecording) stopRecording();
    if (frAudioPlayer) {
        frAudioPlayer.pause();
        frAudioPlayer = null;
    }
    followReadPanel.style.display = "none";
    frOverlay.classList.remove("active");
    mobileControls.classList.remove("follow-mode");
    // 同步移动端模式 tab 回到默认模式
    if (btnModeFollow && btnModeFollow.classList.contains("active")) {
        switchMode("normal");
    }
}

// ========== 影子跟读 ==========
function toggleShadowRead() {
    if (frShadowMode) {
        stopShadowRead();
    } else {
        startShadowRead();
    }
}

function startShadowRead() {
    if (currentIndex < 0) return;
    // 停止录音
    if (frIsRecording) stopRecording();
    if (frAudioPlayer) { frAudioPlayer.pause(); frAudioPlayer = null; }

    frShadowMode = true;
    setFrBtnLabel(btnFrPlayOriginal, t("follow.stopShadow"));
    btnFrPlayOriginal.classList.add("on");

    // 开始播放当前句
    playShadowSentence();
    // 同步中央播放按钮状态
    syncOverlayPlayState();
    showMobileOverlays();
}

function stopShadowRead() {
    frShadowMode = false;
    setFrBtnLabel(btnFrPlayOriginal, t("follow.playOriginal"));
    btnFrPlayOriginal.classList.remove("on");
    video.pause();
    // 同步中央播放按钮状态
    syncOverlayPlayState();
    showMobileOverlays();
}

function playShadowSentence() {
    if (!frShadowMode || currentIndex < 0) return;
    const seg = segments[currentIndex];
    updateFollowReadContentQuiet();  // 更新面板文字，不重置影子模式
    sentenceMode = true;
    repeatCount = 0;
    // 已经在句首附近时不再 seek，避免二次定位造成开头卡顿
    if (Math.abs(video.currentTime - seg.start) > 0.05) {
        video.currentTime = seg.start;
    }
    video.play();
}

// 只更新面板文字，不影响影子跟读状态
function updateFollowReadContentQuiet() {
    if (currentIndex < 0 || segments.length === 0) return;
    const seg = segments[currentIndex];
    frReference.textContent = seg.text || "";
    frTranslation.textContent = seg.translation || "";
    frResult.style.display = "none";
    frOverlay.classList.remove("active");
    frTimer.textContent = "";
}

// 影子跟读模式下，当前句播完后的回调
function onShadowSentenceEnd() {
    if (!frShadowMode) return;
    if (currentIndex + 1 < segments.length) {
        jumpToSentence(currentIndex + 1);
        playShadowSentence();
    } else {
        // 播完最后一句，回到第一句继续
        jumpToSentence(0);
        playShadowSentence();
    }
}

async function toggleRecording() {
    // 录音时停止影子跟读
    if (frShadowMode) stopShadowRead();

    if (frIsRecording) {
        stopRecording();
    } else {
        await startRecording();
    }
}

async function startRecording() {
    try {
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            alert("录音需要 HTTPS 连接。请使用 https:// 地址访问，或在电脑上用 localhost 测试。");
            return;
        }
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        frRecordedChunks = [];
        frHasSpoken = false;

        // 选择浏览器支持的音频格式（iOS Safari 不支持 webm）
        let mimeType = "audio/webm";
        if (MediaRecorder.isTypeSupported("audio/webm")) {
            mimeType = "audio/webm";
        } else if (MediaRecorder.isTypeSupported("audio/mp4")) {
            mimeType = "audio/mp4";
        } else if (MediaRecorder.isTypeSupported("audio/ogg")) {
            mimeType = "audio/ogg";
        }
        frMediaRecorder = new MediaRecorder(stream, { mimeType });

        frMediaRecorder.ondataavailable = (e) => {
            if (e.data.size > 0) frRecordedChunks.push(e.data);
        };

        frMediaRecorder.onstop = () => {
            // 释放麦克风和音频分析
            stream.getTracks().forEach((tk) => tk.stop());
            stopSilenceDetection();
            frIsRecording = false;
            clearInterval(frRecordingTimer);
            btnFrRecord.classList.remove("on");

            if (frHasSpoken) {
                // 有声音：保存录音，开放回放（评分等回放结束后开放）
                frRecordedBlob = new Blob(frRecordedChunks, { type: mimeType });
                frRecordedExt = mimeType.includes("mp4") ? "mp4" : mimeType.includes("ogg") ? "ogg" : "webm";
                btnFrPlayback.disabled = false;
                setFrBtnLabel(btnFrRecord, t("status.reRecord"));
            } else {
                // 没检测到声音：不保存、不回放、不开放评分
                frRecordedBlob = null;
                btnFrPlayback.disabled = true;
                btnFrScore.disabled = true;
                setFrBtnLabel(btnFrRecord, t("follow.record"));
                frTimer.textContent = t("status.noVoice");
            }
        };

        frMediaRecorder.start();
        frIsRecording = true;
        frRecordingStart = Date.now();
        setFrBtnLabel(btnFrRecord, t("status.stopRecord"));
        btnFrRecord.classList.add("on");
        btnFrPlayback.classList.remove("on");
        btnFrPlayback.disabled = true;
        btnFrScore.disabled = true;
        frResult.style.display = "none";
        frOverlay.classList.remove("active");

        // 显示波形
        frWaveform.classList.add("active");

        // 计时显示
        frRecordingTimer = setInterval(() => {
            const elapsed = ((Date.now() - frRecordingStart) / 1000).toFixed(1);
            frTimer.textContent = t("status.recording", { t: elapsed });
        }, 100);

        // 启动静音检测 + 波形绘制
        startSilenceDetection(stream);

    } catch (e) {
        alert(t("status.micFail") + e.message);
    }
}

function startSilenceDetection(stream) {
    frAudioContext = new (window.AudioContext || window.webkitAudioContext)();
    // iOS Safari 上 AudioContext 默认 suspended，必须 resume
    if (frAudioContext.state === "suspended") {
        frAudioContext.resume();
    }
    const source = frAudioContext.createMediaStreamSource(stream);
    const analyser = frAudioContext.createAnalyser();
    analyser.fftSize = 512;
    source.connect(analyser);

    const dataArray = new Uint8Array(analyser.frequencyBinCount);
    const timeDomain = new Uint8Array(analyser.fftSize);
    const SPEECH_THRESHOLD = 15;
    let silenceStart = null;
    let speechTotal = 0;
    const MIN_SPEECH_TOTAL = 4;
    const MIN_RECORD_MS = 1000;

    // 波形绘制（剪映式竖条）
    const canvas = frWaveform;
    const ctx = canvas.getContext("2d");
    function drawWaveform() {
        if (!frIsRecording) return;
        frWaveAnimId = requestAnimationFrame(drawWaveform);
        analyser.getByteTimeDomainData(timeDomain);
        const dpr = window.devicePixelRatio || 1;
        const w = canvas.width = canvas.clientWidth * dpr;
        const h = canvas.height = canvas.clientHeight * dpr;
        const barCount = Math.floor(w / (3 * dpr));
        drawBars(ctx, w, h, timeDomainToAmps(timeDomain, barCount));
    }
    drawWaveform();

    // 静音检测
    frSilenceTimer = setInterval(() => {
        if (!frIsRecording) return;

        analyser.getByteFrequencyData(dataArray);
        let sum = 0;
        for (let i = 0; i < dataArray.length; i++) sum += dataArray[i];
        const avg = sum / dataArray.length;

        const recordedMs = Date.now() - frRecordingStart;

        if (avg > SPEECH_THRESHOLD) {
            speechTotal++;
            if (speechTotal >= MIN_SPEECH_TOTAL) {
                frHasSpoken = true;
            }
            silenceStart = null;
        } else if (frHasSpoken && recordedMs > MIN_RECORD_MS) {
            if (!silenceStart) {
                silenceStart = Date.now();
            } else if (Date.now() - silenceStart > 600) {
                stopRecording();
            }
        }
    }, 50);
}

function stopSilenceDetection() {
    if (frSilenceTimer) {
        clearInterval(frSilenceTimer);
        frSilenceTimer = null;
    }
    if (frWaveAnimId) {
        cancelAnimationFrame(frWaveAnimId);
        frWaveAnimId = null;
    }
    frWaveform.classList.remove("active");
    if (frAudioContext) {
        frAudioContext.close().catch(() => {});
        frAudioContext = null;
    }
}

function stopRecording() {
    if (frMediaRecorder && frMediaRecorder.state !== "inactive") {
        frMediaRecorder.stop();
    }
    // 没检测到声音时不自动回放（onstop 里会显示提示）
    if (!frHasSpoken) return;

    frTimer.textContent = t("status.recordDone");

    // 录音结束后自动回放（延迟等 blob 生成完）
    setTimeout(() => {
        if (frRecordedBlob) playbackRecording();
    }, 300);
}

function playbackRecording() {
    if (!frRecordedBlob) return;
    if (frAudioPlayer) frAudioPlayer.pause();
    frAudioPlayer = new Audio(URL.createObjectURL(frRecordedBlob));
    btnFrPlayback.classList.add("on");

    // 回放时显示波形 + 进度
    frWaveform.classList.add("active");
    const pbCtx = frWaveform.getContext("2d");
    // 用 Web Audio API 解码录音来绘制回放波形
    const pbAudioCtx = new (window.AudioContext || window.webkitAudioContext)();
    if (pbAudioCtx.state === "suspended") pbAudioCtx.resume();
    const pbSource = pbAudioCtx.createMediaElementSource(frAudioPlayer);
    const pbAnalyser = pbAudioCtx.createAnalyser();
    pbAnalyser.fftSize = 512;
    pbSource.connect(pbAnalyser);
    pbAnalyser.connect(pbAudioCtx.destination);
    const pbTimeDomain = new Uint8Array(pbAnalyser.fftSize);

    let pbAnimId = null;
    function drawPlaybackWave() {
        pbAnimId = requestAnimationFrame(drawPlaybackWave);
        pbAnalyser.getByteTimeDomainData(pbTimeDomain);
        const dpr = window.devicePixelRatio || 1;
        const w = frWaveform.width = frWaveform.clientWidth * dpr;
        const h = frWaveform.height = frWaveform.clientHeight * dpr;
        const barCount = Math.floor(w / (3 * dpr));
        drawBars(pbCtx, w, h, timeDomainToAmps(pbTimeDomain, barCount));

        // 进度时间
        if (frAudioPlayer && frAudioPlayer.duration) {
            const cur = frAudioPlayer.currentTime.toFixed(1);
            const dur = frAudioPlayer.duration.toFixed(1);
            frTimer.textContent = `▶ ${cur}s / ${dur}s`;
        }
    }
    drawPlaybackWave();

    frAudioPlayer.play();
    frAudioPlayer.onended = () => {
        cancelAnimationFrame(pbAnimId);
        pbAudioCtx.close().catch(() => {});
        btnFrPlayback.classList.remove("on");
        frWaveform.classList.remove("active");
        frTimer.textContent = t("status.playbackDone");
        // 回放结束后才开放评分
        btnFrScore.disabled = false;
    };
}

async function submitForScoring() {
    if (!frRecordedBlob || currentIndex < 0) return;

    const seg = segments[currentIndex];
    btnFrScore.disabled = true;
    setFrBtnLabel(btnFrScore, t("status.scoringBtn"));
    frTimer.textContent = t("status.scoring");

    const formData = new FormData();
    formData.append("audio", frRecordedBlob, "recording." + frRecordedExt);
    formData.append("reference_text", seg.text);
    // 语言映射：兼容 Whisper 返回的 ISO code ("th") 和全称 ("Thai")
    const langMap = {
        th: "th-TH", Thai: "th-TH", thai: "th-TH",
        en: "en-US", English: "en-US", english: "en-US",
        ja: "ja-JP", Japanese: "ja-JP", japanese: "ja-JP",
        ko: "ko-KR", Korean: "ko-KR", korean: "ko-KR",
        zh: "zh-CN", Chinese: "zh-CN", chinese: "zh-CN",
        fr: "fr-FR", French: "fr-FR",
        de: "de-DE", German: "de-DE",
        es: "es-ES", Spanish: "es-ES",
        pt: "pt-BR", Portuguese: "pt-BR",
        ru: "ru-RU", Russian: "ru-RU",
        it: "it-IT", Italian: "it-IT",
        vi: "vi-VN", Vietnamese: "vi-VN",
        hi: "hi-IN", Hindi: "hi-IN",
    };
    formData.append("language", langMap[language] || "en-US");

    try {
        const res = await fetch("/api/pronounce", {
            method: "POST",
            body: formData,
        });
        const data = await res.json();

        if (data.error) {
            frTimer.textContent = t("status.scoreFail") + data.error;
            btnFrScore.disabled = false;
            setFrBtnLabel(btnFrScore, t("follow.score"));
            return;
        }

        displayScoreResult(data);
        // 全部 0 分时给出提示
        if ((data.overall_score || 0) === 0 && (data.accuracy_score || 0) === 0) {
            frTimer.textContent = "⚠ " + (data.recognized_text
                ? t("status.scoreFail") + "识别为: " + data.recognized_text
                : t("status.scoreFail") + "未识别到语音，请靠近麦克风重试");
        } else {
            frTimer.textContent = "";
        }
    } catch (e) {
        frTimer.textContent = t("status.scoreFail") + e.message;
    }

    btnFrScore.disabled = false;
    setFrBtnLabel(btnFrScore, t("follow.score"));
}

function displayScoreResult(data) {
    frResult.style.display = "block";
    frOverlay.classList.add("active");

    // 总分
    const score = Math.round(data.overall_score || 0);
    frScoreNum.textContent = score;
    frScoreNum.className = "fr-score-num " + scoreColorClass(score);

    // 细分
    frAccuracy.textContent = Math.round(data.accuracy_score || 0);
    frAccuracy.className = scoreColorClass(data.accuracy_score);
    frFluency.textContent = Math.round(data.fluency_score || 0);
    frFluency.className = scoreColorClass(data.fluency_score);
    frCompleteness.textContent = Math.round(data.completeness_score || 0);
    frCompleteness.className = scoreColorClass(data.completeness_score);

    // 逐词标注
    frWords.innerHTML = "";
    (data.words || []).forEach((w) => {
        const span = document.createElement("span");
        span.className = "fr-word " + wordClass(w);
        span.textContent = w.word;
        span.title = `${w.accuracy_score !== undefined ? Math.round(w.accuracy_score) : ""} ${w.error_type || ""}`;
        frWords.appendChild(span);
    });
}

function scoreColorClass(score) {
    if (score >= 80) return "score-high";
    if (score >= 50) return "score-mid";
    return "score-low";
}

function wordClass(w) {
    if (w.error_type === "Omission") return "missed";
    const s = w.accuracy_score;
    if (s === undefined) return "fair";
    if (s >= 80) return "good";
    if (s >= 50) return "fair";
    return "poor";
}

// ========== 波形音轨编辑器 ==========
let localVideoFile = null; // 本地播放时的 File 对象（供解码音频）

const weOverlay = document.getElementById("weOverlay");
const waveEditor = document.getElementById("waveEditor");
const weCanvas = document.getElementById("weCanvas");
const weStartEl = document.getElementById("weStart");
const weEndEl = document.getElementById("weEnd");
const weSeq = document.getElementById("weSeq");
const weBtnClose = document.getElementById("weBtnClose");
const weBtnPlay = document.getElementById("weBtnPlay");
const weBtnSave = document.getElementById("weBtnSave");
const weBtnRetrans = document.getElementById("weBtnRetrans");
const weEngine = document.getElementById("weEngine");
const weStatus = document.getElementById("weStatus");

const WE_PPS = 50; // 每秒峰值数
let wePeaks = null;
let wePeaksVideoKey = null;

// 编辑器状态
const we = {
    idx: -1,
    viewStart: 0,
    viewEnd: 10,
    start: 0,
    end: 1,
    dragging: null,   // 'start' | 'end' | 'pan' | 'pinch'
    lastX: 0,
    pinch0: null,
    playing: false,
};

// ---- 峰值提取与缓存 ----
async function getPeaks() {
    if (wePeaksVideoKey === currentVideoName && wePeaks) return wePeaks;

    let buf;
    if (localVideoFile && video.src.startsWith("blob:")) {
        buf = await localVideoFile.arrayBuffer();
    } else {
        const res = await fetch(`/videos/${encodeURIComponent(currentVideoName)}`);
        buf = await res.arrayBuffer();
    }

    const AC = window.AudioContext || window.webkitAudioContext;
    const actx = new AC();
    try {
        // 回调形式兼容老 Safari
        const audioBuf = await new Promise((resolve, reject) => {
            actx.decodeAudioData(buf, resolve, reject);
        });
        const ch = audioBuf.getChannelData(0);
        const total = Math.ceil(audioBuf.duration * WE_PPS);
        const win = Math.floor(audioBuf.sampleRate / WE_PPS);
        const peaks = new Float32Array(total);
        for (let i = 0; i < total; i++) {
            let max = 0;
            const base = i * win;
            const end = Math.min(base + win, ch.length);
            for (let j = base; j < end; j += 4) {
                const v = Math.abs(ch[j]);
                if (v > max) max = v;
            }
            peaks[i] = max;
        }
        wePeaks = peaks;
        wePeaksVideoKey = currentVideoName;
        return peaks;
    } finally {
        actx.close().catch(() => {});
    }
}

// ---- 打开/关闭 ----
async function openWaveEditor(i) {
    if (i < 0 || i >= segments.length) return;
    // 进入音轨编辑：停止自动按句播放
    if (frShadowMode) stopShadowRead();
    video.pause();
    const seg = segments[i];
    we.idx = i;
    we.start = seg.start;
    we.end = seg.end;
    we.viewStart = Math.max(0, seg.start - 3);
    we.viewEnd = seg.end + 3;
    we.playing = false;
    weSeq.textContent = `#${i + 1}`;
    weBtnPlay.classList.remove("on");

    weOverlay.style.display = "block";
    waveEditor.style.display = "block";

    weBtnRetrans.disabled = false;
    weStatus.textContent = "";

    weUpdateReadout();
    weRender();

    if (!wePeaks || wePeaksVideoKey !== currentVideoName) {
        weStatus.textContent = t("we.loading");
        try {
            await getPeaks();
            if (we.idx === i) {
                weStatus.textContent = "";
                weRender();
            }
        } catch (e) {
            console.log("[WaveEditor] decode failed:", e);
            if (we.idx === i) weStatus.textContent = t("we.decodeFail");
        }
    }
}

function closeWaveEditor() {
    weStopPreview();
    weOverlay.style.display = "none";
    waveEditor.style.display = "none";
    we.idx = -1;
}

weBtnClose.addEventListener("click", closeWaveEditor);
weOverlay.addEventListener("click", closeWaveEditor);

// ---- 时间与坐标换算 ----
function weFormatTime(tSec) {
    const m = Math.floor(tSec / 60);
    const s = (tSec % 60).toFixed(2);
    return `${m}:${s.padStart(5, "0")}`;
}

function weUpdateReadout() {
    weStartEl.textContent = weFormatTime(we.start);
    weEndEl.textContent = weFormatTime(we.end);
}

function weTimeToX(tSec, w) {
    return ((tSec - we.viewStart) / (we.viewEnd - we.viewStart)) * w;
}

function weXToTime(x, w) {
    return we.viewStart + (x / w) * (we.viewEnd - we.viewStart);
}

// ---- 渲染 ----
function weRender() {
    const dpr = window.devicePixelRatio || 1;
    const w = weCanvas.width = weCanvas.clientWidth * dpr;
    const h = weCanvas.height = weCanvas.clientHeight * dpr;
    const ctx = weCanvas.getContext("2d");

    const span = we.viewEnd - we.viewStart;
    const barW = 2, gap = 1;
    const step = (barW + gap) * dpr;
    const barCount = Math.floor(w / step);

    // 从峰值取每根竖条的振幅
    const amps = new Float32Array(barCount);
    if (wePeaks) {
        for (let b = 0; b < barCount; b++) {
            const t0 = we.viewStart + (b / barCount) * span;
            const t1 = we.viewStart + ((b + 1) / barCount) * span;
            const i0 = Math.floor(t0 * WE_PPS);
            const i1 = Math.max(i0 + 1, Math.ceil(t1 * WE_PPS));
            let max = 0;
            for (let i = Math.max(0, i0); i < i1 && i < wePeaks.length; i++) {
                if (wePeaks[i] > max) max = wePeaks[i];
            }
            amps[b] = Math.min(1, max * 1.5);
        }
    } else {
        amps.fill(0.04);
    }

    // 底层：暗色全部波形
    drawBars(ctx, w, h, amps, { color: "rgba(255,255,255,0.28)", barW, gap });

    // 选中区间内：红色波形（clip 重绘）
    const xs = weTimeToX(we.start, w);
    const xe = weTimeToX(we.end, w);
    ctx.save();
    ctx.beginPath();
    ctx.rect(xs, 0, xe - xs, h);
    ctx.clip();
    drawBars(ctx, w, h, amps, { color: "#e94560", barW, gap, clear: false });
    ctx.restore();

    // 邻句边界虚线
    ctx.setLineDash([4 * dpr, 4 * dpr]);
    ctx.lineWidth = 1 * dpr;
    ctx.strokeStyle = "rgba(255,255,255,0.35)";
    const drawBoundary = (tSec) => {
        if (tSec === null || tSec < we.viewStart || tSec > we.viewEnd) return;
        const x = weTimeToX(tSec, w);
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, h);
        ctx.stroke();
    };
    if (we.idx > 0) drawBoundary(Math.min(segments[we.idx - 1].end, we.start));
    if (we.idx < segments.length - 1) drawBoundary(Math.max(segments[we.idx + 1].start, we.end));
    ctx.setLineDash([]);

    // 选区把手：竖线 + 圆形抓点
    const drawHandle = (x) => {
        ctx.strokeStyle = "#ffd700";
        ctx.lineWidth = 2 * dpr;
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, h);
        ctx.stroke();
        ctx.fillStyle = "#ffd700";
        ctx.beginPath();
        ctx.arc(x, h / 2, 7 * dpr, 0, Math.PI * 2);
        ctx.fill();
        // 抓点内部纹路
        ctx.strokeStyle = "#12122a";
        ctx.lineWidth = 1.5 * dpr;
        ctx.beginPath();
        ctx.moveTo(x - 2 * dpr, h / 2 - 3 * dpr);
        ctx.lineTo(x - 2 * dpr, h / 2 + 3 * dpr);
        ctx.moveTo(x + 2 * dpr, h / 2 - 3 * dpr);
        ctx.lineTo(x + 2 * dpr, h / 2 + 3 * dpr);
        ctx.stroke();
    };
    drawHandle(xs);
    drawHandle(xe);

    // 预览播放头
    if (we.playing && video.currentTime >= we.viewStart && video.currentTime <= we.viewEnd) {
        const px = weTimeToX(video.currentTime, w);
        ctx.strokeStyle = "#fff";
        ctx.lineWidth = 1.5 * dpr;
        ctx.beginPath();
        ctx.moveTo(px, 0);
        ctx.lineTo(px, h);
        ctx.stroke();
    }
}

// ---- 触摸交互：拖把手 / 平移 / 双指缩放 ----
function weTouchDist(touches) {
    const dx = touches[0].clientX - touches[1].clientX;
    const dy = touches[0].clientY - touches[1].clientY;
    return Math.sqrt(dx * dx + dy * dy);
}

function weCanvasX(clientX) {
    const rect = weCanvas.getBoundingClientRect();
    return clientX - rect.left;
}

function wePointerDown(clientX) {
    const w = weCanvas.clientWidth;
    const x = weCanvasX(clientX);
    const xs = weTimeToX(we.start, w);
    const xe = weTimeToX(we.end, w);
    if (Math.abs(x - xs) < 24) {
        we.dragging = "start";
    } else if (Math.abs(x - xe) < 24) {
        we.dragging = "end";
    } else {
        we.dragging = "pan";
        we.lastX = x;
    }
}

function wePointerMove(clientX) {
    const w = weCanvas.clientWidth;
    const x = weCanvasX(clientX);
    const span = we.viewEnd - we.viewStart;

    if (we.dragging === "start") {
        let tSec = weXToTime(x, w);
        // 下限：上一句的开头 +0.2（可以越过上一句 end，联动收缩上一句）
        const lower = we.idx > 0 ? segments[we.idx - 1].start + 0.2 : 0;
        tSec = Math.max(lower, Math.min(tSec, we.end - 0.2));
        we.start = Math.round(tSec * 100) / 100;
        weUpdateReadout();
        weRender();
    } else if (we.dragging === "end") {
        let tSec = weXToTime(x, w);
        // 上限：下一句的结尾 -0.2（可以越过下一句 start，联动推移下一句）
        const upper = we.idx < segments.length - 1
            ? segments[we.idx + 1].end - 0.2
            : (video.duration || tSec + 10);
        tSec = Math.min(upper, Math.max(tSec, we.start + 0.2));
        we.end = Math.round(tSec * 100) / 100;
        weUpdateReadout();
        weRender();
    } else if (we.dragging === "pan") {
        const dt = ((we.lastX - x) / w) * span;
        let vs = we.viewStart + dt;
        if (vs < 0) vs = 0;
        we.viewStart = vs;
        we.viewEnd = vs + span;
        we.lastX = x;
        weRender();
    }
}

weCanvas.addEventListener("touchstart", (e) => {
    e.preventDefault();
    if (e.touches.length === 2) {
        const midX = weCanvasX((e.touches[0].clientX + e.touches[1].clientX) / 2);
        const w = weCanvas.clientWidth;
        we.dragging = "pinch";
        we.pinch0 = {
            dist: weTouchDist(e.touches),
            span: we.viewEnd - we.viewStart,
            centerTime: weXToTime(midX, w),
            centerRatio: midX / w,
        };
        return;
    }
    wePointerDown(e.touches[0].clientX);
}, { passive: false });

weCanvas.addEventListener("touchmove", (e) => {
    e.preventDefault();
    if (we.dragging === "pinch" && e.touches.length === 2 && we.pinch0) {
        const d = weTouchDist(e.touches);
        let newSpan = we.pinch0.span * (we.pinch0.dist / d);
        newSpan = Math.max(1, Math.min(60, newSpan));
        let vs = we.pinch0.centerTime - newSpan * we.pinch0.centerRatio;
        if (vs < 0) vs = 0;
        we.viewStart = vs;
        we.viewEnd = vs + newSpan;
        weRender();
        return;
    }
    if (e.touches.length === 1) wePointerMove(e.touches[0].clientX);
}, { passive: false });

weCanvas.addEventListener("touchend", () => {
    we.dragging = null;
    we.pinch0 = null;
});

// 桌面鼠标支持
weCanvas.addEventListener("mousedown", (e) => {
    e.preventDefault();
    wePointerDown(e.clientX);
    const onMove = (ev) => wePointerMove(ev.clientX);
    const onUp = () => {
        we.dragging = null;
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
});

// 桌面滚轮缩放
weCanvas.addEventListener("wheel", (e) => {
    e.preventDefault();
    const w = weCanvas.clientWidth;
    const x = weCanvasX(e.clientX);
    const centerTime = weXToTime(x, w);
    const ratio = x / w;
    const span = we.viewEnd - we.viewStart;
    let newSpan = span * (e.deltaY > 0 ? 1.2 : 0.8);
    newSpan = Math.max(1, Math.min(60, newSpan));
    let vs = centerTime - newSpan * ratio;
    if (vs < 0) vs = 0;
    we.viewStart = vs;
    we.viewEnd = vs + newSpan;
    weRender();
}, { passive: false });

// ---- 试听预览 ----
function wePreview() {
    if (we.playing) {
        weStopPreview();
        return;
    }
    we.playing = true;
    weBtnPlay.classList.add("on");
    setFrBtnLabelWe(weBtnPlay, t("we.stop"));
    sentenceMode = false; // 暂停按句复读逻辑
    video.currentTime = we.start;
    video.play();
}

function weStopPreview() {
    if (!we.playing) return;
    we.playing = false;
    weBtnPlay.classList.remove("on");
    setFrBtnLabelWe(weBtnPlay, t("we.play"));
    video.pause();
    sentenceMode = true;
}

function setFrBtnLabelWe(btn, text) {
    const label = btn.querySelector(".we-btn-label");
    if (label) label.textContent = text;
}

video.addEventListener("timeupdate", () => {
    if (we.playing) {
        if (video.currentTime >= we.end) {
            weStopPreview();
        }
        weRender();
    }
});

weBtnPlay.addEventListener("click", wePreview);

// ---- 保存 ----
weBtnSave.addEventListener("click", async () => {
    const i = we.idx;
    if (i < 0) return;
    const seg = segments[i];
    seg.start = we.start;
    seg.end = we.end;
    // 跨句联动：消除与邻句的重叠
    if (i > 0 && segments[i - 1].end > seg.start) {
        segments[i - 1].end = Math.max(segments[i - 1].start + 0.1, seg.start);
    }
    if (i < segments.length - 1 && segments[i + 1].start < seg.end) {
        segments[i + 1].start = Math.min(segments[i + 1].end - 0.1, seg.end);
    }
    renderSentenceList();
    highlightSentence(currentIndex);
    updateRepeatInfo(parseInt(repeatCountSelect.value) || 3);
    weStatus.textContent = t("we.saved");
    await saveSubtitle();
});

// ---- 二次识别 ----
weBtnRetrans.addEventListener("click", async () => {
    if (we.idx < 0 || weBtnRetrans.disabled) return;
    weBtnRetrans.disabled = true;
    weStatus.textContent = t("we.recognizing");

    const langNameMap = { th: "泰语", en: "英语", ja: "日语", ko: "韩语", fr: "法语", de: "德语", es: "西班牙语", pt: "葡萄牙语", ru: "俄语", it: "意大利语" };
    const shortLang = (language || "").slice(0, 2).toLowerCase();

    const isLocal = video.src.startsWith("blob:") && localVideoFile;

    try {
        let res;
        if (isLocal) {
            // 本地视频：客户端切音频编码 WAV 上传识别
            const wavBlob = await getLocalAudioSliceWav(we.start, we.end);
            const formData = new FormData();
            formData.append("audio", wavBlob, "slice.wav");
            formData.append("provider", weEngine.value);
            formData.append("translate", "true");
            formData.append("language", shortLang);
            formData.append("source_lang", langNameMap[shortLang] || "外语");
            res = await fetch("/api/retranscribe-audio", {
                method: "POST",
                body: formData,
            });
        } else {
            // 服务器视频：后端直接切片
            res = await fetch("/api/retranscribe", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    video: currentVideoName,
                    start: we.start,
                    end: we.end,
                    provider: weEngine.value,
                    translate: true,
                    language: shortLang,
                    source_lang: langNameMap[shortLang] || "外语",
                }),
            });
        }
        const data = await res.json();
        if (data.error) {
            weStatus.textContent = "❌ " + data.error;
            return;
        }
        const seg = segments[we.idx];
        if (data.text) seg.text = data.text;
        if (data.translation) seg.translation = data.translation;
        renderSentenceList();
        if (we.idx === currentIndex) updateSubtitle(seg);
        weStatus.textContent = "✓ " + (data.text || "");
        await saveSubtitle();
    } catch (e) {
        weStatus.textContent = "❌ " + e.message;
    } finally {
        weBtnRetrans.disabled = false;
    }
});

// ---- 本地视频：客户端切音频并编码 WAV（供二次识别上传） ----
async function getLocalAudioSliceWav(startSec, endSec) {
    const buf = await localVideoFile.arrayBuffer();
    const AC = window.AudioContext || window.webkitAudioContext;
    const actx = new AC();
    try {
        const audioBuf = await new Promise((resolve, reject) => {
            actx.decodeAudioData(buf, resolve, reject);
        });
        const sr = audioBuf.sampleRate;
        const ch = audioBuf.getChannelData(0);
        const i0 = Math.max(0, Math.floor(startSec * sr));
        const i1 = Math.min(ch.length, Math.ceil(endSec * sr));
        const slice = ch.subarray(i0, i1);

        // 编码 16-bit PCM WAV（单声道，原采样率，后端会再转 16k）
        const dataLen = slice.length * 2;
        const wav = new ArrayBuffer(44 + dataLen);
        const dv = new DataView(wav);
        const writeStr = (off, s) => { for (let i = 0; i < s.length; i++) dv.setUint8(off + i, s.charCodeAt(i)); };
        writeStr(0, "RIFF");
        dv.setUint32(4, 36 + dataLen, true);
        writeStr(8, "WAVE");
        writeStr(12, "fmt ");
        dv.setUint32(16, 16, true);
        dv.setUint16(20, 1, true);       // PCM
        dv.setUint16(22, 1, true);       // mono
        dv.setUint32(24, sr, true);
        dv.setUint32(28, sr * 2, true);  // byte rate
        dv.setUint16(32, 2, true);       // block align
        dv.setUint16(34, 16, true);      // bits
        writeStr(36, "data");
        dv.setUint32(40, dataLen, true);
        let off = 44;
        for (let i = 0; i < slice.length; i++) {
            const v = Math.max(-1, Math.min(1, slice[i]));
            dv.setInt16(off, v < 0 ? v * 0x8000 : v * 0x7FFF, true);
            off += 2;
        }
        return new Blob([wav], { type: "audio/wav" });
    } finally {
        actx.close().catch(() => {});
    }
}

// 启动时加载本地视频列表（必须在所有声明之后执行）
loadLocalVideoList();
