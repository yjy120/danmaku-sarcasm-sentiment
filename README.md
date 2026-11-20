# 短视频弹幕反讽情感实时分析系统

> 输入 B 站视频链接，自动解析视频与采集评论，用大模型识别「明褒暗贬」的反讽表达，并通过 WebSocket 实时推送分析结果

| Flask | Vue 3 | SocketIO | Selenium | yt-dlp | 大模型 |
|---|---|---|---|---|---|

## 一、项目概述

短视频评论中大量存在「正话反说」「明褒暗贬」的反讽表达（如"可真行""不愧是大厂"），传统情感分析模型容易将其误判为正面情绪。本系统面向 Bilibili 视频评论场景，构建一条从「**视频解析 → 弹幕/评论采集 → 反讽语义分析 → 实时可视化**」的完整链路，用大模型识别反讽倾向并给出解释，配合本地关键词库做降级兜底。

**项目规模**：820+ 行 Flask 后端、2 个 WebSocket 事件、8 线程池并发分析、287 条反讽关键词库。

## 二、核心功能

- **视频直链解析**：粘贴 B 站视频链接，通过 yt-dlp 提取 MP4 直链，自动优先选择音视频合一的格式；前端内嵌播放器预览。
- **视频流代理**：后端带 `Referer` 转发视频流，并透传 `Range` 请求头，解决 B 站 403 防盗链与播放器进度条拖动问题。
- **评论采集**：Selenium 驱动 Chrome 打开视频页，注入倒计时浮层提示用户登录，轮询检测评论组件加载完成后抓取评论；浏览器未就绪时也能继续处理已加载内容。
- **反讽语义分析**：调用 SiliconFlow 大模型，让其对每条评论输出 `probability`（反讽概率）与 `explanation`（中文理由）；API 不可用时自动切换本地关键词库兜底。
- **实时进度推送**：基于 Flask-SocketIO，将「提取视频 → 启动浏览器 → 抓取评论 → 逐条分析结果 → 全部完成」各阶段通过 WebSocket 实时推送到前端。
- **结果可视化**：前端按评论卡片展示反讽概率与判定理由，支持重新提取。

## 三、技术架构

```
用户粘贴 B站链接
      │
      ▼
Flask 后端（bilibili_api.py）
  ├─ /api/bilibili/extract     # 解析入口
  ├─ /api/video/proxy          # 带 Referer + Range 的视频流代理
  ├─ WebSocket: start_extract  # 视频直链 → 浏览器抓评论 → 分阶段推送
  │     ├─ yt-dlp              # 视频直链提取
  │     └─ Selenium + Chrome   # 评论采集
  └─ WebSocket: analyze_irony  # 8 线程池并发调用大模型
        ├─ SiliconFlow LLM     # 主分析通道（3 次重试）
        └─ 287 条关键词库       # 降级兜底
      │  socket.io emit
      ▼
Vue 3 前端（Element Plus + socket.io-client）
```

**技术选型**

- **后端**：Python、Flask、Flask-CORS、Flask-SocketIO、Selenium + webdriver-manager、yt-dlp、requests
- **前端**：Vue 3、Vite、Element Plus、Axios、socket.io-client
- **AI**：SiliconFlow 大模型 API + 本地反讽关键词库（287 条，从字节码恢复）

## 四、技术亮点

**1. 大模型分析的三级容错**
`analyze_sarcasm_with_llm()` 设计完整容错链：3 次重试（每次间隔 2 秒）→ 解析失败自动去除 Markdown 代码块 → 彻底超时/异常时调用 `get_local_fallback_analysis()`，按关键词命中数估算概率（`0.3 + 命中数 × 0.15`，上限 0.85）。保证服务在弱网或 API 故障下仍可用。

**2. 线程池并发分析 + 逐条实时回传**
`handle_analyze_irony()` 使用 `ThreadPoolExecutor(max_workers=8)` 并发分析多条评论，每分析完一条立即通过 `socketio.emit('irony_result', to=sid)` 推送给对应客户端，最后发送 `irony_complete`。用户无需等待全部完成即可看到结果陆续出现。

**3. 工程化的代理环境适配**
针对国内网络与沙箱代理做了专门处理：设置 `no_proxy` 让 Selenium 与 ChromeDriver 的 localhost 通信直连（避免被系统代理拦截导致 `driver.get()` 失败）；配置 `WDM_MIRROR` 用国内镜像加速 chromedriver 下载；对视频请求禁用 SSL 校验警告。

**4. 视频流 Range 请求透传**
`/api/video/proxy` 转发请求时携带浏览器 `Range` 头与 B 站 `Referer`，并过滤不适合的响应头、保留 `Content-Length`，使前端 `<video>` 播放器可以正常拖动进度条。

**5. 关键词库从字节码恢复**
`sarcastic_keywords.py` 的 287 条关键词曾因文件丢失，从 `__pycache__/*.pyc` 字节码中完整还原并保持原顺序，体现了对 Python 字节码结构的理解。

## 五、目录结构

```
danmaku-sarcasm-sentiment/
├── bilibili_api.py          # 820+ 行 Flask 后端：视频代理、评论采集、AI 分析、SocketIO 推送
├── sarcastic_keywords.py    # 287 条反讽关键词库（降级兜底）
├── get_mp4_urls.py          # 批量提取视频 MP4 直链的工具脚本
├── requirements.txt
└── frontend/
    └── src/
        ├── App.vue          # 主页面：输入链接、视频预览、结果展示
        └── components/
```

## 六、快速开始

**环境要求**：Python 3.9+、Node.js 16+、本地 Chrome 浏览器

**1. 安装依赖**

```bash
pip install -r requirements.txt
```

> 评论采集依赖本地 Chrome，webdriver-manager 会自动匹配驱动。

**2. 配置大模型密钥**

源码中的 API Key 已替换为占位符 `YOUR_API_KEY`，请填入你的 SiliconFlow 密钥（或改为环境变量读取）。未配置时分析会自动走本地关键词库兜底。

**3. 启动后端与前端**

```bash
# 后端
python bilibili_api.py

# 前端（另开终端）
cd frontend && npm install && npm run dev
```

浏览器打开前端地址，粘贴 B 站视频链接即可开始分析。

## 七、说明

本项目为课程实践作品，大模型密钥等敏感配置已从代码中移除，请以占位符或环境变量方式注入后再运行。
