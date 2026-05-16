/* ================================================================
   뮤직 다운 — YouTube IFrame API 기반 재생
   재생: 브라우저가 직접 YouTube에 접속 (서버 IP 무관)
   다운: 서버 경유 MP3 변환
================================================================ */

/* ── DOM ─────────────────────────────────────────── */
const searchInput  = document.getElementById("search-input");
const clearBtn     = document.getElementById("clear-btn");
const emptyState   = document.getElementById("empty-state");
const loadingEl    = document.getElementById("loading");
const videoList    = document.getElementById("video-list");
const player       = document.getElementById("player");
const playerThumb  = document.getElementById("player-thumb");
const playerTitle  = document.getElementById("player-title");
const playerTime   = document.getElementById("player-time");
const progressFill = document.getElementById("progress-fill");
const progressBar  = document.getElementById("progress-bar");
const playPauseBtn = document.getElementById("play-pause-btn");
const prevBtn      = document.getElementById("prev-btn");
const nextBtn      = document.getElementById("next-btn");

const SVG_PLAY  = `<svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>`;
const SVG_PAUSE = `<svg viewBox="0 0 24 24" fill="currentColor"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg>`;

/* ── 상태 ────────────────────────────────────────── */
let results      = [];
let currentIndex = -1;
let ytPlayer     = null;   // YouTube IFrame Player 인스턴스
let ytReady      = false;  // API 로드 완료 여부
let pendingId    = null;   // API 로드 전 재생 요청된 video_id
let progressTimer = null;

/* ── YouTube IFrame API 콜백 ─────────────────────── */
window.onYouTubeIframeAPIReady = function () {
  ytPlayer = new YT.Player("yt-player", {
    width: "1", height: "1",
    playerVars: { playsinline: 1, controls: 0, disablekb: 1 },
    events: {
      onReady: () => {
        ytReady = true;
        if (pendingId !== null) {
          ytPlayer.loadVideoById(pendingId);
          pendingId = null;
        }
      },
      onStateChange: onYTStateChange,
    },
  });
};

function onYTStateChange(e) {
  const S = YT.PlayerState;
  if (e.data === S.PLAYING) {
    setPlayerIcon(false);          // ⏸
    syncListIcon(currentIndex, true);
    startProgressTimer();
  } else if (e.data === S.PAUSED) {
    setPlayerIcon(true);           // ▶
    syncListIcon(currentIndex, false);
  } else if (e.data === S.ENDED) {
    syncListIcon(currentIndex, false);
    stopProgressTimer();
    playNextTrack();
  } else if (e.data === S.BUFFERING) {
    // 버퍼링 중 — 아이콘 유지
  }
}

/* ── 진행바 타이머 ───────────────────────────────── */
function startProgressTimer() {
  stopProgressTimer();
  progressTimer = setInterval(updateProgress, 500);
}
function stopProgressTimer() {
  if (progressTimer) { clearInterval(progressTimer); progressTimer = null; }
}
function updateProgress() {
  if (!ytPlayer || typeof ytPlayer.getCurrentTime !== "function") return;
  const cur = ytPlayer.getCurrentTime() || 0;
  const dur = ytPlayer.getDuration()    || 0;
  if (dur > 0) {
    progressFill.style.width = (cur / dur * 100) + "%";
    playerTime.textContent   = `${fmt(cur)} / ${fmt(dur)}`;
  }
}

/* ── 검색 ────────────────────────────────────────── */
let searchTimer = null;

searchInput.addEventListener("input", () => {
  const val = searchInput.value.trim();
  clearBtn.classList.toggle("visible", val.length > 0);
  clearTimeout(searchTimer);
  if (!val) { showEmpty(); return; }
  searchTimer = setTimeout(() => doSearch(val), 500);
});

searchInput.addEventListener("keydown", e => {
  if (e.key === "Enter") {
    clearTimeout(searchTimer);
    const val = searchInput.value.trim();
    if (val) doSearch(val);
  }
});

