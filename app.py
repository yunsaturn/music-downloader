import io
import json
import os
import re
import shutil
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from flask import Flask, render_template, request, jsonify, send_file, Response, after_this_request
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

# ── cobalt.tools API (셀프호스팅 인스턴스 권장) ───
# Railway IP는 YouTube에 직접 접근 불가 → cobalt 인스턴스가 대신 추출.
# COBALT_API_URL 환경변수로 본인이 호스팅한 cobalt 주소 지정.
COBALT_API  = os.environ.get("COBALT_API_URL", "https://api.cobalt.tools").rstrip("/")
COBALT_AUTH = os.environ.get("COBALT_API_KEY", "").strip()

def cobalt_get_download_url(video_id):
    """cobalt API에 요청해 MP3 다운로드 URL + 파일명 반환"""
    yt_url  = f"https://www.youtube.com/watch?v={video_id}"
    payload = json.dumps({
        "url":           yt_url,
        "downloadMode":  "audio",
        "audioFormat":   "mp3",
        "audioBitrate":  "256",
        "filenameStyle": "basic",
    }).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "Accept":       "application/json",
        "User-Agent":   "music-downloader/1.0",
    }
    if COBALT_AUTH:
        headers["Authorization"] = f"Api-Key {COBALT_AUTH}"

    req = urllib.request.Request(COBALT_API + "/", data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            result = json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"cobalt HTTP {e.code}: {body[:200]}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"cobalt 연결 실패 ({COBALT_API}): {e.reason}")

    status = result.get("status")
    print(f"[cobalt] status={status} api={COBALT_API}")

    if status in ("tunnel", "redirect"):
        return result["url"], result.get("filename") or f"{video_id}.mp3"
    if status == "error":
        err  = result.get("error", {}) or {}
        raise RuntimeError(f"cobalt error: {err.get('code', 'unknown')}")
    raise RuntimeError(f"cobalt unsupported status: {status}")


@app.route("/api/stream/<video_id>")
def stream(video_id):
    """재생은 IFrame API가 담당 — 이 엔드포인트는 미사용"""
    return jsonify({"error": "재생은 브라우저 IFrame API를 사용합니다"}), 400


@app.route("/api/debug/<video_id>")
def debug_formats(video_id):
    """쿠키·포맷 진단용 — 각 player_client별로 가용 포맷 수를 보고함"""
    yt_url = f"https://www.youtube.com/watch?v={video_id}"
    results = {"cookie_file": _COOKIES_FILE, "cookie_loaded": bool(_COOKIES_FILE), "clients": {}}

    cookie_preview = None
    if _COOKIES_FILE and os.path.exists(_COOKIES_FILE):
        try:
            with open(_COOKIES_FILE, "r", encoding="utf-8") as f:
                lines = f.readlines()
            results["cookie_lines"]    = len(lines)
            results["cookie_first"]    = lines[0].rstrip() if lines else ""
            results["cookie_has_yt"]   = any("youtube" in l for l in lines)
        except Exception as e:
            results["cookie_read_err"] = str(e)

    # process=False → 포맷 선택을 건너뛰고 원본 응답 그대로
    for client in [None, "ios", "mweb", "web", "android"]:
        opts = {"quiet": True, "no_warnings": True, "skip_download": True}
        if _COOKIES_FILE:
            opts["cookiefile"] = _COOKIES_FILE
        if client:
            opts["extractor_args"] = {"youtube": {"player_client": [client]}}
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(yt_url, download=False, process=False)
            fmts = info.get("formats") or []
            audio_only = [f for f in fmts
                          if (f.get("acodec") and f.get("acodec") != "none")
                          and (not f.get("vcodec") or f.get("vcodec") == "none")]
            results["clients"][client or "default"] = {
                "title": info.get("title"),
                "total_formats": len(fmts),
                "audio_only_formats": len(audio_only),
                "sample_format_ids": [f.get("format_id") for f in fmts[:5]],
            }
        except Exception as e:
            results["clients"][client or "default"] = {"error": str(e)[:200]}

    return jsonify(results)


@app.route("/api/download/<video_id>")
def download(video_id):
    """셀프호스팅 cobalt 인스턴스로 추출한 MP3를 클라이언트로 스트리밍"""
    try:
        file_url, filename = cobalt_get_download_url(video_id)
    except Exception as ex:
        err = str(ex)
        print(f"[download] cobalt 실패: {err}")
        low = err.lower()
        if "rate" in low or "429" in low:
            return jsonify({"error": "RATE_LIMITED"}), 429
        if "401" in low or "403" in low or "auth" in low:
            return jsonify({"error": "COBALT_AUTH_REQUIRED"}), 403
        if "연결 실패" in err or "connection" in low:
            return jsonify({"error": "COBALT_UNREACHABLE"}), 502
        return jsonify({"error": err}), 502

    # cobalt이 준 URL에서 파일을 스트리밍해 클라이언트로 전달
    try:
        upstream = urllib.request.urlopen(
            urllib.request.Request(file_url, headers={"User-Agent": "music-downloader/1.0"}),
            timeout=180,
        )
    except Exception as ex:
        return jsonify({"error": f"파일 다운로드 실패: {ex}"}), 502

    def stream():
        try:
            while True:
                chunk = upstream.read(64 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            upstream.close()

    safe = "".join(c for c in filename if c not in r'\/:*?"<>|').strip() or f"{video_id}.mp3"
    # 한글 파일명을 위해 RFC 5987 인코딩 병행
    encoded   = urllib.parse.quote(safe)
    disposition = f"attachment; filename=\"{video_id}.mp3\"; filename*=UTF-8''{encoded}"

    return Response(
        stream(),
        mimetype="audio/mpeg",
        headers={
            "Content-Disposition": disposition,
            "Cache-Control":       "no-store",
        },
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
