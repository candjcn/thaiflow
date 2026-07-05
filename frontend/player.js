// ========== i18n 初始化 ==========
I18N.init();
document.querySelectorAll(".lang-switcher-btn").forEach(btn => {
    btn.addEventListener("click", () => {
        I18N.setLang(btn.dataset.lang);
    });
});

// ========== 获取用户翻译目标语言 ==========
function getTargetLang() {
    // 根据用户浏览器语言 / UI 语言决定字幕翻译成什么语言
    const lang = navigator.language || navigator.userLanguage || "zh-CN";
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
const frResult = document.getElementById("frResult");
const frScoreNum = document.getElementById("frScoreNum");
const frAccuracy = document.getElementById("frAccuracy");
const frFluency = document.getElementById("frFluency");
const frCompleteness = document.getElementById("frCompleteness");
const frWords = document.getElementById("frWords");
const videoUrlInput = document.getElementById("videoUrlInput");
const btnDownloadUrl = document.getElementById("btnDownloadUrl");
const urlStatus = document.getElementById("urlStatus");
const fileUpload = document.getElementById("fileUpload");
const uploadStatus = document.getElementById("uploadStatus");
const btnBrowseDir = document.getElementById("btnBrowseDir");
const dirBrowser = document.getElementById("dirBrowser");
const dirCurrent = document.getElementById("dirCurrent");
const dirList = document.getElementById("dirList");
const btnDirUp = document.getElementById("btnDirUp");
const btnDirSelect = document.getElementById("btnDirSelect");
const btnDirCancel = document.getElementById("btnDirCancel");

// ========== 初始化 ==========
loadVideoList();

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
document.getElementById("btnSaveLocal").addEventListener("click", saveToLocal);
btnDownloadUrl.addEventListener("click", downloadFromUrl);
fileUpload.addEventListener("change", uploadVideo);
document.getElementById("localFiles").addEventListener("change", openLocalFiles);
btnFrClose.addEventListener("click", closeFollowRead);
btnFrPlayOriginal.addEventListener("click", toggleShadowRead);
btnFrRecord.addEventListener("click", toggleRecording);
btnFrPlayback.addEventListener("click", playbackRecording);
btnFrScore.addEventListener("click", submitForScoring);
btnCloseDrawer.addEventListener("click", () => {
    sentenceDrawer.style.display = "none";
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
mBtnFullscreen.addEventListener("click", () => {
    if (document.fullscreenElement || document.webkitFullscreenElement) {
        (document.exitFullscreen || document.webkitExitFullscreen).call(document).catch(() => {});
    } else {
        const el = document.documentElement;
        if (el.requestFullscreen) {
            el.requestFullscreen({ navigationUI: "hide" }).catch(() => {});
        } else if (el.webkitRequestFullscreen) {
            el.webkitRequestFullscreen();
        }
    }
});

// 同步全屏按钮图标状态
document.addEventListener("fullscreenchange", () => {
    mBtnFullscreen.classList.toggle("is-fullscreen", !!document.fullscreenElement);
});
document.addEventListener("webkitfullscreenchange", () => {
    mBtnFullscreen.classList.toggle("is-fullscreen", !!document.webkitFullscreenElement);
});

// Overlay controls: play/pause, prev, next
mCenterPlayBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    togglePause();
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

function switchMode(mode) {
    [btnModeStudy, btnModeFollow].forEach(b => b.classList.remove("active"));
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
        mModeBg.dataset.pos = "1";
        openFollowRead();
    }
}

// 移动端判断
function isMobile() {
    return window.innerWidth <= 768;
}

// 进入播放界面时自动全屏（移动端）
function tryMobileFullscreen() {
    if (!isMobile()) return;
    const el = document.documentElement; // 全屏整个页面，确保覆盖浏览器 UI
    if (el.requestFullscreen) {
        el.requestFullscreen({ navigationUI: "hide" }).catch(() => {});
    } else if (el.webkitRequestFullscreen) {
        el.webkitRequestFullscreen();
    }
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
    if (video.paused) {
        mCenterPlayBtn.classList.add("paused");
        mCenterPlayBtn.classList.remove("playing");
    } else {
        mCenterPlayBtn.classList.add("playing");
        mCenterPlayBtn.classList.remove("paused");
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
    if (window.innerWidth <= 768) {
        // 移动端：点击视频直接暂停/播放
        togglePause();
        showMobileOverlays();
        return;
    }
    togglePause();
});

// 键盘快捷键
document.addEventListener("keydown", (e) => {
    if (phasePlay.style.display === "none") return;
    if (e.target.tagName === "SELECT" || e.target.tagName === "INPUT") return;

    switch (e.code) {
        case "Space":
            e.preventDefault();
            togglePause();
            break;
        case "ArrowLeft":
            e.preventDefault();
            prevSentence();
            break;
        case "ArrowRight":
            e.preventDefault();
            nextSentence();
            break;
        case "KeyR":
            e.preventDefault();
            repeatCurrent();
            break;
        case "KeyF":
            e.preventDefault();
            toggleFullscreen();
            break;
    }
});

// 同步暂停按钮文字
video.addEventListener("play", () => { btnPause.textContent = "⏸"; });
video.addEventListener("pause", () => {
    if (!isLoading) btnPause.textContent = "▶";
});

// 字幕宽度跟随视频实际渲染宽度
function updateSubtitleWidth() {
    if (video.videoWidth === 0) return;
    const videoRect = video.getBoundingClientRect();
    const containerRect = videoContainer.getBoundingClientRect();
    const videoDisplayWidth = videoRect.width;
    subtitleOverlay.style.width = (videoDisplayWidth * 0.92) + "px";
    // 确保字幕水平居中于视频而非容器
    const videoLeft = videoRect.left - containerRect.left;
    const videoCenter = videoLeft + videoDisplayWidth / 2;
    const containerCenter = containerRect.width / 2;
    const offset = videoCenter - containerCenter;
    subtitleOverlay.style.left = `calc(50% + ${offset}px)`;
}

video.addEventListener("loadedmetadata", updateSubtitleWidth);
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
    if (!document.fullscreenElement) {
        const el = document.documentElement;
        if (el.requestFullscreen) {
            el.requestFullscreen({ navigationUI: "hide" }).catch(() => {});
        } else if (el.webkitRequestFullscreen) {
            el.webkitRequestFullscreen();
        }
    } else {
        document.exitFullscreen();
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
const btnAddVideo = document.getElementById("btnAddVideo");
const addVideoContent = document.getElementById("addVideoContent");

btnAddVideo.addEventListener("click", () => {
    const isOpen = addVideoContent.style.display !== "none";
    addVideoContent.style.display = isOpen ? "none" : "block";
    btnAddVideo.textContent = isOpen ? t("app.add.toggle") : t("app.add.collapse");
});

async function loadVideoList() {
    try {
        const res = await fetch("/api/videos");
        const data = await res.json();
        videoListEl.innerHTML = "";

        if (data.videos.length === 0) {
            myVideosSection.style.display = "none";
            // 没有视频时自动展开添加区域
            addVideoContent.style.display = "block";
            btnAddVideo.textContent = t("app.add.collapse");
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

// ========== 保存到本地 ==========
// subtitleOnly: 为 true 时只下载字幕（用户本地已有视频文件时）
function saveToLocal(subtitleOnly) {
    if (!currentVideoName || segments.length === 0) return;

    if (!subtitleOnly) {
        // 下载视频文件
        const videoLink = document.createElement("a");
        videoLink.href = `/videos/${encodeURIComponent(currentVideoName)}`;
        videoLink.download = currentVideoName;
        videoLink.click();
    }

    // 下载字幕 JSON 文件
    const subtitleData = JSON.stringify({ segments, language }, null, 2);
    const blob = new Blob([subtitleData], { type: "application/json" });
    const subLink = document.createElement("a");
    subLink.href = URL.createObjectURL(blob);
    const baseName = currentVideoName.replace(/\.[^.]+$/, "");
    subLink.download = baseName + ".json";
    // 延迟一点触发下载（如果同时下载视频，需要错开避免被浏览器拦截）
    setTimeout(() => subLink.click(), subtitleOnly ? 0 : 500);
}

// ========== 打开本地文件（直接播放，不上传） ==========
async function openLocalFiles() {
    const input = document.getElementById("localFiles");
    const files = Array.from(input.files);
    if (files.length === 0) return;

    let videoFile = null;
    let subtitleFile = null;

    for (const f of files) {
        if (f.type.startsWith("video/") || f.name.toLowerCase().endsWith(".mp4")) {
            videoFile = f;
        } else if (f.name.toLowerCase().endsWith(".json")) {
            subtitleFile = f;
        }
    }

    if (!videoFile) {
        alert(t("status.selectVideo"));
        return;
    }

    // 切换到播放界面
    currentVideoName = videoFile.name;

    // 先隐藏所有遮罩，再显示播放界面，避免一闪而过
    loadingOverlay.style.display = "none";
    exportOverlay.style.display = "none";
    followReadPanel.style.display = "none";

    phaseSelect.style.display = "none";
    phasePlay.style.display = "flex";
    tryMobileFullscreen();

    // 用本地 URL 播放视频（不上传）
    const videoUrl = URL.createObjectURL(videoFile);
    video.src = videoUrl;
    video.load();

    if (subtitleFile) {

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
    } else {
        // 没有字幕文件，需要上传到服务器识别，显示加载遮罩
        isLoading = true;
        loadingOverlay.style.display = "flex";
        setStep("step1", "active");
        setTip(t("status.uploadingServer"));

        const formData = new FormData();
        formData.append("video", videoFile);
        try {
            const res = await fetch("/api/upload-video", { method: "POST", body: formData });
            const data = await res.json();
            if (data.error) {
                setStep("step2", "error");
                setTip(t("status.uploadFail") + data.error);
                return;
            }
            currentVideoName = data.name;
            // 用服务器的视频地址替换本地 URL（确保后续跟读等功能正常）
            video.src = `/videos/${encodeURIComponent(data.name)}`;
            video.load();
            await waitForVideo();
        } catch (e) {
            setStep("step2", "error");
            setTip(t("status.uploadFail") + e.message);
            return;
        }

        // 继续走识别翻译流程
        const provider = transcribeProvider.value;
        setStep("step2", "active");
        setTip(t("status.recognizing"));
        try {
            const segTarget = segmentTarget.value || null;
            const res = await fetch("/api/transcribe", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ video: currentVideoName, provider, segment_target: segTarget }),
            });
            const data = await res.json();
            if (data.error) { setStep("step2", "error"); setTip(t("status.recognizeFail") + data.error); return; }
            segments = data.segments || [];
            language = data.language || "";
            setStep("step2", "done");
        } catch (e) { setStep("step2", "error"); setTip(t("status.recognizeFail") + e.message); return; }

        setStep("step3", "active");
        setTip(t("status.translating"));
        const langMap = { th: "泰语", en: "英语", ja: "日语", ko: "韩语", fr: "法语", de: "德语", es: "西班牙语", pt: "葡萄牙语", ru: "俄语", it: "意大利语" };
        const sourceLang = langMap[language] || "外语";
        try {
            const res = await fetch("/api/translate", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ segments: segments.map(s => ({ index: s.index, text: s.text })), source_lang: sourceLang, target_lang: getTargetLang() }),
            });
            const data = await res.json();
            if (!data.error) {
                (data.translations || []).forEach(tr => { if (segments[tr.index]) segments[tr.index].translation = tr.translation; });
            }
            setStep("step3", "done");
            setTip(t("status.allReady"));
        } catch (e) { setStep("step3", "error"); setTip(t("status.translateFail") + e.message); }

        await saveSubtitle();
        await delay(500);
        finishLoading();

        // 用户本地已有视频文件，只需下载字幕
        saveToLocal(true);
    }

    input.value = "";
}