clearBtn.addEventListener("click", () => {
  searchInput.value = "";
  clearBtn.classList.remove("visible");
  showEmpty();
  searchInput.focus();
});

async function doSearch(q) {
  showLoading();
  try {
    const res  = await fetch(`/api/search?q=${encodeURIComponent(q)}`);
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    results = data;
    renderList(results);
  } catch (e) {
    showEmptyMsg("검색 중 오류가 발생했습니다 😢", e.message);
  }
}

/* ── 렌더링 ──────────────────────────────────────── */
function renderList(videos) {
  loadingEl.hidden  = true;
  emptyState.hidden = true;
  videoList.innerHTML = "";

  if (!videos.length) {
    showEmptyMsg("검색 결과가 없습니다", "다른 검색어로 시도해 보세요");
    return;
  }

  videos.forEach((v, i) => {
    const li = document.createElement("li");
    li.className    = "video-item";
    li.dataset.index = i;
    li.innerHTML = `
      <div class="thumb-wrap">
        <img src="${esc(v.thumbnail)}" alt="" loading="lazy" />
      </div>
      <div class="video-info">
        <div class="video-title">${esc(v.title)}</div>
        <div class="video-duration">${esc(v.duration)}</div>
      </div>
      <div class="video-actions">
        <button class="icon-btn play-btn" data-index="${i}" aria-label="재생">
          ${SVG_PLAY}
        </button>
        <button class="icon-btn dl-btn" data-index="${i}" aria-label="다운로드">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
               stroke-linecap="round" stroke-linejoin="round">
            <path d="M12 4v12m0 0-4-4m4 4 4-4"/><path d="M4 20h16"/>
          </svg>
        </button>
      </div>`;
    videoList.appendChild(li);
  });

  videoList.querySelectorAll(".play-btn").forEach(btn =>
    btn.addEventListener("click", () => playTrack(+btn.dataset.index))
  );
  videoList.querySelectorAll(".dl-btn").forEach(btn =>
    btn.addEventListener("click", () => downloadTrack(+btn.dataset.index))
  );
}

/* ── 재생 ────────────────────────────────────────── */
function playTrack(index) {
  if (index < 0 || index >= results.length) return;
  const v = results[index];

  setPlayingStyle(currentIndex, false);
  currentIndex = index;
  setPlayingStyle(currentIndex, true);

  // 플레이어 UI 업데이트
  playerThumb.src           = v.thumbnail;
  playerTitle.textContent   = v.title;
  playerTime.textContent    = "불러오는 중…";
  progressFill.style.width  = "0%";
  player.hidden             = false;
  setPlayerIcon(false);

  // YouTube IFrame으로 재생
  if (ytReady && ytPlayer) {
    ytPlayer.loadVideoById(v.video_id);
  } else {
    pendingId = v.video_id;   // API 준비되면 자동 재생
  }
}

function playNextTrack() {
  if (currentIndex < results.length - 1) playTrack(currentIndex + 1);
}

/* ── 컨트롤 ──────────────────────────────────────── */
playPauseBtn.addEventListener("click", () => {
  if (!ytPlayer) return;
  const state = ytPlayer.getPlayerState();
  if (state === YT.PlayerState.PLAYING) ytPlayer.pauseVideo();
  else ytPlayer.playVideo();
});

prevBtn.addEventListener("click", () => {
  if (currentIndex > 0) playTrack(currentIndex - 1);
});
nextBtn.addEventListener("click", playNextTrack);

/* 프로그레스바 클릭 → 탐색 */
progressBar.addEventListener("click", e => {
  if (!ytPlayer || typeof ytPlayer.getDuration !== "function") return;
  const track = progressBar.querySelector(".player-progress-track");
  const rect  = track.getBoundingClientRect();
  const pct   = Math.min(Math.max((e.clientX - rect.left) / rect.width, 0), 1);
  ytPlayer.seekTo(pct * ytPlayer.getDuration(), true);
});

