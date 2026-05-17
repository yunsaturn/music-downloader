import io
import json
import os
import re
import shutil
import tempfile
import threading
import urllib.parse
import urllib.request
from flask import Flask, render_template, request, jsonify, send_file, after_this_request
import yt_dlp

# ── 쿠키 초기화 ───────────────────────────────────
_COOKIES_FILE = None

def _init_cookies():
    global _COOKIES_FILE
    local = os.path.join(os.path.dirname(__file__), "cookies.txt")
    if os.path.exists(local):
        _COOKIES_FILE = local
        print(f"[cookies] cookies.txt 사용")
        return
    content = os.environ.get("COOKIES_CONTENT", "").strip()
    if content:
        # Railway 환경변수는 줄바꿈이 리터럴 \n 으로 저장되는 경우가 있음 → 실제 개행으로 변환
        content = content.replace("\\n", "\n").replace("\\t", "\t")
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8")
        tmp.write(content)
        tmp.close()
        _COOKIES_FILE = tmp.name
        # 쿠키 파일 유효성 간단 확인
        line_count = content.count("\n")
        print(f"[cookies] COOKIES_CONTENT 로드됨 — {line_count}줄, 경로={tmp.name}")

_init_cookies()

# ── yt-dlp 옵션 ───────────────────────────────────
def search_ydl_opts():
    """검색용 — android client 없이 기본 동작 (검색과 충돌함)"""
    opts = {"quiet": True, "no_warnings": True,
            "extract_flat": True, "skip_download": True}
    if _COOKIES_FILE:
        opts["cookiefile"] = _COOKIES_FILE
    return opts

def stream_ydl_opts():
    """스트림/다운로드용 기본 옵션 (android client 제거 — 포맷 충돌 방지)"""
    opts = {"quiet": True, "no_warnings": True}
    if _COOKIES_FILE:
        opts["cookiefile"] = _COOKIES_FILE
    return opts

def ffmpeg_available():
    return shutil.which("ffmpeg") is not None

def format_duration(seconds):
    if not seconds:
        return ""
    seconds = int(seconds)
    h, m, s = seconds // 3600, (seconds % 3600) // 60, seconds % 60
    return f"{h}:{m:02d}:{s:02d}" if h > 0 else f"{m}:{s:02d}"

def parse_iso_duration(iso):
    """PT1H23M45S → 1:23:45"""
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return ""
    h, mn, s = int(m.group(1) or 0), int(m.group(2) or 0), int(m.group(3) or 0)
    return f"{h}:{mn:02d}:{s:02d}" if h else f"{mn}:{s:02d}"


app = Flask(__name__)

# ── YouTube Data API v3 검색 ──────────────────────
def search_via_youtube_api(q, api_key):
    """YouTube Data API v3 — 봇 감지 없음, 무료 100회/일"""
    # 1) 검색
    search_url = "https://www.googleapis.com/youtube/v3/search?" + urllib.parse.urlencode({
        "part": "snippet", "q": q, "type": "video",
        "maxResults": 15, "key": api_key,
    })
    with urllib.request.urlopen(search_url, timeout=10) as r:
        items = json.loads(r.read()).get("items", [])

    if not items:
        return []

    # 2) 재생시간 일괄 조회
    ids = ",".join(it["id"]["videoId"] for it in items)
    detail_url = "https://www.googleapis.com/youtube/v3/videos?" + urllib.parse.urlencode({
        "part": "contentDetails", "id": ids, "key": api_key,
    })
    with urllib.request.urlopen(detail_url, timeout=10) as r:
        dur_map = {
            it["id"]: parse_iso_duration(it["contentDetails"]["duration"])
            for it in json.loads(r.read()).get("items", [])
        }

    videos = []
    for it in items:
        vid_id  = it["id"]["videoId"]
        snippet = it["snippet"]
        thumbs  = snippet.get("thumbnails", {})
        thumb   = (thumbs.get("medium") or thumbs.get("high") or thumbs.get("default") or {}).get("url") \
                  or f"https://i.ytimg.com/vi/{vid_id}/mqdefault.jpg"
        videos.append({
            "video_id":  vid_id,
            "title":     snippet.get("title", ""),
            "thumbnail": thumb,
            "duration":  dur_map.get(vid_id, ""),
        })
    return videos

# ── yt-dlp 검색 (fallback) ────────────────────────
def search_via_ytdlp(q):
    opts = search_ydl_opts()
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
    return videos


# ── OG 이미지 ─────────────────────────────────────
def _make_og_image():
    from PIL import Image, ImageDraw, ImageFont

    W, H   = 1200, 630
    CREAM  = (245, 240, 232)
    CORAL  = (217, 119, 87)
    CORAL2 = (201, 100, 66)
    DARK   = (26, 22, 20)
    GRAY   = (107, 101, 96)
    WHITE  = (255, 255, 255)

    img  = Image.new("RGB", (W, H), CREAM)
    draw = ImageDraw.Draw(img)

    draw.rectangle([0, 0, 420, H], fill=CORAL)
    draw.ellipse([300, -100, 620, 220], fill=CORAL2)
    draw.ellipse([260, 440, 520, 700], fill=CORAL2)

    def load_font(size, bold=False):
        candidates = [
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc" if bold else
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc" if bold else
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "C:/Windows/Fonts/malgunbd.ttf" if bold else "C:/Windows/Fonts/malgun.ttf",
        ]
        for path in candidates:
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
        return ImageFont.load_default()

    draw.text((210, 315), "♪",  fill=WHITE,  font=load_font(220),      anchor="mm")
    draw.text((810, 230), "뮤직 다운",        fill=DARK,   font=load_font(82, bold=True), anchor="mm")
    draw.text((810, 330), "YouTube 음악 검색 · 재생 · MP3 저장",
              fill=GRAY, font=load_font(38), anchor="mm")

    tag_font = load_font(30)
    tx = 590
    for tag in ["🎵 무료", "📱 모바일 지원", "⬇ MP3 다운로드"]:
        tw = int(draw.textlength(tag, font=tag_font)) + 32
        draw.rounded_rectangle([tx, 400, tx + tw, 448], radius=20, fill=CORAL)
        draw.text((tx + tw / 2, 424), tag, fill=WHITE, font=tag_font, anchor="mm")
        tx += tw + 16

    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    buf.seek(0)
    return buf


