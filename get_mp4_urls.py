import yt_dlp
import os

def get_mp4_direct_urls(url_file, output_file="mp4_urls.txt"):
    if not os.path.exists(url_file):
        print(f"错误: 找不到文件 {url_file}")
        return

    # 读取所有 B 站视频链接
    with open(url_file, "r", encoding="utf-8") as f:
        urls = [line.strip() for line in f if line.strip()]

    if not urls:
        print(f"错误: {url_file} 为空")
        return

    print(f"准备提取 {len(urls)} 个视频的 MP4 直链...")

    # 配置 yt-dlp
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
    }

    results = []
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        for i, url in enumerate(urls, 1):
            print(f"正在处理第 {i}/{len(urls)} 个: {url}")
            try:
                # 提取完整视频信息
                info = ydl.extract_info(url, download=False)
                title = info.get('title', '未知标题')
                
                formats = info.get('formats', [])
                
                # 寻找同时包含视频和音频的单一格式（非 DASH）
                # 这类链接通常分辨率较低，但可以直接播放
                single_file_formats = [
                    f for f in formats 
                    if f.get('url') and f.get('vcodec') != 'none' and f.get('acodec') != 'none'
                ]
                
                direct_url = None
                
                if single_file_formats:
                    # 优先取 mp4 扩展名的
                    mp4_files = [f for f in single_file_formats if f.get('ext') == 'mp4']
                    if mp4_files:
                        direct_url = sorted(mp4_files, key=lambda x: x.get('height') or 0, reverse=True)[0]['url']
                    else:
                        direct_url = sorted(single_file_formats, key=lambda x: x.get('height') or 0, reverse=True)[0]['url']
                
                # 如果找不到单一文件，则尝试提取最高画质的视频流（注意：无音频！）
                if not direct_url:
                    video_only_formats = [
                        f for f in formats 
                        if f.get('url') and f.get('vcodec') != 'none' and f.get('acodec') == 'none'
                    ]
                    if video_only_formats:
                        direct_url = sorted(video_only_formats, key=lambda x: x.get('height') or 0, reverse=True)[0]['url']
                        print(f"警告: {title[:20]}... 仅获取到视频轨道，无声音。")

                if direct_url:
                    print(f"成功获取直链: {title[:30]}...")
                    with open(output_file, "a", encoding="utf-8") as f_out:
                        f_out.write(f"标题: {title}\n")
                        f_out.write(f"视频页: {url}\n")
                        f_out.write(f"MP4直链: {direct_url}\n")
                        f_out.write(f"注意: 必须设置 Referer: https://www.bilibili.com/ 才能访问，否则会报 403 错误。\n")
                        f_out.write("-" * 50 + "\n")
                    results.append(direct_url)
                else:
                    print(f"无法从 {url} 中提取任何有效的直链")
            except Exception as e:
                print(f"处理 {url} 时出错: {str(e)[:100]}...")

    return results

if __name__ == "__main__":
    input_file = "video_urls.txt"
    output_file = "mp4_urls.txt"
    
    # 清空旧的输出文件并写入头部说明
    with open(output_file, "w", encoding="utf-8") as f_head:
        f_head.write("=" * 60 + "\n")
        f_head.write("Bilibili 视频直链提取结果\n")
        f_head.write("使用说明：\n")
        f_head.write("1. 这些链接带有防盗链，直接点击浏览器可能会报 403 或 Akamai 错误。\n")
        f_head.write("2. 必须在请求头中加入 Referer: https://www.bilibili.com/ 才能下载或播放。\n")
        f_head.write("3. 建议使用支持设置 Referer 的下载工具（如 IDM, Motrix, curl, wget）。\n")
        f_head.write("4. 示例命令: curl -H \"Referer: https://www.bilibili.com/\" -o video.mp4 \"URL\"\n")
        f_head.write("=" * 60 + "\n\n")
        
    get_mp4_direct_urls(input_file, output_file)
    print(f"\n提取完成！MP4 直链已保存至 {output_file}")
