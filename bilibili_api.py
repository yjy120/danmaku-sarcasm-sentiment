import time
import threading
import json
import random
import requests
from concurrent.futures import ThreadPoolExecutor
from sarcastic_keywords import SARCASTIC_KEYWORDS
from flask import Flask, request, jsonify, Response
from flask_cors import CORS
from flask_socketio import SocketIO, emit
import re
import logging

# 禁用 Flask/Werkzeug 的默认日志，减少干扰
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
import yt_dlp
import os
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- 本地通信绕过系统/沙箱代理 ---
# Selenium 与 ChromeDriver 通过 localhost 临时端口通信，若系统设置了
# HTTP_PROXY（如部分沙箱/代理环境），请求会被代理拦截并返回
# "unhandled request"，导致 driver.get() 失败。
# 将本地地址加入 no_proxy 后：本地通信直连，外部请求（B站/LLM API）不受影响。
os.environ["no_proxy"] = "localhost,127.0.0.1,::1"
os.environ["NO_PROXY"] = "localhost,127.0.0.1,::1"

# --- 解决 webdriver_manager 连接超时问题 (针对国内环境) ---
os.environ['WDM_MIRROR'] = 'https://npmmirror.com/mirrors/chromedriver'
os.environ['WDM_SSL_VERIFY'] = '0' # 禁用 SSL 验证，防止代理干扰