# ── Routes ────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/og-image.png")
def og_image():
    return send_file(_make_og_image(), mimetype="image/png", max_age=86400)

@app.route("/api/search")
def search():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify([])

    api_key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    try:
        if api_key:
            videos = search_via_youtube_api(q, api_key)
        else:
            videos = search_via_ytdlp(q)
        return jsonify(videos)
    except Exception as ex:
        # API 실패 시 yt-dlp로 재시도
        if api_key:
            try:
                return jsonify(search_via_ytdlp(q))
            except Exception:
                pass
        return jsonify({"error": str(ex)}), 500

# 포맷 선택자: 오디오 전용 우선, 없으면 최상위 포맷
# ext 제한을 없애고 가장 넓게 잡음 (Railway IP 환경에서 제공 포맷이 다를 수 있음)
AUDIO_FORMAT = "bestaudio/best"

# 다운로드 시 시도할 player_client 순서
DOWNLOAD_CLIENTS = ["ios", "mweb", "web", None]

def _make_dl_opts(extra, client=None):
    """player_client 지정 가능한 yt-dlp 옵션 생성"""
    opts = {"quiet": True, "no_warnings": True, **extra}
    if client:
        opts["extractor_args"] = {"youtube": {"player_client": [client]}}
    if _COOKIES_FILE:
        opts["cookiefile"] = _COOKIES_FILE
    return opts

def _download_with_fallback(video_id, extra):
    """여러 player_client로 순차 시도 → 성공하면 info 반환"""
    yt_url   = f"https://www.youtube.com/watch?v={video_id}"
    last_err = None
    for client in DOWNLOAD_CLIENTS:
        opts = _make_dl_opts(extra, client)
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(yt_url, download=True)
            print(f"[download] 성공 client={client}")
            return info
        except Exception as e:
            print(f"[download] 실패 client={client}: {e}")
            last_err = e
    raise last_err


@app.route("/api/stream/<video_id>")
def stream(video_id):
    """재생은 IFrame API가 담당 — 이 엔드포인트는 미사용"""
    return jsonify({"error": "재생은 브라우저 IFrame API를 사용합니다"}), 400


@app.route("/api/debug/<video_id>")
def debug_formats(video_id):
    """쿠키·포맷 진단용 엔드포인트 (배포 후 브라우저에서 직접 호출)"""
    yt_url = f"https://www.youtube.com/watch?v={video_id}"
    opts = {**stream_ydl_opts(), "skip_download": True, "quiet": False}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(yt_url, download=False)
        fmts = [
            {"id": f.get("format_id"), "ext": f.get("ext"),
             "acodec": f.get("acodec"), "vcodec": f.get("vcodec"),
             "abr": f.get("abr"), "filesize": f.get("filesize")}
            for f in (info.get("formats") or [])
        ]
        return jsonify({
            "cookie_file": _COOKIES_FILE,
            "cookie_loaded": bool(_COOKIES_FILE),
            "title": info.get("title"),
            "format_count": len(fmts),
            "formats": fmts,
        })
    except Exception as e:
        return jsonify({"error": str(e), "cookie_file": _COOKIES_FILE}), 500


@app.route("/api/download/<video_id>")
def download(video_id):
    tmp_dir    = tempfile.mkdtemp()
    has_ffmpeg = ffmpeg_available()
    extra      = {
        "format":  AUDIO_FORMAT,
        "outtmpl": os.path.join(tmp_dir, "%(title)s.%(ext)s"),
    }
    if has_ffmpeg:
        extra["postprocessors"] = [{"key": "FFmpegExtractAudio",
                                    "preferredcodec": "mp3", "preferredquality": "192"}]
        target_ext, mime = ".mp3", "audio/mpeg"
    else:
        target_ext, mime = None, "audio/mp4"

    try:
        info  = _download_with_fallback(video_id, extra)
        title = info.get("title", video_id)

        if target_ext:
            files = [f for f in os.listdir(tmp_dir) if f.endswith(target_ext)]
        else:
            files = [f for f in os.listdir(tmp_dir)
                     if f.endswith((".m4a", ".webm", ".ogg", ".opus", ".mp3"))]
        if not files:
            return jsonify({"error": "NO_FILE"}), 500

        audio_path = os.path.join(tmp_dir, files[0])
        actual_ext = os.path.splitext(files[0])[1]

        @after_this_request
        def cleanup(response):
            threading.Thread(target=lambda: (
                os.remove(audio_path), os.rmdir(tmp_dir)
            ), daemon=True).start()
            return response

        safe    = "".join(c for c in title if c not in r'\/:*?"<>|').strip()
        dl_name = f"{safe}.mp3" if has_ffmpeg else f"{safe}{actual_ext}"
        return send_file(audio_path, as_attachment=True, download_name=dl_name, mimetype=mime)

    except Exception as ex:
        err = str(ex)
        # 봇 감지 / 인증 필요 에러 → 사용자 친화적 메시지
        if "sign in" in err.lower() or "bot" in err.lower() or "confirm" in err.lower():
            return jsonify({"error": "COOKIE_REQUIRED"}), 403
        return jsonify({"error": err}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
