import io
import os
import shutil
import tempfile
import threading
from flask import Flask, render_template, request, jsonify, send_file, after_this_request
import yt_dlp

# ── 쿠키 초기화 ───────────────────────────────────
# 우선순위: 1) cookies.txt 파일  2) COOKIES_CONTENT 환경변수
_COOKIES_FILE = None

def _init_cookies():
    global _COOKIES_FILE
    local = os.path.join(os.path.dirname(__file__), "cookies.txt")
    if os.path.exists(local):
        _COOKIES_FILE = local
        print(f"[cookies] cookies.txt 사용: {local}")
        return
    content = os.environ.get("COOKIES_CONTENT", "").strip()
    if content:
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8")
        tmp.write(content)
        tmp.close()
        _COOKIES_FILE = tmp.name
        print(f"[cookies] 환경변수(COOKIES_CONTENT) → {tmp.name}")

_init_cookies()

# ── 공통 yt-dlp 옵션 ──────────────────────────────
def base_ydl_opts():
    opts = {
        "quiet": True,
        "no_warnings": True,
        "extractor_args": {
            "youtube": {"player_client": ["android", "web"]}
        },
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Linux; Android 13; Pixel 7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/116.0.0.0 Mobile Safari/537.36"
            )
        },
    }
    if _COOKIES_FILE:
        opts["cookiefile"] = _COOKIES_FILE
    return opts

def ffmpeg_available():
    return shutil.which("ffmpeg") is not None

def format_duration(seconds):
    if not seconds:
        return "0:00"
    seconds = int(seconds)
    h, m, s = seconds // 3600, (seconds % 3600) // 60, seconds % 60
    return f"{h}:{m:02d}:{s:02d}" if h > 0 else f"{m}:{s:02d}"


app = Flask(__name__)

# ── OG 이미지 생성 ─────────────────────────────────
def _make_og_image():
    from PIL import Image, ImageDraw, ImageFont

    W, H = 1200, 630
    CREAM  = (245, 240, 232)
    CORAL  = (217, 119, 87)
    CORAL2 = (201, 100, 66)
    DARK   = (26, 22, 20)
    GRAY   = (107, 101, 96)
    WHITE  = (255, 255, 255)

    img  = Image.new("RGB", (W, H), CREAM)
    draw = ImageDraw.Draw(img)

    # 왼쪽 코랄 패널
    draw.rectangle([0, 0, 420, H], fill=CORAL)
    # 패널 오른쪽 원형 장식
    draw.ellipse([300, -100, 620, 220], fill=CORAL2)
    draw.ellipse([260, 440, 520, 700], fill=CORAL2)

    # 폰트 탐색 (Docker: NotoSansCJK, Windows: 맑은 고딕)
    def load_font(size, bold=False):
        candidates = [
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc" if bold else
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc" if bold else
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "C:/Windows/Fonts/malgunbd.ttf" if bold else "C:/Windows/Fonts/malgun.ttf",
            "C:/Windows/Fonts/arialbd.ttf"  if bold else "C:/Windows/Fonts/arial.ttf",
        ]
        for path in candidates:
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
        return ImageFont.load_default()

    # 왼쪽: 큰 음표
    note_font = load_font(220)
    draw.text((210, 315), "♪", fill=WHITE, font=note_font, anchor="mm")

    # 오른쪽: 텍스트
    title_font = load_font(82, bold=True)
    sub_font   = load_font(38)
    tag_font   = load_font(30)

    draw.text((810, 230), "뮤직 다운", fill=DARK, font=title_font, anchor="mm")
    draw.text((810, 330), "YouTube 음악 검색 · 재생 · MP3 저장", fill=GRAY, font=sub_font, anchor="mm")

    # 태그 배지
    tags = ["🎵 무료", "📱 모바일 지원", "⬇ MP3 다운로드"]
    tx = 590
    for tag in tags:
        tw = draw.textlength(tag, font=tag_font) + 32
        draw.rounded_rectangle([tx, 400, tx + tw, 448], radius=20, fill=CORAL)
        draw.text((tx + tw / 2, 424), tag, fill=WHITE, font=tag_font, anchor="mm")
        tx += tw + 16

    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    buf.seek(0)
    return buf


@app.route("/og-image.png")
def og_image():
    buf = _make_og_image()
    return send_file(buf, mimetype="image/png", max_age=86400)


# ── 페이지 ────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")


# ── 검색 ──────────────────────────────────────────
@app.route("/api/search")
def search():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify([])

    opts = base_ydl_opts()
    opts.update({"extract_flat": True, "skip_download": True})

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
                "video_id":  vid_id,
                "title":     e.get("title", "Unknown"),
                "thumbnail": e.get("thumbnail") or f"https://i.ytimg.com/vi/{vid_id}/mqdefault.jpg",
                "duration":  format_duration(e.get("duration")),
            })
        return jsonify(videos)
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500


# ── 스트리밍 ──────────────────────────────────────
@app.route("/api/stream/<video_id>")
def stream(video_id):
    opts = base_ydl_opts()
    opts.update({"format": "bestaudio/best", "skip_download": True})
    try:
        url = f"https://www.youtube.com/watch?v={video_id}"
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        audio_url = info.get("url")
        if not audio_url:
            for fmt in reversed(info.get("formats", [])):
                if fmt.get("url"):
                    audio_url = fmt["url"]
                    break
        return jsonify({"url": audio_url, "title": info.get("title", "")})
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500


# ── 다운로드 ──────────────────────────────────────
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
        target_ext, mime = ".mp3", "audio/mpeg"
    else:
        opts["format"] = "bestaudio[ext=m4a]/bestaudio/best"
        target_ext, mime = None, "audio/mp4"

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=True)
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
        return send_file(audio_path, as_attachment=True, download_name=dl_name, mimetype=mime)

    except Exception as ex:
        return jsonify({"error": str(ex)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
