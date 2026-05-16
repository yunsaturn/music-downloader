(() => {
  /* ── DOM refs ──────────────────────────────────── */
  const searchInput   = document.getElementById("search-input");
  const clearBtn      = document.getElementById("clear-btn");
  const emptyState    = document.getElementById("empty-state");
  const loadingEl     = document.getElementById("loading");
  const videoList     = document.getElementById("video-list");
  const player        = document.getElementById("player");
  const audio         = document.getElementById("audio");
  const playerThumb   = document.getElementById("player-thumb");
  const playerTitle   = document.getElementById("player-title");
  const playerTime    = document.getElementById("player-time");
  const progressFill  = document.getElementById("progress-fill");
  const progressBar   = document.getElementById("progress-bar");
  const playPauseBtn  = document.getElementById("play-pause-btn");
  const prevBtn       = document.getElementById("prev-btn");
  const nextBtn       = document.getElementById("next-btn");

  let results      = [];
  let currentIndex = -1;
  let searchTimer  = null;

  /* ── Search ────────────────────────────────────── */
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

  /* ── Render ────────────────────────────────────── */
  function renderList(videos) {
    loadingEl.hidden = true;
    emptyState.hidden = true;
    videoList.innerHTML = "";

    if (!videos.length) {
      showEmptyMsg("검색 결과가 없습니다", "다른 검색어로 시도해 보세요");
      return;
    }

    videos.forEach((v, i) => {
      const li = document.createElement("li");
      li.className = "video-item";
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
            <svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
          </button>
          <button class="icon-btn dl-btn" data-index="${i}" aria-label="다운로드">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M12 4v12m0 0-4-4m4 4 4-4"/><path d="M4 20h16"/>
            </svg>
          </button>
        </div>
      `;
      videoList.appendChild(li);
    });

    videoList.querySelectorAll(".play-btn").forEach(btn =>
      btn.addEventListener("click", () => playTrack(+btn.dataset.index))
    );
    videoList.querySelectorAll(".dl-btn").forEach(btn =>
      btn.addEventListener("click", () => downloadTrack(+btn.dataset.index))
    );
  }

  /* ── Playback ──────────────────────────────────── */
  async function playTrack(index) {
    if (index < 0 || index >= results.length) return;
    const v = results[index];

    setPlayingStyle(currentIndex, false);
    currentIndex = index;
    setPlayingStyle(currentIndex, true);

    playerThumb.src = v.thumbnail;
    playerTitle.textContent = v.title;
    playerTime.textContent = "불러오는 중…";
    player.hidden = false;
    setPlayerIcon(false); // show pause (playing state)

    try {
      const res  = await fetch(`/api/stream/${encodeURIComponent(v.video_id)}`);
      const data = await res.json();
      if (data.error) throw new Error(data.error);
      audio.src = data.url;
      await audio.play();
    } catch (e) {
      alert("재생 오류: " + e.message);
      setPlayingStyle(currentIndex, false);
      setPlayerIcon(true); // show play
    }
  }

  function setPlayingStyle(index, active) {
    if (index < 0) return;
    const btn  = videoList.querySelector(`.play-btn[data-index="${index}"]`);
    const item = videoList.querySelector(`.video-item[data-index="${index}"]`);
    if (btn) {
      btn.classList.toggle("playing-indicator", active);
      btn.innerHTML = active
        ? `<svg viewBox="0 0 24 24" fill="currentColor"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg>`
        : `<svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>`;
    }
    if (item) item.classList.toggle("playing", active);
  }

  /* ── Audio events ──────────────────────────────── */
  audio.addEventListener("timeupdate", () => {
    if (!audio.duration) return;
    const pct = (audio.currentTime / audio.duration) * 100;
    progressFill.style.width = pct + "%";
    playerTime.textContent = `${fmt(audio.currentTime)} / ${fmt(audio.duration)}`;
  });

  audio.addEventListener("ended", () => {
    setPlayingStyle(currentIndex, false);
    setPlayerIcon(true);
    if (currentIndex < results.length - 1) playTrack(currentIndex + 1);
  });

  audio.addEventListener("pause", () => {
    setPlayerIcon(true);
    syncListIcon(currentIndex, false);
  });
  audio.addEventListener("play", () => {
    setPlayerIcon(false);
    syncListIcon(currentIndex, true);
  });

  /* 목록 버튼 아이콘을 재생/일시정지 상태에 맞춰 동기화 */
  function syncListIcon(index, playing) {
    const btn = videoList.querySelector(`.play-btn[data-index="${index}"]`);
    if (!btn) return;
    btn.innerHTML = playing
      ? `<svg viewBox="0 0 24 24" fill="currentColor"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg>`
      : `<svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>`;
  }

  /* innerHTML 교체 방식 — CSS specificity 충돌 없음 */
  const SVG_PLAY  = `<svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>`;
  const SVG_PAUSE = `<svg viewBox="0 0 24 24" fill="currentColor"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg>`;

  function setPlayerIcon(showPlay) {
    playPauseBtn.innerHTML = showPlay ? SVG_PLAY : SVG_PAUSE;
  }

  /* Progress bar seek — .player-progress-wrap 클릭 → .player-progress-track 기준 */
  progressBar.addEventListener("click", e => {
    if (!audio.duration) return;
    const track = progressBar.querySelector(".player-progress-track");
    const rect  = track.getBoundingClientRect();
    const pct   = Math.min(Math.max((e.clientX - rect.left) / rect.width, 0), 1);
    audio.currentTime = pct * audio.duration;
  });

  playPauseBtn.addEventListener("click", () => {
    if (audio.paused) audio.play();
    else audio.pause();
  });

  prevBtn.addEventListener("click", () => {
    if (currentIndex > 0) playTrack(currentIndex - 1);
  });
  nextBtn.addEventListener("click", () => {
    if (currentIndex < results.length - 1) playTrack(currentIndex + 1);
  });

  /* ── Download ──────────────────────────────────── */
  function downloadTrack(index) {
    const v   = results[index];
    const btn = videoList.querySelector(`.dl-btn[data-index="${index}"]`);
    if (!btn) return;

    // spinner icon
    btn.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9" stroke-dasharray="56" stroke-dashoffset="20" style="animation:spin .9s linear infinite;transform-origin:center"/></svg>`;
    btn.classList.add("loading-btn");

    const a = document.createElement("a");
    a.href = `/api/download/${encodeURIComponent(v.video_id)}`;
    a.download = v.title + ".mp3";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);

    setTimeout(() => {
      btn.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 4v12m0 0-4-4m4 4 4-4"/><path d="M4 20h16"/></svg>`;
      btn.classList.remove("loading-btn");
    }, 4000);
  }

  /* ── Helpers ───────────────────────────────────── */
  function showEmpty() {
    loadingEl.hidden = true;
    videoList.innerHTML = "";
    emptyState.hidden = false;
    emptyState.querySelector(".empty-title").textContent = "음악을 검색해보세요";
    emptyState.querySelector(".empty-sub").textContent   = "YouTube에서 원하는 곡을 찾아 재생하거나 MP3로 저장하세요";
  }

  function showEmptyMsg(title, sub = "") {
    loadingEl.hidden = true;
    videoList.innerHTML = "";
    emptyState.hidden = false;
    emptyState.querySelector(".empty-title").textContent = title;
    emptyState.querySelector(".empty-sub").textContent   = sub;
  }

  function showLoading() {
    emptyState.hidden = true;
    videoList.innerHTML = "";
    loadingEl.hidden = false;
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
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }
})();