// ========== 上传视频到服务器识别 ==========
async function uploadVideo() {
    const file = fileUpload.files[0];
    if (!file) return;

    uploadStatus.textContent = t("status.uploading");
    uploadStatus.className = "upload-status";

    const formData = new FormData();
    formData.append("video", file);

    try {
        const res = await fetch("/api/upload-video", {
            method: "POST",
            body: formData,
        });
        const data = await res.json();

        if (data.error) {
            uploadStatus.textContent = t("status.uploadFail") + data.error;
            uploadStatus.className = "upload-status error";
            return;
        }

        uploadStatus.textContent = t("status.uploadSuccess") + data.name;
        uploadStatus.className = "upload-status success";

        await loadVideoList();
        fileUpload.value = "";
        startLoading(data.name);
    } catch (e) {
        uploadStatus.textContent = t("status.uploadFail") + e.message;
        uploadStatus.className = "upload-status error";
    }
}

// ========== 显示播放界面并加载视频首帧 ==========
function showPlayerWithVideo(videoName) {
    currentVideoName = videoName;
    isLoading = true;

    // 切换到播放界面
    phaseSelect.style.display = "none";
    phasePlay.style.display = "flex";
    tryMobileFullscreen();

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
}

// ========== 完整加载流程 ==========
async function startLoading(videoName) {
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

    // 处理完成后自动下载视频+字幕到本地
    saveToLocal();
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
    if (document.fullscreenElement) {
        document.exitFullscreen().catch(() => {});
    }
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
        div.innerHTML = `
            <span class="seq">${i + 1}</span>
            <div class="text-group">
                <div class="time">${formatTime(seg.start)} - ${formatTime(seg.end)}</div>
                <div class="original">${escapeHtml(seg.text)}</div>
                <div class="translation">${escapeHtml(seg.translation || "")}</div>
            </div>
        `;
        div.addEventListener("click", () => {
            sentenceMode = true;
            jumpToSentence(i);
            video.play();
        });
        sentenceList.appendChild(div);
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
                // 整个视频循环：回到第一句重新开始
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
        // 手动切句时停止影子跟读
        if (frShadowMode) stopShadowRead();
        sentenceMode = true;
        jumpToSentence(currentIndex - 1);
        video.play();
    }
}

