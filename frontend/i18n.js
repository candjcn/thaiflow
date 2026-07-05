// ========== i18n 国际化 ==========
const I18N = {
    // 当前语言
    currentLang: "zh-CN",

    // 翻译字典
    translations: {
        "zh-CN": {
            // ---- Landing 页 ----
            "nav.cta": "开始学习",
            "hero.line1": "刷着短视频",
            "hero.line2": "学会任何外语",
            "hero.subtitle": "粘贴一条 TikTok 链接，AI 自动识别每一句台词。<br>逐句重复、跟读打分，英语、日语、泰语、法语……统统搞定。",
            "hero.btn.try": "免费体验",
            "hero.btn.more": "了解更多",
            "hero.mock.subtitle": "Nice to meet you!",
            "hero.mock.cn": "很高兴认识你",
            "hero.mock.score.num": "92",
            "hero.mock.score.label": "发音评分",
            "features.title": "为什么选择 ThaiFlow",
            "features.desc": "三个简单步骤，将任何短视频变成你的外语课堂",
            "feature.1.title": "粘贴即学",
            "feature.1.desc": "粘贴 TikTok、YouTube 链接，AI 自动识别语音并翻译成中文，支持英语、日语、泰语、法语等 50+ 种语言。",
            "feature.2.title": "逐句精听",
            "feature.2.desc": "每句自动重复三遍：第一遍盲听、第二遍看原文、第三遍看翻译。渐进式理解，印象更深。",
            "feature.3.title": "AI 评分",
            "feature.3.desc": "跟读后 AI 实时评估你的发音，精确到每个音节。准确度、流利度、完整度一目了然。",
            "steps.title": "三步开始学习",
            "step.1.title": "粘贴链接",
            "step.1.desc": "将 TikTok 或 YouTube 短视频链接粘贴到输入框，点击下载。",
            "step.2.title": "自动识别",
            "step.2.desc": "AI 自动识别语音、断句、翻译，生成精准的双语字幕。全程无需手动操作。",
            "step.3.title": "跟读练习",
            "step.3.desc": "逐句播放、重复跟读、AI 打分。每天 15 分钟，外语脱口而出。",
            "highlight.1.title": "智能校准<br><span class=\"gradient-text\">双引擎识别</span>",
            "highlight.1.desc": "同时调用 Groq Whisper 和 Azure Speech 两个引擎。Whisper 负责精准断句，Azure 负责准确识别。两者结合，字幕准确率远超单一引擎。",
            "highlight.1.engine1.desc": "断句 + 时间戳",
            "highlight.1.engine2.desc": "精准识别文本",
            "highlight.2.title": "三遍学习法<br><span class=\"gradient-text\">科学记忆</span>",
            "highlight.2.desc": "每句自动播放三遍，字幕渐进显示。第一遍锻炼听力，第二遍对照原文，第三遍理解含义。符合语言学习的\u201c可理解性输入\u201d原则。",
            "highlight.2.pass1.label": "盲听",
            "highlight.2.pass1.desc": "纯听力训练",
            "highlight.2.pass2.label": "原文",
            "highlight.2.pass3.label": "双语",
            "cta.title": "开始你的外语学习之旅",
            "cta.desc": "完全免费，无需注册，打开即用。",
            "cta.btn": "立即体验",
            "footer.copy": "用短视频学外语",

            // ---- App 页 ----
            "app.title": "短视频外语学习播放器",
            "app.local.btn": "打开本地视频（已有字幕）",
            "app.local.hint": "选择同名的视频文件和字幕文件，直接播放，无需上传",
            "app.server.title": "服务器视频",
            "app.add.toggle": "+ 添加新视频",
            "app.add.collapse": "− 收起",
            "app.add.url.label": "从链接下载",
            "app.add.url.placeholder": "粘贴 TikTok / YouTube 链接...",
            "app.add.url.btn": "下载",
            "app.add.upload.label": "上传到服务器识别翻译",
            "app.add.upload.btn": "选择视频文件",
            "app.add.engine.label": "识别引擎：",
            "app.add.engine.combined": "智能校准 (Groq+Azure)",
            "app.add.segment.label": "断句：",
            "app.add.segment.auto": "自动",
            "app.add.segment.short": "短句",
            "app.add.segment.medium": "中等",
            "app.add.segment.long": "长句",

            // 加载步骤
            "loading.step1": "加载视频文件...",
            "loading.step2": "语音识别与断句...",
            "loading.step3": "翻译字幕...",
            "export.overlay.title": "正在导出带字幕的视频...",

            // 控制栏
            "ctrl.back": "返回选择",
            "ctrl.prev": "上一句",
            "ctrl.pause": "暂停/播放",
            "ctrl.repeat": "重复当前句",
            "ctrl.next": "下一句",
            "ctrl.repeat.label": "重复",
            "ctrl.repeat.unit": "遍",
            "ctrl.speed.label": "速度",
            "ctrl.original": "原文",
            "ctrl.translation": "译文",
            "ctrl.list": "句子列表",
            "ctrl.follow": "跟读",
            "ctrl.save": "保存",
            "ctrl.export": "导出",
            "ctrl.fullscreen": "全屏",

            // 移动端
            "mobile.mode.play": "播放",
            "mobile.mode.study": "复读",
            "mobile.mode.follow": "跟读",

            // 句子列表
            "drawer.title": "句子列表",
            "drawer.retranslate": "重新翻译",

            // 导出弹窗
            "export.title": "导出设置",
            "export.type.label": "导出内容：",
            "export.type.all": "带字幕视频 + SRT 字幕文件",
            "export.type.srt": "仅 SRT 字幕文件",
            "export.dir.label": "导出目录：",
            "export.dir.placeholder": "/Users/apple/Desktop",
            "export.dir.browse": "浏览",
            "export.prefix.label": "文件名前缀：",
            "export.prefix.placeholder": "留空则使用视频原名",
            "export.hint.default": "将导出 3 个文件：带字幕视频(.mp4)、泰语字幕(.srt)、中文字幕(.srt)",
            "export.cancel": "取消",
            "export.confirm": "开始导出",
            "export.dir.up": "上级目录",
            "export.dir.select": "选择此目录",
            "export.dir.noSub": "（无子目录）",

            // 跟读
            "follow.title": "跟读练习",
            "follow.playOriginal": "影子跟读",
            "follow.stopShadow": "停止跟读",
            "follow.record": "开始录音",
            "follow.playback": "回放",
            "follow.score": "评分",
            "follow.total": "总分",
            "follow.accuracy": "准确度",
            "follow.fluency": "流利度",
            "follow.completeness": "完整度",

            // 动态文本（player.js 使用）
            "status.ready": "已识别 · 点击播放",
            "status.notReady": "未识别",
            "status.redo": "重新识别",
            "status.recognize": "识别翻译",
            "status.downloading": "下载中...",
            "status.fetchingInfo": "正在获取视频信息...",
            "status.enterUrl": "请输入视频链接",
            "status.downloadFail": "下载失败: ",
            "status.uploading": "正在上传...",
            "status.uploadSuccess": "上传成功：",
            "status.uploadFail": "上传失败: ",
            "status.loadingVideo": "正在加载视频文件...",
            "status.loadingSubtitle": "正在读取已保存的字幕...",
            "status.subtitleReady": "就绪！",
            "status.subtitleFail": "字幕读取失败: ",
            "status.recognizing": "正在语音识别...",
            "status.recognizeFail": "识别失败: ",
            "status.recognizeDone": "识别完成，共 {n} 句",
            "status.translating": "正在翻译字幕...",
            "status.translateFail": "翻译失败: ",
            "status.translateRetry": "（可稍后手动重试）",
            "status.allReady": "全部就绪！",
            "status.uploadingServer": "正在上传视频到服务器...",
            "status.videoLoadFail": "视频加载失败",
            "status.translatingBtn": "翻译中...",
            "status.retranslate": "重新翻译",
            "status.selectVideo": "请选择一个视频文件",
            "status.subtitleParseFail": "字幕文件解析失败: ",
            "status.providerGroq": "Groq Whisper",
            "status.providerAzure": "Azure Speech",
            "status.providerCombined": "Groq + Azure 智能校准",
            "status.callingProvider": "正在调用 {provider} 语音识别，将音频自动断句...",
            "status.exportFail": "导出失败: ",
            "status.exportDone": "导出完成！已保存到 ",
            "status.srtExportDone": "字幕导出完成！\n保存到：{dir}\n文件：{files}",
            "status.enterExportDir": "请输入导出目录",
            "status.micFail": "无法访问麦克风: ",
            "status.recording": "录音中... {t}s",
            "status.recordDone": "录音完成",
            "status.scoreFail": "评分失败: ",
            "status.scoring": "正在分析发音...",
            "status.scoringBtn": "评分中...",
            "status.reRecord": "重新录音",
            "status.stopRecord": "停止录音",
            "mode.none": "盲听",
            "mode.original": "原文",
            "mode.both": "双语",
            "hint.videoName": "视频名",
            "hint.srtFiles": "将导出：{prefix}_泰语.srt、{prefix}_中文.srt",
            "hint.allFiles": "将导出：{prefix}.mp4、{prefix}_泰语.srt、{prefix}_中文.srt",
            "lang.switcher": "语言",
        },

        "zh-TW": {
            // ---- Landing 頁 ----
            "nav.cta": "開始學習",
            "hero.line1": "刷著短視頻",
            "hero.line2": "學會任何外語",
            "hero.subtitle": "貼上一條 TikTok 連結，AI 自動識別每一句台詞。<br>逐句重複、跟讀打分，英語、日語、泰語、法語……通通搞定。",
            "hero.btn.try": "免費體驗",
            "hero.btn.more": "了解更多",
            "hero.mock.subtitle": "Nice to meet you!",
            "hero.mock.cn": "很高興認識你",
            "hero.mock.score.num": "92",
            "hero.mock.score.label": "發音評分",
            "features.title": "為什麼選擇 ThaiFlow",
            "features.desc": "三個簡單步驟，將任何短視頻變成你的外語課堂",
            "feature.1.title": "貼上即學",
            "feature.1.desc": "貼上 TikTok、YouTube 連結，AI 自動識別語音並翻譯成中文，支持英語、日語、泰語、法語等 50+ 種語言。",
            "feature.2.title": "逐句精聽",
            "feature.2.desc": "每句自動重複三遍：第一遍盲聽、第二遍看原文、第三遍看翻譯。漸進式理解，印象更深。",
            "feature.3.title": "AI 評分",
            "feature.3.desc": "跟讀後 AI 即時評估你的發音，精確到每個音節。準確度、流利度、完整度一目了然。",
            "steps.title": "三步開始學習",
            "step.1.title": "貼上連結",
            "step.1.desc": "將 TikTok 或 YouTube 短視頻連結貼到輸入框，點擊下載。",
            "step.2.title": "自動識別",
            "step.2.desc": "AI 自動識別語音、斷句、翻譯，生成精準的雙語字幕。全程無需手動操作。",
            "step.3.title": "跟讀練習",
            "step.3.desc": "逐句播放、重複跟讀、AI 打分。每天 15 分鐘，外語脫口而出。",
            "highlight.1.title": "智能校準<br><span class=\"gradient-text\">雙引擎識別</span>",
            "highlight.1.desc": "同時調用 Groq Whisper 和 Azure Speech 兩個引擎。Whisper 負責精準斷句，Azure 負責準確識別。兩者結合，字幕準確率遠超單一引擎。",
            "highlight.1.engine1.desc": "斷句 + 時間戳",
            "highlight.1.engine2.desc": "精準識別文本",
            "highlight.2.title": "三遍學習法<br><span class=\"gradient-text\">科學記憶</span>",
            "highlight.2.desc": "每句自動播放三遍，字幕漸進顯示。第一遍鍛鍊聽力，第二遍對照原文，第三遍理解含義。符合語言學習的「可理解性輸入」原則。",
            "highlight.2.pass1.label": "盲聽",
            "highlight.2.pass1.desc": "純聽力訓練",
            "highlight.2.pass2.label": "原文",
            "highlight.2.pass3.label": "雙語",
            "cta.title": "開始你的外語學習之旅",
            "cta.desc": "完全免費，無需註冊，打開即用。",
            "cta.btn": "立即體驗",
            "footer.copy": "用短視頻學外語",

            // ---- App 頁 ----
            "app.title": "短視頻外語學習播放器",
            "app.local.btn": "打開本地視頻（已有字幕）",
            "app.local.hint": "選擇同名的視頻檔案和字幕檔案，直接播放，無需上傳",
            "app.server.title": "伺服器視頻",
            "app.add.toggle": "+ 添加新視頻",
            "app.add.collapse": "− 收起",
            "app.add.url.label": "從連結下載",
            "app.add.url.placeholder": "貼上 TikTok / YouTube 連結...",
            "app.add.url.btn": "下載",
            "app.add.upload.label": "上傳到伺服器識別翻譯",
            "app.add.upload.btn": "選擇視頻檔案",
            "app.add.engine.label": "識別引擎：",
            "app.add.engine.combined": "智能校準 (Groq+Azure)",
            "app.add.segment.label": "斷句：",
            "app.add.segment.auto": "自動",
            "app.add.segment.short": "短句",
            "app.add.segment.medium": "中等",
            "app.add.segment.long": "長句",

            "loading.step1": "載入視頻檔案...",
            "loading.step2": "語音識別與斷句...",
            "loading.step3": "翻譯字幕...",
            "export.overlay.title": "正在導出帶字幕的視頻...",

            "ctrl.back": "返回選擇",
            "ctrl.prev": "上一句",
            "ctrl.pause": "暫停/播放",
            "ctrl.repeat": "重複當前句",
            "ctrl.next": "下一句",
            "ctrl.repeat.label": "重複",
            "ctrl.repeat.unit": "遍",
            "ctrl.speed.label": "速度",
            "ctrl.original": "原文",
            "ctrl.translation": "譯文",
            "ctrl.list": "句子列表",
            "ctrl.follow": "跟讀",
            "ctrl.save": "保存",
            "ctrl.export": "導出",
            "ctrl.fullscreen": "全螢幕",

            "mobile.mode.play": "播放",
            "mobile.mode.study": "複讀",
            "mobile.mode.follow": "跟讀",

            "drawer.title": "句子列表",
            "drawer.retranslate": "重新翻譯",

            "export.title": "導出設置",
            "export.type.label": "導出內容：",
            "export.type.all": "帶字幕視頻 + SRT 字幕檔案",
            "export.type.srt": "僅 SRT 字幕檔案",
            "export.dir.label": "導出目錄：",
            "export.dir.placeholder": "/Users/apple/Desktop",
            "export.dir.browse": "瀏覽",
            "export.prefix.label": "檔名前綴：",
            "export.prefix.placeholder": "留空則使用視頻原名",
            "export.hint.default": "將導出 3 個檔案：帶字幕視頻(.mp4)、泰語字幕(.srt)、中文字幕(.srt)",
            "export.cancel": "取消",
            "export.confirm": "開始導出",
            "export.dir.up": "上級目錄",
            "export.dir.select": "選擇此目錄",
            "export.dir.noSub": "（無子目錄）",

            "follow.title": "跟讀練習",
            "follow.playOriginal": "影子跟讀",
            "follow.stopShadow": "停止跟讀",
            "follow.record": "開始錄音",
            "follow.playback": "回放",
            "follow.score": "評分",
            "follow.total": "總分",
            "follow.accuracy": "準確度",
            "follow.fluency": "流利度",
            "follow.completeness": "完整度",

            "status.ready": "已識別 · 點擊播放",
            "status.notReady": "未識別",
            "status.redo": "重新識別",
            "status.recognize": "識別翻譯",
            "status.downloading": "下載中...",
            "status.fetchingInfo": "正在獲取視頻資訊...",
            "status.enterUrl": "請輸入視頻連結",
            "status.downloadFail": "下載失敗: ",
            "status.uploading": "正在上傳...",
            "status.uploadSuccess": "上傳成功：",
            "status.uploadFail": "上傳失敗: ",
            "status.loadingVideo": "正在載入視頻檔案...",
            "status.loadingSubtitle": "正在讀取已保存的字幕...",
            "status.subtitleReady": "就緒！",
            "status.subtitleFail": "字幕讀取失敗: ",
            "status.recognizing": "正在語音識別...",
            "status.recognizeFail": "識別失敗: ",
            "status.recognizeDone": "識別完成，共 {n} 句",
            "status.translating": "正在翻譯字幕為中文...",
            "status.translateFail": "翻譯失敗: ",
            "status.translateRetry": "（可稍後手動重試）",
            "status.allReady": "全部就緒！",
            "status.uploadingServer": "正在上傳視頻到伺服器...",
            "status.videoLoadFail": "視頻載入失敗",
            "status.translatingBtn": "翻譯中...",
            "status.retranslate": "重新翻譯",
            "status.selectVideo": "請選擇一個視頻檔案",
            "status.subtitleParseFail": "字幕檔案解析失敗: ",
            "status.providerGroq": "Groq Whisper",
            "status.providerAzure": "Azure Speech",
            "status.providerCombined": "Groq + Azure 智能校準",
            "status.callingProvider": "正在調用 {provider} 語音識別，將音頻自動斷句...",
            "status.exportFail": "導出失敗: ",
            "status.exportDone": "導出完成！已保存到 ",
            "status.srtExportDone": "字幕導出完成！\n保存到：{dir}\n檔案：{files}",
            "status.enterExportDir": "請輸入導出目錄",
            "status.micFail": "無法存取麥克風: ",
            "status.recording": "錄音中... {t}s",
            "status.recordDone": "錄音完成",
            "status.scoreFail": "評分失敗: ",
            "status.scoring": "正在分析發音...",
            "status.scoringBtn": "評分中...",
            "status.reRecord": "重新錄音",
            "status.stopRecord": "停止錄音",
            "mode.none": "盲聽",
            "mode.original": "原文",
            "mode.both": "雙語",
            "hint.videoName": "視頻名",
            "hint.srtFiles": "將導出：{prefix}_泰語.srt、{prefix}_中文.srt",
            "hint.allFiles": "將導出：{prefix}.mp4、{prefix}_泰語.srt、{prefix}_中文.srt",
            "lang.switcher": "語言",
        },

        "en": {
            // ---- Landing page ----
            "nav.cta": "Start Learning",
            "hero.line1": "Watch Short Videos",
            "hero.line2": "Master Any Language",
            "hero.subtitle": "Paste a TikTok link, AI auto-recognizes every sentence.<br>Repeat sentence by sentence, practice pronunciation, get AI scores — English, Japanese, Thai, French… all covered.",
            "hero.btn.try": "Try Free",
            "hero.btn.more": "Learn More",
            "hero.mock.subtitle": "Nice to meet you!",
            "hero.mock.cn": "很高兴认识你",
            "hero.mock.score.num": "92",
            "hero.mock.score.label": "Pronunciation",
            "features.title": "Why ThaiFlow",
            "features.desc": "Three simple steps to turn any short video into your language class",
            "feature.1.title": "Paste & Learn",
            "feature.1.desc": "Paste a TikTok or YouTube link, AI auto-recognizes speech and translates into Chinese. Supports English, Japanese, Thai, French, and 50+ more languages.",
            "feature.2.title": "Listen Closely",
            "feature.2.desc": "Each sentence repeats three times: first listen blind, second read the original, third read the translation. Progressive understanding for deeper retention.",
            "feature.3.title": "AI Scoring",
            "feature.3.desc": "AI evaluates your pronunciation in real time after you read along, down to every syllable. Accuracy, fluency, and completeness at a glance.",
            "steps.title": "Three Steps to Start",
            "step.1.title": "Paste Link",
            "step.1.desc": "Paste a TikTok or YouTube short video link into the input box, then click download.",
            "step.2.title": "Auto Recognition",
            "step.2.desc": "AI auto-recognizes speech, segments sentences, and translates — generating accurate bilingual subtitles. Fully automatic.",
            "step.3.title": "Read Along",
            "step.3.desc": "Play sentence by sentence, repeat & read along, get AI scores. 15 minutes a day, speak fluently.",
            "highlight.1.title": "Smart Calibration<br><span class=\"gradient-text\">Dual Engine</span>",
            "highlight.1.desc": "Uses both Groq Whisper and Azure Speech engines simultaneously. Whisper handles precise segmentation, Azure handles accurate recognition. Combined, subtitle accuracy far exceeds either engine alone.",
            "highlight.1.engine1.desc": "Segmentation + Timestamps",
            "highlight.1.engine2.desc": "Accurate Recognition",
            "highlight.2.title": "Three-Pass Method<br><span class=\"gradient-text\">Scientific Memory</span>",
            "highlight.2.desc": "Each sentence plays three times with progressive subtitles. First pass trains listening, second pass shows the original, third pass shows the meaning. Follows the \"comprehensible input\" principle of language learning.",
            "highlight.2.pass1.label": "Blind",
            "highlight.2.pass1.desc": "Pure listening",
            "highlight.2.pass2.label": "Original",
            "highlight.2.pass3.label": "Bilingual",
            "cta.title": "Start Your Language Journey",
            "cta.desc": "Completely free. No registration. Ready to use.",
            "cta.btn": "Try Now",
            "footer.copy": "Learn languages with short videos",

            // ---- App page ----
            "app.title": "Short Video Language Player",
            "app.local.btn": "Open Local Video (with subtitles)",
            "app.local.hint": "Select video and subtitle files with matching names for direct playback, no upload needed",
            "app.server.title": "Server Videos",
            "app.add.toggle": "+ Add New Video",
            "app.add.collapse": "− Collapse",
            "app.add.url.label": "Download from Link",
            "app.add.url.placeholder": "Paste TikTok / YouTube link...",
            "app.add.url.btn": "Download",
            "app.add.upload.label": "Upload to server for recognition",
            "app.add.upload.btn": "Choose Video File",
            "app.add.engine.label": "Engine: ",
            "app.add.engine.combined": "Smart Calibration (Groq+Azure)",
            "app.add.segment.label": "Segmentation: ",
            "app.add.segment.auto": "Auto",
            "app.add.segment.short": "Short",
            "app.add.segment.medium": "Medium",
            "app.add.segment.long": "Long",

            "loading.step1": "Loading video file...",
            "loading.step2": "Speech recognition & segmentation...",
            "loading.step3": "Translating subtitles...",
            "export.overlay.title": "Exporting video with subtitles...",

            "ctrl.back": "Back",
            "ctrl.prev": "Previous",
            "ctrl.pause": "Pause/Play",
            "ctrl.repeat": "Repeat",
            "ctrl.next": "Next",
            "ctrl.repeat.label": "Repeat",
            "ctrl.repeat.unit": "×",
            "ctrl.speed.label": "Speed",
            "ctrl.original": "Original",
            "ctrl.translation": "Translation",
            "ctrl.list": "Sentence List",
            "ctrl.follow": "Read",
            "ctrl.save": "Save",
            "ctrl.export": "Export",
            "ctrl.fullscreen": "Fullscreen",

            "mobile.mode.play": "Play",
            "mobile.mode.study": "Repeat",
            "mobile.mode.follow": "Follow",

            "drawer.title": "Sentence List",
            "drawer.retranslate": "Re-translate",

            "export.title": "Export Settings",
            "export.type.label": "Export type:",
            "export.type.all": "Video with subtitles + SRT files",
            "export.type.srt": "SRT subtitle files only",
            "export.dir.label": "Export directory:",
            "export.dir.placeholder": "/Users/apple/Desktop",
            "export.dir.browse": "Browse",
            "export.prefix.label": "File name prefix:",
            "export.prefix.placeholder": "Leave blank to use video name",
            "export.hint.default": "Will export 3 files: video with subtitles (.mp4), original subtitle (.srt), Chinese subtitle (.srt)",
            "export.cancel": "Cancel",
            "export.confirm": "Start Export",
            "export.dir.up": "Parent directory",
            "export.dir.select": "Select this directory",
            "export.dir.noSub": "(No subdirectories)",

            "follow.title": "Read-Along Practice",
            "follow.playOriginal": "Shadow",
            "follow.stopShadow": "Stop",
            "follow.record": "Record",
            "follow.playback": "Playback",
            "follow.score": "Score",
            "follow.total": "Total",
            "follow.accuracy": "Accuracy",
            "follow.fluency": "Fluency",
            "follow.completeness": "Completeness",

            "status.ready": "Ready · Click to play",
            "status.notReady": "Not processed",
            "status.redo": "Re-process",
            "status.recognize": "Recognize",
            "status.downloading": "Downloading...",
            "status.fetchingInfo": "Fetching video info...",
            "status.enterUrl": "Please enter a video URL",
            "status.downloadFail": "Download failed: ",
            "status.uploading": "Uploading...",
            "status.uploadSuccess": "Upload success: ",
            "status.uploadFail": "Upload failed: ",
            "status.loadingVideo": "Loading video file...",
            "status.loadingSubtitle": "Reading saved subtitles...",
            "status.subtitleReady": "Ready!",
            "status.subtitleFail": "Failed to read subtitles: ",
            "status.recognizing": "Speech recognition in progress...",
            "status.recognizeFail": "Recognition failed: ",
            "status.recognizeDone": "Recognition complete, {n} sentences",
            "status.translating": "Translating subtitles to Chinese...",
            "status.translateFail": "Translation failed: ",
            "status.translateRetry": " (retry manually later)",
            "status.allReady": "All ready!",
            "status.uploadingServer": "Uploading video to server...",
            "status.videoLoadFail": "Video loading failed",
            "status.translatingBtn": "Translating...",
            "status.retranslate": "Re-translate",
            "status.selectVideo": "Please select a video file",
            "status.subtitleParseFail": "Subtitle file parse error: ",
            "status.providerGroq": "Groq Whisper",
            "status.providerAzure": "Azure Speech",
            "status.providerCombined": "Groq + Azure Smart Calibration",
            "status.callingProvider": "Calling {provider} for speech recognition and segmentation...",
            "status.exportFail": "Export failed: ",
            "status.exportDone": "Export complete! Saved to ",
            "status.srtExportDone": "Subtitle export complete!\nSaved to: {dir}\nFiles: {files}",
            "status.enterExportDir": "Please enter export directory",
            "status.micFail": "Cannot access microphone: ",
            "status.recording": "Recording... {t}s",
            "status.recordDone": "Recording complete",
            "status.scoreFail": "Scoring failed: ",
            "status.scoring": "Analyzing pronunciation...",
            "status.scoringBtn": "Scoring...",
            "status.reRecord": "Re-record",
            "status.stopRecord": "Stop",
            "mode.none": "Blind",
            "mode.original": "Original",
            "mode.both": "Bilingual",
            "hint.videoName": "video name",
            "hint.srtFiles": "Will export: {prefix}_original.srt, {prefix}_chinese.srt",
            "hint.allFiles": "Will export: {prefix}.mp4, {prefix}_original.srt, {prefix}_chinese.srt",
            "lang.switcher": "Lang",
        },
    },

    // 初始化：检测浏览器语言
    init() {
        const saved = localStorage.getItem("ui-lang");
        if (saved && this.translations[saved]) {
            this.currentLang = saved;
        } else {
            const browserLang = navigator.language || navigator.userLanguage || "zh-CN";
            if (browserLang.startsWith("zh")) {
                // 繁体中文地区
                if (browserLang === "zh-TW" || browserLang === "zh-HK" || browserLang === "zh-Hant") {
                    this.currentLang = "zh-TW";
                } else {
                    this.currentLang = "zh-CN";
                }
            } else {
                this.currentLang = "en";
            }
        }
        this.applyToPage();
        this.updateSwitcher();
    },

    // 获取翻译
    t(key, params) {
        const dict = this.translations[this.currentLang] || this.translations["zh-CN"];
        let text = dict[key] || this.translations["zh-CN"][key] || key;
        if (params) {
            Object.keys(params).forEach(k => {
                text = text.replace(`{${k}}`, params[k]);
            });
        }
        return text;
    },

    // 切换语言
    setLang(lang) {
        if (!this.translations[lang]) return;
        this.currentLang = lang;
        localStorage.setItem("ui-lang", lang);
        this.applyToPage();
        this.updateSwitcher();
    },

    // 应用翻译到页面上所有 data-i18n 元素
    applyToPage() {
        document.querySelectorAll("[data-i18n]").forEach(el => {
            const key = el.getAttribute("data-i18n");
            const text = this.t(key);
            if (el.tagName === "INPUT" || el.tagName === "TEXTAREA") {
                // 不修改 input 的 textContent
            } else {
                el.innerHTML = text;
            }
        });
        document.querySelectorAll("[data-i18n-placeholder]").forEach(el => {
            el.placeholder = this.t(el.getAttribute("data-i18n-placeholder"));
        });
        document.querySelectorAll("[data-i18n-title]").forEach(el => {
            el.title = this.t(el.getAttribute("data-i18n-title"));
        });
        // 更新 <html lang>
        const langMap = { "zh-CN": "zh-CN", "zh-TW": "zh-TW", "en": "en" };
        document.documentElement.lang = langMap[this.currentLang] || "zh-CN";
    },

    // 更新语言切换按钮状态
    updateSwitcher() {
        document.querySelectorAll(".lang-switcher-btn").forEach(btn => {
            btn.classList.toggle("active", btn.dataset.lang === this.currentLang);
        });
    },
};

// 快捷函数
function t(key, params) {
    return I18N.t(key, params);
}
