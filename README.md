# 短视频弹幕反讽情感实时分析系统

> 输入 B 站视频链接，自动提取视频与弹幕，借助大模型对评论做反讽/讽刺倾向分析，并通过 WebSocket 实时推送结果 · Flask + Vue3

## 项目简介

短视频评论中大量存在「明褒暗贬」「正话反说」的反讽表达，传统情感分析容易将其误判为正面情绪。本系统面向 B 站视频评论场景，构建一条从「视频解析 → 弹幕采集 → 语义分析 → 实时可视化」的完整链路，用大模型识别反讽倾向，并配合本地关键词库做降级兜底。

## 核心功能

- **视频解析**：粘贴 Bilibili 视频链接，通过 yt-dlp 提取视频直链，前端内嵌播放器预览。
- **视频代理转发**：后端带 Referer 转发视频流，并透传 Range 请求头，解决 403 与进度条拖动问题。
- **弹幕/评论采集**：基于 Selenium 驱动浏览器采集评论数据。
- **反讽语义分析**：调用 SiliconFlow 大模型判断评论的反讽概率；接口不可用时自动切换到本地 287 条反讽关键词库兜底。
- **实时推送**：基于 Flask-SocketIO（WebSocket）将分析进度与结果实时推送到前端。
- **结果可视化**：前端以卡片形式展示评论、反讽概率与分布统计。

## 技术栈

**后端**
- Python / Flask / Flask-CORS / Flask-SocketIO
- Selenium + webdriver-manager（评论采集）
- yt-dlp（视频直链解析）
- requests（视频流转发与大模型调用）
- SiliconFlow 大模型 API + 本地反讽关键词库（降级兜底）

**前端**
- Vue 3 + Vite
- Element Plus + Axios + socket.io-client

## 目录结构

```
danmaku-sarcasm-sentiment/
├── bilibili_api.py          # Flask 后端：视频代理、评论采集、AI 分析、SocketIO 推送
├── sarcastic_keywords.py    # 本地反讽关键词库（287 条，降级兜底）
├── get_mp4_urls.py          # 批量提取视频 MP4 直链的工具脚本
├── requirements.txt
└── frontend/                # Vue 3 前端工程
    └── src/
        ├── App.vue          # 主页面：输入链接、视频预览、结果展示
        └── components/
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

> 评论采集依赖本地 Chrome 浏览器，webdriver-manager 会自动匹配驱动。

### 2. 配置大模型密钥

源码中的 API Key 已替换为占位符 `YOUR_API_KEY`，请填入你自己的 SiliconFlow 密钥（或改为从环境变量读取）后再运行。未配置时分析会自动走本地关键词库兜底。

### 3. 启动后端

```bash
python bilibili_api.py
```

### 4. 启动前端

```bash
cd frontend
npm install
npm run dev
```

浏览器打开前端地址，粘贴 B 站视频链接即可开始分析。

## 说明

本项目为课程实践作品，大模型密钥等敏感配置已从代码中移除，请以占位符或环境变量方式注入后再运行。
