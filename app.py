import os
import shutil
import tempfile
import threading
from flask import Flask, render_template, request, jsonify, send_file, after_this_request
import yt_dlp

def ffmpeg_available():
    return shutil.which("ffmpeg") is not None

# cookies.txt 경로 (프로젝트 루트에 있으면 자동 사용)
COOKIES_FILE = os.path.join(os.path.dirname(__file__), "cookies.txt")

def base_ydl_opts():
    """모든 yt-dlp 요청에 공통 적용되는 옵션 (봇 감지 우회 포함)"""
    opts = {
        "quiet": True,
        "no_warnings": True,
        # android 클라이언트 → YouTube 봇 감지 우회에 효과적
        "extractor_args": {
            "youtube": {
                "player_client": ["android", "web"],
            }
        },
        # 최신 yt-dlp가 아닌 경우 대비 user-agent 설정
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Linux; Android 13; Pixel 7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/116.0.0.0 Mobile Safari/537.36"
            )
        },
    }
    # cookies.txt 있으면 자동 사용
    if os.path.exists(COOKIES_FILE):
        opts["cookiefile"] = COOKIES_FILE
    return opts


app = Flask(__name__)

def format_duration(seconds):
    if not seconds:
        return "0:00"
    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/search")
def search():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify([])

    opts = base_ydl_opts()
    opts.update({
        "extract_flat": True,
        "skip_download": True,
    })

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            result = ydl.extract_info(f"ytsearch15:{q}", download=False)
        entries = result.get("entries", []) or []
        videos = []
        for e in entries:
            if not e:
                continue
            vid_id = e.get("id") or e.get("url", "").split("v=")[-1]
            videos.append({
                "video_id": vid_id,
                "title": e.get("title", "Unknown"),
                "thumbnail": e.get("thumbnail") or f"https://i.ytimg.com/vi/{vid_id}/mqdefault.jpg",
                "duration": format_duration(e.get("duration")),
            })
        return jsonify(videos)
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500


@app.route("/api/stream/<video_id>")
def stream(video_id):
    opts = base_ydl_opts()
    opts.update({
        "format": "bestaudio/best",
        "skip_download": True,
    })
    try:
        url = f"https://www.youtube.com/watch?v={video_id}"
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        # 오디오 전용 URL 추출
        audio_url = info.get("url")
        if not audio_url:
            # formats 리스트에서 오디오 URL 탐색
            for fmt in reversed(info.get("formats", [])):
                if fmt.get("url"):
                    audio_url = fmt["url"]
                    break
        title = info.get("title", "")
        return jsonify({"url": audio_url, "title": title})
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500


@app.route("/api/download/<video_id>")
def download(video_id):
    tmp_dir = tempfile.mkdtemp()
    output_template = os.path.join(tmp_dir, "%(title)s.%(ext)s")
    has_ffmpeg = ffmpeg_available()

    opts = base_ydl_opts()
    opts["outtmpl"] = output_template

    if has_ffmpeg:
        opts["format"] = "bestaudio/best"
        opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }]
        target_ext = ".mp3"
        mime = "audio/mpeg"
    else:
        opts["format"] = "bestaudio[ext=m4a]/bestaudio/best"
        target_ext = None
        mime = "audio/mp4"

    try:
        url = f"https://www.youtube.com/watch?v={video_id}"
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get("title", video_id)

        if target_ext:
            audio_files = [f for f in os.listdir(tmp_dir) if f.endswith(target_ext)]
        else:
            audio_files = [f for f in os.listdir(tmp_dir)
                           if f.endswith((".m4a", ".webm", ".ogg", ".opus", ".mp3"))]

        if not audio_files:
            return jsonify({"error": "오디오 파일 변환/다운로드 실패"}), 500

        audio_path = os.path.join(tmp_dir, audio_files[0])
        actual_ext = os.path.splitext(audio_files[0])[1]

        @after_this_request
        def cleanup(response):
            def _remove():
                try:
                    os.remove(audio_path)
                    os.rmdir(tmp_dir)
                except Exception:
                    pass
            threading.Thread(target=_remove, daemon=True).start()
            return response

        safe_title = "".join(c for c in title if c not in r'\/:*?"<>|').strip()
        dl_name = f"{safe_title}.mp3" if has_ffmpeg else f"{safe_title}{actual_ext}"
        return send_file(
            audio_path,
            as_attachment=True,
            download_name=dl_name,
            mimetype=mime,
        )
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