/* ── 다운로드 ─────────────────────────────────────── */
const DL_SVG = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
  stroke-linecap="round" stroke-linejoin="round">
  <path d="M12 4v12m0 0-4-4m4 4 4-4"/><path d="M4 20h16"/></svg>`;

const SPIN_SVG = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
  <circle cx="12" cy="12" r="9" stroke-dasharray="56" stroke-dashoffset="20"
    style="animation:spin .9s linear infinite;transform-origin:center"/></svg>`;

async function downloadTrack(index) {
  const v   = results[index];
  const btn = videoList.querySelector(`.dl-btn[data-index="${index}"]`);
  if (!btn) return;

  btn.innerHTML = SPIN_SVG;
  btn.classList.add("loading-btn");

  try {
    const res = await fetch(`/api/download/${encodeURIComponent(v.video_id)}`);

    if (res.ok) {
      // 성공 → blob으로 받아서 저장
      const blob = await res.blob();
      const url  = URL.createObjectURL(blob);
      const a    = document.createElement("a");
      a.href     = url;
      a.download = v.title + ".mp3";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } else {
      const data = await res.json().catch(() => ({}));
      if (res.status === 403 || data.error === "COOKIE_REQUIRED") {
        showToast("⚠️ 다운로드는 서버 쿠키 설정이 필요합니다.\nRailway Variables에 COOKIES_CONTENT를 추가해주세요.");
      } else {
        showToast("다운로드 실패: " + (data.error || res.status));
      }
    }
  } catch (e) {
    showToast("네트워크 오류: " + e.message);
  } finally {
    btn.innerHTML = DL_SVG;
    btn.classList.remove("loading-btn");
  }
}

/* ── UI 헬퍼 ─────────────────────────────────────── */
function setPlayerIcon(showPlay) {
  playPauseBtn.innerHTML = showPlay ? SVG_PLAY : SVG_PAUSE;
}

function setPlayingStyle(index, active) {
  if (index < 0) return;
  const btn  = videoList.querySelector(`.play-btn[data-index="${index}"]`);
  const item = videoList.querySelector(`.video-item[data-index="${index}"]`);
  if (btn)  { btn.classList.toggle("playing-indicator", active);
               btn.innerHTML = active ? SVG_PAUSE : SVG_PLAY; }
  if (item) item.classList.toggle("playing", active);
}

function syncListIcon(index, playing) {
  const btn = videoList.querySelector(`.play-btn[data-index="${index}"]`);
  if (btn) btn.innerHTML = playing ? SVG_PAUSE : SVG_PLAY;
}

function showEmpty() {
  loadingEl.hidden  = true;
  videoList.innerHTML = "";
  emptyState.hidden = false;
  emptyState.querySelector(".empty-title").textContent = "음악을 검색해보세요";
  emptyState.querySelector(".empty-sub").textContent   = "YouTube에서 원하는 곡을 찾아 재생하거나 MP3로 저장하세요";
}
function showEmptyMsg(title, sub = "") {
  loadingEl.hidden  = true;
  videoList.innerHTML = "";
  emptyState.hidden = false;
  emptyState.querySelector(".empty-title").textContent = title;
  emptyState.querySelector(".empty-sub").textContent   = sub;
}
function showLoading() {
  emptyState.hidden   = true;
  videoList.innerHTML = "";
  loadingEl.hidden    = false;
}

/* ── 토스트 알림 ─────────────────────────────────── */
function showToast(msg) {
  let t = document.getElementById("toast");
  if (!t) {
    t = document.createElement("div");
    t.id = "toast";
    document.body.appendChild(t);
  }
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(t._timer);
  t._timer = setTimeout(() => t.classList.remove("show"), 4000);
}

function fmt(sec) {
  sec = Math.floor(sec || 0);
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  return h > 0
    ? `${h}:${String(m).padStart(2,"0")}:${String(s).padStart(2,"0")}`
    : `${m}:${String(s).padStart(2,"0")}`;
}

function esc(str) {
  return String(str)
    .replace(/&/g,"&amp;").replace(/</g,"&lt;")
    .replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}