app = Flask(__name__)
CORS(app)
# 使用 threading 模式启动，避免 eventlet 补丁导致的驱动启动冲突
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# --- 视频代理逻辑 (解决 Referer 403 问题) ---
@app.route('/api/video/proxy')
def video_proxy():
    video_url = request.args.get('url')
    if not video_url:
        return "Missing URL", 400
    
    headers = {
        'Referer': 'https://www.bilibili.com/',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    # 转发 Range 请求头，以便前端视频播放器可以拖动进度条
    range_header = request.headers.get('Range')
    if range_header:
        headers['Range'] = range_header

    try:
        # 使用 stream=True 进行流式转发，避免内存占用过大
        resp = requests.get(video_url, headers=headers, stream=True, timeout=10)
        
        # 排除掉一些不适合直接转发的响应头
        excluded_headers = ['content-encoding', 'content-length', 'transfer-encoding', 'connection']
        headers_to_forward = [
            (name, value) for name, value in resp.raw.headers.items()
            if name.lower() not in excluded_headers
        ]
        
        # 将原始响应的 Content-Length 也带回去，确保浏览器知道视频大小
        if 'Content-Length' in resp.headers:
            headers_to_forward.append(('Content-Length', resp.headers['Content-Length']))

        return Response(
            resp.iter_content(chunk_size=1024 * 64),
            status=resp.status_code,
            headers=headers_to_forward,
            content_type=resp.headers.get('Content-Type')
        )
    except Exception as e:
        return str(e), 500

# --- LLM 配置 (SiliconFlow) ---
API_KEY = "YOUR_API_KEY"
API_URL = "https://api.siliconflow.cn/v1/chat/completions"
MODEL_NAME = "Qwen/Qwen2.5-7B-Instruct"

def get_local_fallback_analysis(comment_text):
    """
    本地兜底分析逻辑：当 AI 接口彻底失败时使用外部加载的关键词列表。
    """
    # 统计关键词命中情况
    hit_count = sum(1 for kw in SARCASTIC_KEYWORDS if kw in comment_text.lower())
    
    if hit_count > 0:
        # 简单估算概率
        prob = min(0.3 + (hit_count * 0.15), 0.85)
        return prob, f"AI接口超时，本地关键词检测到 {hit_count} 处疑似反讽词汇"
    else:
        return 0.1, "AI接口超时，本地未检测到明显反讽特征"

def analyze_sarcasm_with_llm(comment_text, video_title=""):
    """
    使用 SiliconFlow API 分析评论的反讽概率
    增加重试机制、超时处理和本地兜底策略
    """
    if not API_KEY or "sk-" not in API_KEY:
        return random.random(), "未配置 API Key，返回模拟结果"

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    
    prompt = f"""
    你是一个反讽分析专家。请分析以下评论是否具有反讽（讽刺）意味。
    视频标题：{video_title}
    用户评论内容："{comment_text}"
    
    请严格按以下 JSON 格式返回分析结果：
    {{
      "probability": 0.0-1.0 之间的浮点数,
      "explanation": "一句简短的中文分析理由，说明为什么它是或不是反讽"
    }}
    不要包含任何 markdown 代码块标记，只返回 JSON 字符串。
    """
    
    data = {
        "model": MODEL_NAME,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 200
    }
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            if attempt > 0:
                print(f"[AI分析] 正在进行第 {attempt + 1} 次尝试...")
            
            # 缩短单次超时时间到 30 秒，配合并发可以更快触发重试或兜底
            response = requests.post(API_URL, headers=headers, json=data, timeout=30)
            res_json = response.json()
            
            if 'choices' not in res_json:
                print(f"[AI分析] API 返回异常: {res_json}")
                if attempt < max_retries - 1:
                    time.sleep(2)
                    continue
                # API 彻底异常，使用本地兜底
                return get_local_fallback_analysis(comment_text)
                
            content = res_json['choices'][0]['message']['content'].strip()
            content = content.replace("```json", "").replace("```", "").strip()
            result = json.loads(content)
            prob = float(result.get("probability", 0.5))
            expl = result.get("explanation", "分析完毕")
            print(f"[AI分析] 分析成功: 概率={prob}, 理由={expl}")
            return prob, expl
            
        except requests.exceptions.Timeout:
            print(f"[AI分析] 第 {attempt + 1} 次请求超时 (read timeout=30)")
            if attempt < max_retries - 1:
                time.sleep(2) # 等待 2 秒后重试
                continue
            # 彻底超时，使用本地兜底
            return get_local_fallback_analysis(comment_text)
        except Exception as e:
            print(f"[AI分析] 发生错误: {e}")
            if attempt < max_retries - 1:
                time.sleep(2)
                continue
            # 彻底报错，使用本地兜底
            return get_local_fallback_analysis(comment_text)
    
    # 达到最大重试次数，使用本地兜底
    return get_local_fallback_analysis(comment_text)

# --- 浏览器内倒计时注入 ---
def inject_countdown_overlay(driver, timeout=40):
    inject_js = f"""
    (function() {{
        let old = document.getElementById('trae-countdown-overlay');
        if (old) old.remove();
        
        let div = document.createElement('div');
        div.id = 'trae-countdown-overlay';
        div.style.position = 'fixed';
        div.style.top = '20px';
        div.style.left = '50%';
        div.style.transform = 'translateX(-50%)';
        div.style.zIndex = '2147483647';
        div.style.backgroundColor = '#fb7299';
        div.style.color = 'white';
        div.style.padding = '15px 30px';
        div.style.borderRadius = '30px';
        div.style.fontSize = '20px';
        div.style.fontWeight = 'bold';
        div.style.boxShadow = '0 4px 15px rgba(0,0,0,0.3)';
        div.style.textAlign = 'center';
        div.style.pointerEvents = 'none';
        div.innerHTML = '🔒 登录倒计时：<span id="trae-timer">{timeout}</span> 秒 (登录后请勿关闭浏览器)';
        document.body.appendChild(div);
        
        window.traeTimeLeft = {timeout};
        let timer = setInterval(() => {{
            window.traeTimeLeft--;
            let timerSpan = document.getElementById('trae-timer');
            if (timerSpan) timerSpan.innerText = window.traeTimeLeft;
            if (window.traeTimeLeft <= 0) {{
                clearInterval(timer);
                div.innerHTML = '⌛ 时间到，正在开始提取数据...';
            }}
        }}, 1000);
    }})();
    """
    try:
        driver.execute_script(inject_js)
    except:
        pass

# --- 链接清洗：兼容 B 站分享文案（如"【标题】 https://b23.tv/xxx"） ---
def clean_video_url(raw_url):
    """
    从用户输入中提取纯净的视频链接。
    B站"分享"按钮复制的文案带有标题前缀，直接传给 yt-dlp 会报
    "is not a valid URL"，这里用正则提取其中的 http(s) 链接。
    """
    if not raw_url:
        return ""
    match = re.search(r'https?://[^\s\'"<>\]】]+', str(raw_url))
    if match:
        # 去掉文案可能带上的尾部标点
        return match.group(0).rstrip('。，、,.;；!！?？')
    return str(raw_url).strip()

# --- MP4 提取逻辑 (yt-dlp) ---
def get_mp4_url(url):
    print(f"\n[视频提取] 正在处理链接: {url}")
    # 配置 yt-dlp
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # 提取完整视频信息
            info = ydl.extract_info(url, download=False)
            title = info.get('title', '未知标题')
            print(f"[视频提取] 成功解析视频信息: {title[:30]}...")
            
            formats = info.get('formats', [])
            
            # 寻找同时包含视频和音频的单一格式（非 DASH）
            # 这类链接通常分辨率较低，但可以直接播放
            single_file_formats = [
                f for f in formats 
                if f.get('url') and f.get('vcodec') != 'none' and f.get('acodec') != 'none'
            ]
            
            direct_url = None
            is_video_only = False
            
            if single_file_formats:
                # 优先取 mp4 扩展名的
                mp4_files = [f for f in single_file_formats if f.get('ext') == 'mp4']
                if mp4_files:
                    direct_url = sorted(mp4_files, key=lambda x: x.get('height') or 0, reverse=True)[0]['url']
                    print(f"[视频提取] 成功获取有声音的 MP4 直链: {title[:30]}...")
                else:
                    direct_url = sorted(single_file_formats, key=lambda x: x.get('height') or 0, reverse=True)[0]['url']
                    print(f"[视频提取] 成功获取有声音的直链 (非 MP4): {title[:30]}...")
            
            # 如果找不到单一文件，则尝试提取最高画质的视频流（注意：无音频！）
            if not direct_url:
                video_only_formats = [
                    f for f in formats 
                    if f.get('url') and f.get('vcodec') != 'none' and f.get('acodec') == 'none'
                ]
                if video_only_formats:
                    direct_url = sorted(video_only_formats, key=lambda x: x.get('height') or 0, reverse=True)[0]['url']
                    is_video_only = True
                    print(f"[视频提取] 警告: {title[:20]}... 仅获取到视频轨道，无声音。")
            
            if direct_url:
                return {
                    "title": title,
                    "url": direct_url,
                    "is_video_only": is_video_only
                }
            else:
                print(f"[视频提取] 无法从 {url} 中提取任何有效的直链")
                return None
    except Exception as e:
        print(f"[视频提取] 提取失败: {str(e)}")
        return None

# --- 评论提取逻辑 (Selenium + Shadow DOM) ---
def parse_count(count_str):
    if not count_str or count_str == "未知":
        return 0
    count_str = count_str.replace(",", "").strip()
    if "万" in count_str:
        return int(float(count_str.replace("万", "")) * 10000)
    try:
        return int(count_str)
    except ValueError:
        return 0

def get_comments(driver, target_url, sid=None):
    # 移除重复访问，已经在 run_extraction_task 中访问过了
    # print(f"\n[评论抓取] 正在访问: {target_url}")
    # driver.get(target_url)
    # time.sleep(5) 
    
    # 初始滚动并尝试切换到“最新”排序（以便抓取更多评论）
    try:
        driver.execute_script("""
            window.scrollTo(0, 1500);
            setTimeout(() => {
                function clickLatest() {
                    // 尝试点击“最新”排序按钮
                    let buttons = document.querySelectorAll('span, a, div, li');
                    for (let btn of buttons) {
                        if (btn.innerText === '最新' || btn.innerText === '按时间排序') {
                            btn.click();
                            return true;
                        }
                    }
                    return false;
                }
                clickLatest();
            }, 1000);
        """)
    except Exception as e:
        print(f"[评论抓取] 初始滚动/排序脚本执行失败 (可能浏览器已关闭): {e}")
        return [], "未知"

    time.sleep(3) # 给排序切换留时间
    
    # 1. 获取评论总数 (完全按照 scrape_comments.py 的逻辑)
    def get_total_count_from_page():
        for i in range(5):
            get_total_count_js = """
            function getTotalCount() {
                function findCount(root) {
                    // 尝试匹配多种可能的 ID 或类名
                    let countEl = root.querySelector('#count') || root.querySelector('.count-text');
                    if (countEl) return countEl.innerText.trim();
                    
                    let allElements = root.querySelectorAll('*');
                    for (let el of allElements) {
                        if (el.shadowRoot) {
                            let res = findCount(el.shadowRoot);
                            if (res) return res;
                        }
                    }
                    return null;
                }
                return findCount(document);
            }
            return getTotalCount();
            """
            res = driver.execute_script(get_total_count_js)
            if res: 
                print(f"[评论抓取] 第 {i+1} 次尝试成功获取总数: {res}")
                return res
            
            time.sleep(2)
        return "未知"

    total_count_str = get_total_count_from_page()
    target_count = parse_count(total_count_str)
    
    # 兜底：如果解析失败或为 0，给一个较大的默认抓取上限
    if target_count <= 0:
        print(f"[评论抓取] 无法获取有效总数 ({total_count_str})，将尝试持续抓取直到无新内容。")
        target_count = 1000 # 设置一个合理的兜底值
    else:
        print(f"[评论抓取] 页面显示的评论总数: {total_count_str} (解析为数字: {target_count})")
    
    if sid:
        socketio.emit('status', {'msg': f'检测到评论总数: {total_count_str}'}, to=sid)
    
    # 2. 提取评论 JS (从 scrape_comments.py 同步，带 Shadow DOM 递归搜索)
    js_extract_comments = """
    function getComments() {
        try {
            let comments = [];
            let allRenderers = [];
            
            function findRenderers(root) {
                if (!root) return;
                let renderers = root.querySelectorAll('bili-comment-renderer, bili-comment-reply-renderer');
                if (renderers.length > 0) {
                    allRenderers.push(...renderers);
                }
                
                let allElements = root.querySelectorAll('*');
                allElements.forEach(el => {
                    if (el.shadowRoot) {
                        findRenderers(el.shadowRoot);
                    }
                });
            }

            findRenderers(document);

            allRenderers.forEach(renderer => {
                if (renderer.shadowRoot) {
                    function findContent(r) {
                        // 1. 尝试从 bili-rich-text 提取 (根据用户截图，内容在 p#contents > span 里面)
                        let richText = r.querySelector('bili-rich-text');
                        if (richText && richText.shadowRoot) {
                            let contentP = richText.shadowRoot.querySelector('#contents');
                            if (contentP) {
                                // 提取所有 span 的文本并拼接，处理可能的表情或分段
                                let spans = contentP.querySelectorAll('span');
                                if (spans.length > 0) {
                                    return Array.from(spans).map(s => s.innerText).join('');
                                }
                                return contentP.innerText;
                            }
                        }
                        // 2. 尝试从常规类名提取
                        let textEl = r.querySelector('.comment-text') || 
                                     r.querySelector('#content') || 
                                     r.querySelector('.content') ||
                                     r.querySelector('.text');
                        if (textEl) return textEl.innerText;
                        
                        // 3. 递归在 shadowRoot 中查找更多内容 (处理嵌套回复)
                        let subRichTexts = r.querySelectorAll('bili-rich-text');
                        if (subRichTexts.length > 0) {
                            return Array.from(subRichTexts).map(rt => {
                                if (rt.shadowRoot) {
                                    let p = rt.shadowRoot.querySelector('#contents');
                                    if (p) {
                                        let spans = p.querySelectorAll('span');
                                        return spans.length > 0 ? Array.from(spans).map(s => s.innerText).join('') : p.innerText;
                                    }
                                }
                                return "";
                            }).filter(t => t.trim() !== "").join('\\n');
                        }
                        return null;
                    }
                    let text = findContent(renderer.shadowRoot);
                    if (text && text.trim()) {
                        comments.push(text.trim());
                    }
                }
            });
            return Array.from(new Set(comments));
        } catch (e) {
            return [];
        }
    }
    return getComments();
    """
    
    all_comments = []
    no_new_count = 0
    max_no_new = 4 # 增加到 12 次，给加载留更多时间
    max_loop = 300 # 增加循环次数，支持更多评论

    print("[评论抓取] 开始滚动并实时抓取评论...")
    for i in range(max_loop):
        try:
            current_batch = driver.execute_script(js_extract_comments)
        except Exception as e:
            print(f"[评论抓取] 执行提取脚本出错: {e}")
            current_batch = []

        new_found_list = []
        if current_batch:
            for c in current_batch:
                if c not in all_comments:
                    all_comments.append(c)
                    new_found_list.append(c)
        
        # 如果有新评论，通过 WebSocket 发送
        if sid and new_found_list:
            socketio.emit('new_comments', {'comments': new_found_list, 'current_total': len(all_comments)}, to=sid)
            print(f"[评论抓取] 第 {i+1} 轮：新发现 {len(new_found_list)} 条评论，累计抓取: {len(all_comments)}")
            no_new_count = 0 # 重置计数
        else:
            no_new_count += 1
            if i % 2 == 0:
                msg = f"正在滚动寻找新评论... (当前已抓取 {len(all_comments)} 条)"
                socketio.emit('status', {'msg': msg}, to=sid)
                print(f"[评论抓取] 第 {i+1} 轮：未发现新评论，已连续 {no_new_count} 次无果...")

        # 如果一开始没拿到总数，或者发现当前抓取的已经接近/超过了之前拿到的总数，尝试重新拿一次
        # 很多时候 B 站的总数显示是动态加载的
        if i % 5 == 0:
            new_total_str = get_total_count_from_page()
            new_count = parse_count(new_total_str)
            if new_count > target_count:
                target_count = new_count
                total_count_str = new_total_str
                print(f"[评论抓取] 更新评论总数: {total_count_str}")
                if sid:
                    socketio.emit('status', {'msg': f'同步评论总数: {total_count_str}'}, to=sid)

        # 检查是否完成
        if target_count > 0 and len(all_comments) >= target_count:
            # 即使达到总数，也再尝试 2 次看有没有漏掉的（B站总数有时不准）
            if no_new_count >= 2:
                if sid:
                    socketio.emit('status', {'msg': f'已达到抓取目标 ({len(all_comments)})，停止抓取。'}, to=sid)
                print(f"[评论抓取] 已达到抓取目标 ({len(all_comments)})，停止抓取。")
                break
            
        if no_new_count >= max_no_new:
            if len(all_comments) > 0:
                msg = '连续多次未发现新评论，可能已到底，停止抓取。'
            else:
                msg = '未发现任何评论，可能页面未加载成功或评论被隐藏。'
            if sid:
                socketio.emit('status', {'msg': msg}, to=sid)
            print(f"[评论抓取] {msg}")
            break
            
        # 更加稳健的滚动策略
        # 采用随机滚动，模拟人工行为，避免被风控，同时触发加载
        scroll_step = 1200 + random.randint(0, 800)
        driver.execute_script(f"window.scrollBy(0, {scroll_step});")
        
        # 如果连续没抓到，等久一点
        wait_time = 2 + (no_new_count * 0.5) if no_new_count > 0 else 2
        socketio.sleep(min(wait_time, 5)) 
        
    print(f"[评论抓取] 抓取结束，共获取唯一评论: {len(all_comments)} 条")
    return all_comments, total_count_str

@socketio.on('start_extract')
def handle_extract(data):
    video_url = clean_video_url(data.get('url'))
    sid = request.sid
    if not video_url:
        emit('error', {'msg': '参数 url 缺失'}, to=sid)
        return
        
    print(f"WebSocket 收到提取请求: {video_url}, SID: {sid}")
    
    # 在新线程中运行爬虫，避免阻塞 WebSocket 事件循环
    thread = threading.Thread(target=run_extraction_task, args=(video_url, sid))
    thread.start()

# --- 浏览器驱动单例/缓存，避免重复初始化 webdriver_manager ---
CHROME_DRIVER_PATH = None

def get_chromedriver_path():
    global CHROME_DRIVER_PATH
    if CHROME_DRIVER_PATH is None:
        try:
            print("[系统] 正在初始化 ChromeDriver...")
            CHROME_DRIVER_PATH = ChromeDriverManager().install()
        except Exception as e:
            print(f"[系统] 初始化 ChromeDriver 失败: {e}")
    return CHROME_DRIVER_PATH

def get_optimized_options():
    chrome_options = Options()
    # 核心优化：减少不必要的资源加载和后台进程
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-infobars")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-browser-side-navigation")
    chrome_options.add_argument("--no-first-run")
    chrome_options.add_argument("--no-default-browser-check")
    chrome_options.add_argument("--dns-prefetch-disable")
    
    # 额外优化提升启动速度
    chrome_options.add_argument("--disable-sync")
    chrome_options.add_argument("--disable-background-networking")
    chrome_options.add_argument("--disable-client-side-phishing-detection")
    chrome_options.add_argument("--disable-default-apps")
    chrome_options.add_argument("--mute-audio")
    chrome_options.add_argument("--disable-hang-monitor")
    chrome_options.add_argument("--disable-prompt-on-repost")
    chrome_options.add_argument("--disable-background-timer-throttling")
    chrome_options.add_argument("--disable-breakpad")
    chrome_options.add_argument("--disable-ipc-flooding-protection")
    chrome_options.add_argument("--disable-renderer-backgrounding")
    
    # 防止被识别为自动化测试 (有助于某些页面的加载)
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")

    # 策略：不等待所有资源加载，只等待 DOM 加载 (加快响应)
    chrome_options.page_load_strategy = 'eager'
    return chrome_options

