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
btnDownloadUrl.addEventListener("click", downloadFromUrl);
btnFrClose.addEventListener("click", closeFollowRead);
btnFrPlayOriginal.addEventListener("click", playOriginalSentence);
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

video.addEventListener("timeupdate", () => {
    onTimeUpdate();
    updateTimeDisplay();
});

// 点击视频区域暂停/播放
videoContainer.addEventListener("click", (e) => {
    // 不在加载中，不是点击控件区域
    if (isLoading) return;
    if (e.target.closest(".subtitle-overlay")) return;
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
        phasePlay.requestFullscreen().catch(() => {});
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
async function loadVideoList() {
    try {
        const res = await fetch("/api/videos");
        const data = await res.json();
        videoListEl.innerHTML = "";
        if (data.videos.length === 0) {
            videoListEl.innerHTML = '<p class="placeholder">videos 目录下没有 MP4 文件</p>';
            return;
        }
        data.videos.forEach((v) => {
            const item = document.createElement("div");
            item.className = "video-item";

            const name = document.createElement("span");
            name.className = "video-name";
            name.textContent = v.name;

            const actions = document.createElement("div");
            actions.className = "video-actions";

            if (v.has_subtitle) {
                const btnPlay = document.createElement("button");
                btnPlay.textContent = "播放学习";
                btnPlay.className = "btn-play";
                btnPlay.addEventListener("click", () => loadSaved(v.name));

                const btnRedo = document.createElement("button");
                btnRedo.textContent = "重新识别";
                btnRedo.className = "btn-redo";
                btnRedo.addEventListener("click", () => startLoading(v.name));

                actions.appendChild(btnPlay);
                actions.appendChild(btnRedo);
            } else {
                const btnNew = document.createElement("button");
                btnNew.textContent = "识别翻译";
                btnNew.className = "btn-new";
                btnNew.addEventListener("click", () => startLoading(v.name));
                actions.appendChild(btnNew);
            }

            item.appendChild(name);
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
        urlStatus.textContent = "请输入视频链接";
        urlStatus.className = "url-status error";
        return;
    }

    btnDownloadUrl.disabled = true;
    btnDownloadUrl.textContent = "下载中...";
    urlStatus.textContent = "正在获取视频信息...";
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
        urlStatus.textContent = "下载失败: " + e.message;
        urlStatus.className = "url-status error";
    }

    btnDownloadUrl.disabled = false;
    btnDownloadUrl.textContent = "下载";
}

// 回车键触发下载
videoUrlInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") downloadFromUrl();
});

// ========== 显示播放界面并加载视频首帧 ==========
function showPlayerWithVideo(videoName) {
    currentVideoName = videoName;
    isLoading = true;

    // 切换到播放界面
    phaseSelect.style.display = "none";
    phasePlay.style.display = "flex";

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
    showPlayerWithVideo(videoName);

    setStep("step1", "active");
    setTip("正在加载视频...");

    await waitForVideo();
    setStep("step1", "done");

    setStep("step2", "done");
    setStep("step3", "active");
    setTip("正在读取已保存的字幕...");

    try {
        const res = await fetch(`/api/subtitle/${encodeURIComponent(videoName)}`);
        const data = await res.json();
        segments = data.segments || [];
        language = data.language || "";
        setStep("step3", "done");
        setTip("就绪！");
    } catch (e) {
        setStep("step3", "error");
        setTip("字幕读取失败: " + e.message);
        return;
    }

    await delay(400);
    finishLoading();
}

// ========== 完整加载流程 ==========
async function startLoading(videoName) {
    showPlayerWithVideo(videoName);

    // 步骤 1：加载视频
    setStep("step1", "active");
    setTip("正在加载视频文件...");
    await waitForVideo();
    setStep("step1", "done");

    // 步骤 2：语音识别
    const provider = transcribeProvider.value;
    const providerLabels = {
        groq: "Groq Whisper",
        azure: "Azure Speech",
        combined: "Groq + Azure 智能校准",
    };
    const providerLabel = providerLabels[provider] || provider;
    setStep("step2", "active");
    setTip(`正在调用 ${providerLabel} 语音识别，将音频自动断句...`);
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
            setTip("识别失败: " + data.error);
            return;
        }
        segments = data.segments || [];
        language = data.language || "";
        setStep("step2", "done");
        setTip(`识别完成，共 ${segments.length} 句`);
    } catch (e) {
        setStep("step2", "error");
        setTip("识别失败: " + e.message);
        return;
    }

    // 步骤 3：翻译
    setStep("step3", "active");
    setTip("正在翻译字幕为中文...");
    const langMap = { th: "泰语", Thai: "泰语", en: "英语", English: "英语", ja: "日语", ko: "韩语" };
    const sourceLang = langMap[language] || "泰语";
    try {
        const res = await fetch("/api/translate", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                segments: segments.map((s) => ({ index: s.index, text: s.text })),
                source_lang: sourceLang,
            }),
        });
        const data = await res.json();
        if (data.error) {
            setStep("step3", "error");
            setTip("翻译失败: " + data.error + "（可稍后手动重试）");
        } else {
            (data.translations || []).forEach((t) => {
                if (segments[t.index]) segments[t.index].translation = t.translation;
            });
            setStep("step3", "done");
            setTip("全部就绪！");
        }
    } catch (e) {
        setStep("step3", "error");
        setTip("翻译失败: " + e.message + "（可稍后手动重试）");
    }

    // 保存字幕
    await saveSubtitle();

    await delay(500);
    finishLoading();
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
            setTip("视频加载失败");
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
            // 手机端点击后关闭列表，电脑端保持打开
            if (window.innerWidth <= 768) {
                sentenceDrawer.style.display = "none";
            }
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
}

