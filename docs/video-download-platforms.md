# 视频平台下载支持追踪

> 最后更新：2026-07-13

## 下载架构

```
用户输入（链接 / 分享文本）
    ↓
extractUrlFromText()         # 前端：从分享文本提取 URL
    ↓
_extract_url_from_text()     # 后端二次提取（防御）
    ↓
_is_douyin_url() ?
    ├─ YES → _download_douyin()   # 自定义：解析分享页 → CDN 下载
    └─ NO  → yt-dlp              # 通用下载器
                ↓
           ffprobe 音频轨道验证
                ↓
           normalize_audio()
```

---

## 平台支持状态

### ✅ 已测试可用

| 平台 | 链接格式 | 下载方法 | 测试时间 | 备注 |
|------|---------|---------|---------|------|
| 抖音 | `v.douyin.com/xxx` | 自定义（解析分享页 → CDN） | 2026-07-13 | 3/3 成功，约 2s；微信分享文本自动提取 URL |
| TikTok | `vm.tiktok.com/xxx`、`www.tiktok.com/...` | yt-dlp | 2026-07 | 曾遇无音频问题，已加 ffprobe 验证 |
| YouTube | `youtu.be/xxx`、`youtube.com/watch` | yt-dlp + YouTube cookie 兜底 | 2026-07 | 机器人检测时自动切 TV 客户端 |
| Facebook | `facebook.com/share/v/xxx`、`facebook.com/watch/` | yt-dlp | 2026-07-13 | 3/3 成功，约 9s，无需登录；公开视频直接可下 |

### ⚠️ 已知问题 / 未完整测试

| 平台 | 状态 | 问题描述 | 待办 |
|------|------|---------|------|
| 微博视频 | 未测试 | — | 测试 yt-dlp 支持情况 |
| 小红书 | 未测试 | — | 测试 yt-dlp 支持情况 |
| 微信视频号 | 未测试 | 需登录，可能无法服务器端下载 | 调研 |
| B站 | 未测试 | — | 测试 yt-dlp；注意大会员视频 |
| Facebook | 未测试 | — | 测试 yt-dlp |
| Instagram | 未测试 | 登录墙问题 | 调研 |
| Twitter/X | 未测试 | — | 测试 yt-dlp |
| LINE VOOM | 未测试 | — | 调研 |

### ❌ 已确认无法下载

| 平台 | 原因 | 错误类型 |
|------|------|---------|
| 抖音（yt-dlp） | 需要带签名 cookies，服务器无法生成 | `Fresh cookies needed` |
| 受 DRM 保护的视频 | 内容加密 | `DRM` |
| 私密 / 已删除视频 | 内容不可访问 | `404 / unavailable` |
| 会员专属视频 | 需登录验证 | `403 / Premium` |

---

## 抖音下载方案详情

**方法**：绕开 yt-dlp，自定义解析流程  
**文件**：`backend/app.py` → `_download_douyin()`

```
1. 短链跟随重定向 → iesdouyin.com 分享页 HTML
2. 正则提取 play_addr uri（形如 v0d00fg10000xxx）
3. 构造 CDN URL：https://aweme.snssdk.com/aweme/v1/play/?video_id={uri}&ratio=720p&line=0
4. 流式下载 → 写入临时文件 → 移动到 videos/
```

**风险点**：
- 抖音若修改分享页 HTML 结构，正则 `play_addr[^}]{0,300}?uri` 需更新
- CDN 域名 `aweme.snssdk.com` 可能变化，需关注
- 高清版本（1080p）暂未探索，当前固定 `ratio=720p`

**分享文本格式**（自动处理）：
```
7.46 复制打开抖音，看看【xxx的作品】标题... https://v.douyin.com/xxx/ 02/16 随机字符
```
前端 `extractUrlFromText()` 和后端 `_extract_url_from_text()` 均会从中提取 URL。

---

## 错误分类（当前 `_classify_error()`）

| 错误码 | 提示 | 触发关键词 |
|-------|------|-----------|
| 🔒 DRM | 版权保护 | `DRM`, `drm` |
| 🗑️ 不存在 | 已删除/私密 | `404`, `not found`, `unavailable`, `private`, `removed` |
| 🚫 需登录 | 会员/防盗链 | `Sign in`, `403`, `Forbidden`, `cookies`, `Premium` |
| ⏱️ 反爬 | 平台限速 | `429`, `rate limit`, `bot`, `challenge`, `JavaScript` |
| 🔇 无音频 | 无音频轨道 | `matches no streams`, `no audio` |
| ❓ 未知 | 兜底 | 截取 stderr 最后 120 字符 |

---

## 待测试清单

- [ ] 微博：`weibo.com/tv/show/xxx`
- [ ] 小红书：`xhslink.com/xxx` 或 `xiaohongshu.com/explore/xxx`
- [ ] B站：`bilibili.com/video/BVxxx` 或 `b23.tv/xxx`
- [x] Facebook：`facebook.com/watch/` 或 `fb.watch/xxx` ✅ 2026-07-13
- [ ] Instagram：`instagram.com/reel/xxx`
- [ ] Twitter/X：`x.com/xxx/status/xxx`
- [ ] 微信视频号：分享链接格式待确认
- [ ] LINE VOOM：格式待确认
- [ ] 抖音 1080p：探索 `ratio=1080p` 参数是否有效

---

## 更新记录

| 日期 | 改动 |
|------|------|
| 2026-07-13 | 新增抖音自定义下载；前后端均加分享文本 URL 提取 |
| 2026-07-13 | 测试 Facebook：yt-dlp 直接可用，3/3 成功，约 9s |
| 2026-07 | TikTok 无音频修复（ffprobe 验证 + 格式链扩展） |
| 2026-07 | 下载错误分类（5 类友好提示）+ 阶段进度条 |
| 2026-07 | YouTube 机器人检测自动切 TV 客户端 |