def create_driver(chrome_options=None):
    """
    优化后的驱动启动逻辑
    """
    if chrome_options is None:
        chrome_options = get_optimized_options()
    
    # --- 调试逻辑：查找 Chrome 二进制文件 ---
    chrome_binaries = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe")
    ]
    for bin_path in chrome_binaries:
        if os.path.exists(bin_path):
            chrome_options.binary_location = bin_path
            break

    try:
        driver_path = get_chromedriver_path()
        if driver_path:
            service = Service(executable_path=driver_path)
            return webdriver.Chrome(service=service, options=chrome_options)
        return webdriver.Chrome(options=chrome_options)
    except Exception as e:
        print(f"[系统] 驱动启动失败，尝试直接拉起: {e}")
        try:
            return webdriver.Chrome(options=chrome_options)
        except Exception as e2:
            raise Exception(f"无法启动 Chrome 驱动: {e2}")

def run_extraction_task(video_url, sid):
    # 使用统一的优化参数
    chrome_options = get_optimized_options()
    
    # 1. 【最优先】提取视频直链并立即发送给前端
    print(f"[任务开始] 正在为 {sid} 优先提取视频信息...")
    socketio.emit('status', {'msg': '正在优先提取视频直链...'}, to=sid)
    
    mp4_data = get_mp4_url(video_url)
    if mp4_data and mp4_data.get('url'):
        socketio.emit('video_info', {
            "title": mp4_data["title"],
            "mp4_url": mp4_data["url"],
            "is_video_only": mp4_data["is_video_only"],
            "referer": "https://www.bilibili.com/"
        }, to=sid)
        socketio.emit('status', {'msg': '视频已就绪，正在启动浏览器抓取评论...'}, to=sid)
        print(f"[任务进度] 视频已发送给前端: {mp4_data['title']}")
    else:
        socketio.emit('status', {'msg': '视频直链提取失败，将仅尝试抓取评论...'}, to=sid)
    
    socketio.sleep(0.5) # 给前端一点反应时间

    # 2. 启动浏览器
    try:
        driver = create_driver(chrome_options)
    except Exception as e:
        print(f"[系统] 驱动启动失败: {e}")
        socketio.emit('error', {'msg': f"无法启动浏览器: {str(e)}"}, to=sid)
        return
    
    try:
        # 3. 直接访问视频页面 (同步 scrape_comments.py 逻辑)
        print(f"[评论抓取] 正在访问视频页: {video_url}")
        driver.get(video_url)
        
        # 注入倒计时并提示用户登录（如果需要）
        inject_countdown_overlay(driver, 40)
        socketio.emit('status', {'msg': '浏览器已开启，请在 40 秒内确保页面加载完成（如需登录请扫码）...'}, to=sid)
        
        # 等待 40 秒，期间每秒检查一下是否已经加载了评论组件
        for i in range(40, 0, -1):
            socketio.sleep(1)
            # 简单检查一下是否有评论组件，如果有可以提前结束等待
            try:
                # 增加对 driver 存活的检查
                driver.title 
                has_comments = driver.execute_script("return document.querySelector('bili-comment-renderer') !== null || document.querySelector('.comment-list') !== null")
                if has_comments:
                    print("[评论抓取] 检测到评论组件已加载，提前结束等待。")
                    break
            except Exception as e:
                # 如果获取 title 失败，说明浏览器可能被用户关闭了
                print(f"[评论抓取] 浏览器连接中断 (用户可能关闭了窗口): {e}")
                socketio.emit('status', {'msg': '检测到浏览器窗口已关闭，尝试继续提取已加载内容...'}, to=sid)
                break
        
        # 4. 抓取评论 (不再在内部重复 driver.get)
        comments, total_str = get_comments(driver, video_url, sid=sid)
        
        # 5. 发送最终汇总结果
        socketio.emit('complete', {
            "title": mp4_data["title"] if mp4_data else "未知",
            "mp4_url": mp4_data["url"] if mp4_data else None,
            "total_comments": len(comments),
            "total_from_page": total_str
        }, to=sid)
        print(f"[任务完成] {sid} 抓取任务结束")
        
    except Exception as e:
        print(f"[任务错误] {e}")
        socketio.emit('error', {'msg': f"任务运行出错: {str(e)}"}, to=sid)
    finally:
        try:
            driver.quit()
        except:
            pass