function nextSentence() {
    if (currentIndex < segments.length - 1) {
        if (frShadowMode) stopShadowRead();
        sentenceMode = true;
        jumpToSentence(currentIndex + 1);
        video.play();
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

function updateSubtitle(seg) {
    subtitleOriginal.textContent = seg.text || "";
    subtitleTranslation.textContent = seg.translation || "";
    // 调试：确认翻译数据
    if (!seg.translation) {
        console.warn("字幕缺少翻译:", seg.index, seg.text);
    }
    updateSubtitleVisibility();
}

function clearSubtitle() {
    subtitleOriginal.textContent = "";
    subtitleTranslation.textContent = "";
}

function updateSubtitleVisibility() {
    const mode = getSubtitleMode();
    if (mode === "none") {
        subtitleOriginal.style.display = "none";
        subtitleTranslation.style.display = "none";
    } else if (mode === "original") {
        subtitleOriginal.style.display = "inline-block";
        subtitleTranslation.style.display = "none";
    } else {
        subtitleOriginal.style.display = "inline-block";
        subtitleTranslation.style.display = "inline-block";
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

// ========== 跟读功能 ==========
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
    frTimer.textContent = "";
    btnFrPlayback.disabled = true;
    btnFrScore.disabled = true;
    btnFrRecord.textContent = t("follow.record");
    btnFrRecord.classList.remove("recording");
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
    btnFrPlayOriginal.textContent = t("follow.stopShadow");
    btnFrPlayOriginal.classList.add("shadow-active");

    // 开始播放当前句
    playShadowSentence();
}

function stopShadowRead() {
    frShadowMode = false;
    btnFrPlayOriginal.textContent = t("follow.playOriginal");
    btnFrPlayOriginal.classList.remove("shadow-active");
    video.pause();
}

function playShadowSentence() {
    if (!frShadowMode || currentIndex < 0) return;
    const seg = segments[currentIndex];
    updateFollowReadContentQuiet();  // 更新面板文字，不重置影子模式
    sentenceMode = true;
    repeatCount = 0;
    video.currentTime = seg.start;
    video.play();
}

// 只更新面板文字，不影响影子跟读状态
function updateFollowReadContentQuiet() {
    if (currentIndex < 0 || segments.length === 0) return;
    const seg = segments[currentIndex];
    frReference.textContent = seg.text || "";
    frTranslation.textContent = seg.translation || "";
    frResult.style.display = "none";
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
            frRecordedBlob = new Blob(frRecordedChunks, { type: mimeType });
            // 保存实际格式的扩展名
            frRecordedExt = mimeType.includes("mp4") ? "mp4" : mimeType.includes("ogg") ? "ogg" : "webm";
            btnFrPlayback.disabled = false;
            btnFrScore.disabled = false;
            frIsRecording = false;
            clearInterval(frRecordingTimer);
            btnFrRecord.textContent = t("status.reRecord");
            btnFrRecord.classList.remove("recording");
        };

        frMediaRecorder.start();
        frIsRecording = true;
        frRecordingStart = Date.now();
        btnFrRecord.textContent = t("status.stopRecord");
        btnFrRecord.classList.add("recording");
        frResult.style.display = "none";

        // 计时显示
        frRecordingTimer = setInterval(() => {
            const elapsed = ((Date.now() - frRecordingStart) / 1000).toFixed(1);
            frTimer.textContent = t("status.recording", { t: elapsed });
        }, 100);

        // 启动静音检测：用户说完话后自动停止录音并回放
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
    const SPEECH_THRESHOLD = 15;   // 低阈值，确保能检测到语音
    let silenceStart = null;
    let speechTotal = 0;           // 累计检测到语音的帧数（不要求连续）
    const MIN_SPEECH_TOTAL = 4;    // 累计 4 帧(200ms)算开过口
    const MIN_RECORD_MS = 1000;    // 最短录音 1 秒

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
            // 已经说过话、且录够最短时长，开始静音计时
            if (!silenceStart) {
                silenceStart = Date.now();
            } else if (Date.now() - silenceStart > 600) {
                // 静音超过 0.6 秒，自动停止并回放
                stopRecording(true);
            }
        }
    }, 50);
}