function prevSentence() {
    if (currentIndex > 0) {
        sentenceMode = true;
        jumpToSentence(currentIndex - 1);
        video.play();
    }
}

function nextSentence() {
    if (currentIndex < segments.length - 1) {
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
        subtitleOriginal.style.display = "";
        subtitleTranslation.style.display = "none";
    } else {
        subtitleOriginal.style.display = "";
        subtitleTranslation.style.display = "";
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
    btnTranslate.textContent = "翻译中...";

    const langMap = { th: "泰语", Thai: "泰语", en: "英语", English: "英语", ja: "日语", ko: "韩语" };
    const sourceLang = langMap[language] || "泰语";

    try {
        const res = await fetch("/api/translate", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                segments: segments.map((s) => ({ index: s.index, text: s.text })),
                source_lang: sourceLang,
            }),
        });
        const data = await res.json();
        if (data.error) {
            alert("翻译失败: " + data.error);
        } else {
            (data.translations || []).forEach((t) => {
                if (segments[t.index]) segments[t.index].translation = t.translation;
            });
            renderSentenceList();
            highlightSentence(currentIndex);
            if (currentIndex >= 0) updateSubtitle(segments[currentIndex]);
            await saveSubtitle();
        }
    } catch (e) {
        alert("翻译失败: " + e.message);
    }
    btnTranslate.textContent = "重新翻译";
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
            dirList.innerHTML = '<div class="dir-item" style="color:#666;">（无子目录）</div>';
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
    const prefix = exportPrefixInput.value.trim() || "视频名";
    const type = exportTypeSelect.value;
    if (type === "srt") {
        exportHint.textContent = `将导出：${prefix}_泰语.srt、${prefix}_中文.srt`;
    } else {
        exportHint.textContent = `将导出：${prefix}.mp4、${prefix}_泰语.srt、${prefix}_中文.srt`;
    }
}

// ========== 执行导出 ==========
async function doExport() {
    const exportDir = exportDirInput.value.trim();
    const filePrefix = exportPrefixInput.value.trim();
    const exportType = exportTypeSelect.value;

    if (!exportDir) {
        alert("请输入导出目录");
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
                alert("导出失败: " + data.error);
            } else {
                alert(`字幕导出完成！\n保存到：${data.dir}\n文件：${data.files.join("、")}`);
            }
        } catch (e) {
            alert("导出失败: " + e.message);
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
            exportPct.textContent = `导出完成！已保存到 ${result.dir}`;
        } else {
            exportPct.textContent = "100%";
        }
        await delay(1500);
    } catch (e) {
        alert("导出失败: " + e.message);
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
    const modeLabels = { none: "盲听", original: "原文", both: "双语" };
    const mode = getSubtitleMode();
    const label = modeLabels[mode];
    repeatInfo.textContent = `${currentIndex + 1}/${segments.length} | ${repeatCount + 1}/${maxRepeat} ${label}`;
}

function delay(ms) {
    return new Promise((r) => setTimeout(r, ms));
}

