// "Listen" player.
// 1. AI voice: asks the server for MP3 parts (/api/audio). The server makes each part the
//    first time anyone asks, then everyone gets the saved file. Part 0 can play while the
//    next parts are still being made.
// 2. Backup: the browser's own voice (Web Speech API), if the AI voice is not available.
(function () {
  var player = document.querySelector(".listen");
  if (!player) return;

  var hasSpeech = "speechSynthesis" in window && !!window.SpeechSynthesisUtterance;
  var aiDate = player.dataset.audioDate;
  var aiOnly = player.dataset.audioPart; // token pages: just that part
  var mode = aiDate ? "ai" : "browser";
  if (mode === "browser" && !hasSpeech) { player.hidden = true; return; }
  player.hidden = false;

  var playBtn = player.querySelector(".listen-play");
  var stopBtn = player.querySelector(".listen-stop");
  var speedBtn = player.querySelector(".listen-speed");
  var status = player.querySelector(".listen-status");
  var bar = player.querySelector(".listen-bar i");

  var SPEEDS = [1, 1.2, 1.5, 0.85];
  var speed = 1;
  var playing = false;
  var started = false;

  function mark(els) {
    document.querySelectorAll(".speaking").forEach(function (n) { n.classList.remove("speaking"); });
    (els || []).forEach(function (el) { el.classList.add("speaking"); });
  }

  function setProgress(fraction, text) {
    var pct = Math.max(0, Math.min(100, Math.round(fraction * 100)));
    bar.style.width = pct + "%";
    if (text) status.textContent = text;
    else if (playing) status.textContent = (mode === "ai" ? "AI voice · " : "") + pct + "%";
    else if (started) status.textContent = "Paused at " + pct + "%";
    else status.textContent = status.dataset.idle;
  }

  function updateButtons() {
    playBtn.textContent = playing ? "❚❚ Pause" : (started ? "▶ Resume" : "▶ Listen");
    playBtn.setAttribute("aria-pressed", playing ? "true" : "false");
    stopBtn.hidden = !started;
  }

  function finish() {
    playing = false;
    started = false;
    mark(null);
    updateButtons();
    setProgress(0, "Done. Bon café! ☕");
  }

  /* ---------- AI voice ---------- */

  var audio = new Audio();
  audio.preload = "auto";
  var manifest = null;
  var cur = 0;
  var polls = 0;
  var pollTimer = null;
  var SILENT = "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA=";

  function api(method) {
    var url = "/api/audio?date=" + encodeURIComponent(aiDate) + (aiOnly ? "&part=" + aiOnly : "");
    return fetch(url, { method: method }).then(function (r) {
      if (!r.ok) throw new Error("audio " + r.status);
      return r.json();
    });
  }

  function partEls(p) { return Array.prototype.slice.call(document.querySelectorAll('[data-part="' + p.n + '"]')); }

  function aiProgress() {
    if (!manifest) return 0;
    var inPart = audio.duration ? audio.currentTime / audio.duration : 0;
    return (cur + inPart) / manifest.parts.length;
  }

  function aiPlayCurrent() {
    if (!playing) return;
    var p = manifest.parts[cur];
    if (!p) { finish(); return; }
    if (p.status === "ready") {
      polls = 0;
      if (audio.dataset.src !== p.url) { audio.src = p.url; audio.dataset.src = p.url; }
      audio.playbackRate = speed;
      mark(partEls(p));
      audio.play().then(function () { setProgress(aiProgress()); }).catch(function () {
        playing = false; updateButtons(); setProgress(aiProgress(), "Tap ▶ to start the audio");
      });
    } else if (p.status === "failed" || polls > 60) {
      useBrowserVoice("The AI voice is not available right now. Using your browser's voice.");
    } else {
      setProgress(aiProgress(), cur === 0 ? "☕ Brewing the AI voice… a few seconds" : "☕ Brewing the next part…");
      polls += 1;
      pollTimer = setTimeout(function () {
        api("GET").then(function (m) { manifest = m; aiPlayCurrent(); })
          .catch(function () { useBrowserVoice("The AI voice is not available right now. Using your browser's voice."); });
      }, 2500);
    }
  }

  audio.addEventListener("ended", function () { cur += 1; aiPlayCurrent(); });
  audio.addEventListener("timeupdate", function () { if (playing) setProgress(aiProgress()); });
  audio.addEventListener("error", function () {
    if (audio.dataset.src && playing) useBrowserVoice("The AI voice could not play. Using your browser's voice.");
  });

  function aiPlay() {
    if (!manifest) {
      audio.src = SILENT; audio.play().catch(function () {}); // unlock audio on phones (needs the tap)
      setProgress(0, "☕ Brewing the AI voice… a few seconds");
      api("POST").then(function (m) { manifest = m; aiPlayCurrent(); })
        .catch(function () { useBrowserVoice("The AI voice is not available right now. Using your browser's voice."); });
    } else {
      aiPlayCurrent();
    }
  }

  function aiPause() { clearTimeout(pollTimer); audio.pause(); }
  function aiStop() { clearTimeout(pollTimer); audio.pause(); if (audio.dataset.src) audio.currentTime = 0; cur = 0; }

  /* ---------- browser voice (backup) ---------- */

  var synth = hasSpeech ? window.speechSynthesis : null;
  var chunks = [];   // { text, el }
  var index = 0;
  var voice = null;
  var gen = 0;       // bumps on every stop, so old sentences are ignored

  function pickVoice() {
    var voices = synth.getVoices().filter(function (v) { return /^en(-|_|$)/i.test(v.lang); });
    var prefer = [/natural/i, /premium|enhanced/i, /google (us|uk) english/i, /samantha|ava|allison|serena|daniel/i, /microsoft (aria|jenny|guy)/i];
    for (var i = 0; i < prefer.length; i++) {
      var found = voices.find(function (v) { return prefer[i].test(v.name); });
      if (found) return found;
    }
    return voices.find(function (v) { return v.default; }) || voices[0] || null;
  }
  if (synth) {
    voice = pickVoice();
    if (synth.onvoiceschanged !== undefined) synth.onvoiceschanged = function () { voice = voice || pickVoice(); };
  }

  // Split the page into short sentences (long text gets cut off in some browsers)
  function buildChunks() {
    var list = [];
    document.querySelectorAll("[data-speak]").forEach(function (el) {
      var text = (el.getAttribute("data-speak-prefix") || "") + " " + el.innerText;
      text = text.replace(/\s+/g, " ").replace(/↗/g, "").trim();
      var sentences = text.match(/[^.!?…]+[.!?…]+["')\]]*|[^.!?…]+$/g) || [text];
      sentences.forEach(function (s) {
        s = s.trim();
        if (s) list.push({ text: s, el: el });
      });
    });
    return list;
  }

  function speakNext() {
    if (!playing) return;
    if (index >= chunks.length) { finish(); return; }
    var chunk = chunks[index];
    var mine = gen;
    var u = new SpeechSynthesisUtterance(chunk.text);
    if (voice) u.voice = voice;
    u.lang = (voice && voice.lang) || "en-US";
    u.rate = speed;
    u.onend = function () {
      if (!playing || mine !== gen) return;
      index += 1;
      setProgress(index / chunks.length);
      speakNext();
    };
    u.onerror = function (e) {
      if (mine !== gen || e.error === "interrupted" || e.error === "canceled") return;
      index += 1;
      speakNext();
    };
    mark([chunk.el]);
    synth.speak(u);
  }

  function browserPlay() {
    if (!chunks.length) chunks = buildChunks();
    if (index >= chunks.length) index = 0;
    gen += 1;
    synth.cancel();
    setProgress(index / chunks.length);
    speakNext();
  }
  function browserPause() { gen += 1; synth.cancel(); }
  function browserStop() { gen += 1; synth.cancel(); index = 0; }

  function useBrowserVoice(message) {
    aiStop();
    mode = "browser";
    if (!hasSpeech) { playing = false; started = false; updateButtons(); setProgress(0, "Audio is not available on this browser."); return; }
    status.textContent = message;
    playing = true;
    started = true;
    updateButtons();
    setTimeout(browserPlay, 1200);
  }

  /* ---------- buttons ---------- */

  playBtn.addEventListener("click", function () {
    if (playing) {
      playing = false;
      mode === "ai" ? aiPause() : browserPause();
      updateButtons();
      setProgress(mode === "ai" ? aiProgress() : index / (chunks.length || 1));
      return;
    }
    playing = true;
    started = true;
    updateButtons();
    mode === "ai" ? aiPlay() : browserPlay();
  });

  stopBtn.addEventListener("click", function () {
    playing = false;
    started = false;
    mode === "ai" ? aiStop() : browserStop();
    mark(null);
    updateButtons();
    setProgress(0);
  });

  speedBtn.addEventListener("click", function () {
    speed = SPEEDS[(SPEEDS.indexOf(speed) + 1) % SPEEDS.length];
    speedBtn.textContent = speed + "×";
    if (mode === "ai") audio.playbackRate = speed;
    else if (playing) { gen += 1; synth.cancel(); speakNext(); }
  });

  window.addEventListener("pagehide", function () { if (synth) synth.cancel(); audio.pause(); });
  updateButtons();
  setProgress(0);
})();