function stopSilenceDetection() {
    if (frSilenceTimer) {
        clearInterval(frSilenceTimer);
        frSilenceTimer = null;
    }
    if (frAudioContext) {
        frAudioContext.close().catch(() => {});
        frAudioContext = null;
    }
}

function stopRecording(autoPlayback) {
    if (frMediaRecorder && frMediaRecorder.state !== "inactive") {
        frMediaRecorder.stop();
    }
    frTimer.textContent = t("status.recordDone");

    // 自动停止时，延迟一点等 blob 生成完再回放
    if (autoPlayback) {
        setTimeout(() => {
            if (frRecordedBlob) playbackRecording();
        }, 300);
    }
}

function playbackRecording() {
    if (!frRecordedBlob) return;
    if (frAudioPlayer) frAudioPlayer.pause();
    frAudioPlayer = new Audio(URL.createObjectURL(frRecordedBlob));
    frAudioPlayer.play();
}

async function submitForScoring() {
    if (!frRecordedBlob || currentIndex < 0) return;

    const seg = segments[currentIndex];
    btnFrScore.disabled = true;
    btnFrScore.textContent = t("status.scoringBtn");
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
            btnFrScore.textContent = t("follow.score");
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
    btnFrScore.textContent = t("follow.score");
}

function displayScoreResult(data) {
    frResult.style.display = "block";

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