@socketio.on('analyze_irony')
def handle_analyze_irony(data):
    """
    接收前端的大模型分析请求，使用线程池并发处理以提高速度
    """
    comments = data.get('comments', [])
    video_title = data.get('title', '')
    sid = request.sid
    
    print(f"收到大模型分析请求, 共 {len(comments)} 条评论，启动并发分析...")
    
    def analyze_task(index, comment_text):
        try:
            prob, explanation = analyze_sarcasm_with_llm(comment_text, video_title)
            # 逐条发送分析结果给前端
            socketio.emit('irony_result', {
                'index': index,
                'text': comment_text,
                'probability': prob,
                'explanation': explanation
            }, to=sid)
        except Exception as e:
            print(f"[并发分析] 任务 {index} 出错: {e}")

    def run_analysis_parallel():
        # 使用线程池并发执行分析任务 (建议 5-10 个并发)
        with ThreadPoolExecutor(max_workers=8) as executor:
            # 提交所有任务
            futures = [executor.submit(analyze_task, i, text) for i, text in enumerate(comments)]
            # 等待所有任务完成
            for future in futures:
                try:
                    future.result()
                except:
                    pass
        
        socketio.emit('irony_complete', {'msg': '所有评论并发分析完毕'}, to=sid)
        print(f"[分析完成] SID: {sid} 的 {len(comments)} 条评论已全部分析结束")

    thread = threading.Thread(target=run_analysis_parallel)
    thread.start()