// ========== 跟读功能 ==========
let frMediaRecorder = null;
let frRecordedChunks = [];
let frRecordedBlob = null;
let frRecordingTimer = null;
let frRecordingStart = 0;
let frIsRecording = false;
let frAudioPlayer = null;

function openFollowRead() {
    if (currentIndex < 0 || segments.length === 0) return;

    const seg = segments[currentIndex];
    video.pause();
    sentenceMode = false;

    // 显示面板，填入当前句子
    frReference.textContent = seg.text || "";
    frTranslation.textContent = seg.translation || "";
    frResult.style.display = "none";
    frTimer.textContent = "";
    btnFrPlayback.disabled = true;
    btnFrScore.disabled = true;
    btnFrRecord.textContent = "开始录音";
    btnFrRecord.classList.remove("recording");
    frRecordedBlob = null;

    followReadPanel.style.display = "block";
}

function closeFollowRead() {
    // 停止录音（如果正在录）
    if (frIsRecording) stopRecording();
    // 停止回放
    if (frAudioPlayer) {
        frAudioPlayer.pause();
        frAudioPlayer = null;
    }
    followReadPanel.style.display = "none";

    // 恢复句子模式
    sentenceMode = true;
    if (currentIndex >= 0) {
        jumpToSentence(currentIndex);
    }
}

function playOriginalSentence() {
    if (currentIndex < 0) return;
    const seg = segments[currentIndex];
    video.currentTime = seg.start;
    video.play();
    // 播放到句尾自动停
    const onTime = () => {
        if (video.currentTime >= seg.end - 0.05) {
            video.pause();
            video.removeEventListener("timeupdate", onTime);
        }
    };
    video.addEventListener("timeupdate", onTime);
}

async function toggleRecording() {
    if (frIsRecording) {
        stopRecording();
    } else {
        await startRecording();
    }
}

async function startRecording() {
    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        frRecordedChunks = [];
        frMediaRecorder = new MediaRecorder(stream);

        frMediaRecorder.ondataavailable = (e) => {
            if (e.data.size > 0) frRecordedChunks.push(e.data);
        };

        frMediaRecorder.onstop = () => {
            // 释放麦克风
            stream.getTracks().forEach((t) => t.stop());
            frRecordedBlob = new Blob(frRecordedChunks, { type: "audio/webm" });
            btnFrPlayback.disabled = false;
            btnFrScore.disabled = false;
            frIsRecording = false;
            clearInterval(frRecordingTimer);
            btnFrRecord.textContent = "重新录音";
            btnFrRecord.classList.remove("recording");
        };

        frMediaRecorder.start();
        frIsRecording = true;
        frRecordingStart = Date.now();
        btnFrRecord.textContent = "停止录音";
        btnFrRecord.classList.add("recording");
        frResult.style.display = "none";

        // 计时显示
        frRecordingTimer = setInterval(() => {
            const elapsed = ((Date.now() - frRecordingStart) / 1000).toFixed(1);
            frTimer.textContent = `录音中... ${elapsed}s`;
        }, 100);

    } catch (e) {
        alert("无法访问麦克风: " + e.message);
    }
}

function stopRecording() {
    if (frMediaRecorder && frMediaRecorder.state !== "inactive") {
        frMediaRecorder.stop();
    }
    frTimer.textContent = "录音完成";
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
    btnFrScore.textContent = "评分中...";
    frTimer.textContent = "正在分析发音...";

    const formData = new FormData();
    formData.append("audio", frRecordedBlob, "recording.webm");
    formData.append("reference_text", seg.text);
    // 语言映射
    const langMap = { th: "th-TH", Thai: "th-TH", en: "en-US", English: "en-US" };
    formData.append("language", langMap[language] || "th-TH");

    try {
        const res = await fetch("/api/pronounce", {
            method: "POST",
            body: formData,
        });
        const data = await res.json();

        if (data.error) {
            frTimer.textContent = "评分失败: " + data.error;
            btnFrScore.disabled = false;
            btnFrScore.textContent = "评分";
            return;
        }

        displayScoreResult(data);
        frTimer.textContent = "";
    } catch (e) {
        frTimer.textContent = "评分失败: " + e.message;
    }

    btnFrScore.disabled = false;
    btnFrScore.textContent = "评分";
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
        span.title = `${w.accuracy_score !== undefined ? Math.round(w.accuracy_score) + "分" : ""} ${w.error_type || ""}`;
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