@app.route('/api/bilibili/extract', methods=['GET'])
def extract():
    video_url = clean_video_url(request.args.get('url'))
    if not video_url:
        return jsonify({"code": 400, "msg": "参数 url 缺失"}), 400
        
    print(f"收到请求: {video_url}")
    
    # 1. 启动浏览器用于登录
    chrome_options = get_optimized_options()
    
    try:
        driver = create_driver(chrome_options)
    except Exception as e:
        return jsonify({"code": 500, "msg": str(e)}), 500
    
    try:
        # 2. 引导登录
        driver.get("https://passport.bilibili.com/login")
        inject_countdown_overlay(driver, 40)
        
        # 循环检查登录状态或超时
        start_time = time.time()
        timeout = 40
        logged_in = False
        while time.time() - start_time < timeout:
            try:
                cookies = driver.get_cookies()
                if any(c['name'] == 'SESSDATA' for c in cookies):
                    logged_in = True
                    break
            except:
                pass # 浏览器窗口关闭等异常处理
            time.sleep(1)
        
        # 3. 抓取评论 (继续使用当前浏览器)
        comments, total_str = get_comments(driver, video_url)
        
        # 4. 提取 MP4 直链 (使用 yt-dlp)
        mp4_data = get_mp4_url(video_url)
        
        return jsonify({
            "code": 200,
            "data": {
                "title": mp4_data["title"] if mp4_data else "未知",
                "mp4_url": mp4_data["url"] if mp4_data else None,
                "is_video_only": mp4_data["is_video_only"] if mp4_data else False,
                "comments": comments,
                "total_comments": total_str,
                "referer": "https://www.bilibili.com/"
            }
        })
        
    except Exception as e:
        return jsonify({"code": 500, "msg": str(e)}), 500
    finally:
        driver.quit()

if __name__ == '__main__':
    # 启动前预热 ChromeDriver，减少第一次提取时的等待时间
    threading.Thread(target=get_chromedriver_path).start()
    
    print("Bilibili WebSocket & HTTP 提取接口已启动，监听端口 5001...")
    print("HTTP 访问示例: http://127.0.0.1:5001/api/bilibili/extract?url=https://www.bilibili.com/video/BVxxxxx")
    print("WebSocket 事件: 'start_extract', 'new_comments', 'status', 'complete', 'error'")
    socketio.run(app, host='0.0.0.0', port=5001, debug=False, allow_unsafe_werkzeug=True)
