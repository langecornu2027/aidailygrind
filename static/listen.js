// "Listen" player: reads the page aloud with the browser's own voice (Web Speech API).
// Free, nothing is sent to a server. Reads every element marked with data-speak, in order.
(function () {
  var player = document.querySelector(".listen");
  if (!player) return;
  if (!("speechSynthesis" in window) || !window.SpeechSynthesisUtterance) {
    player.hidden = true;
    return;
  }
  player.hidden = false;

  var synth = window.speechSynthesis;
  var playBtn = player.querySelector(".listen-play");
  var stopBtn = player.querySelector(".listen-stop");
  var speedBtn = player.querySelector(".listen-speed");
  var status = player.querySelector(".listen-status");
  var bar = player.querySelector(".listen-bar i");

  var SPEEDS = [1, 1.2, 1.5, 0.85];
  var speed = 1;
  var chunks = [];   // { text, el }
  var index = 0;
  var playing = false;
  var voice = null;
  var gen = 0;       // bumps on every stop, so old sentences are ignored

  // Pick the most natural English voice the device has
  function pickVoice() {
    var voices = synth.getVoices().filter(function (v) { return /^en(-|_|$)/i.test(v.lang); });
    var prefer = [/natural/i, /premium|enhanced/i, /google (us|uk) english/i, /samantha|ava|allison|serena|daniel/i, /microsoft (aria|jenny|guy)/i];
    for (var i = 0; i < prefer.length; i++) {
      var found = voices.find(function (v) { return prefer[i].test(v.name); });
      if (found) return found;
    }
    return voices.find(function (v) { return v.default; }) || voices[0] || null;
  }
  voice = pickVoice();
  if (synth.onvoiceschanged !== undefined) {
    synth.onvoiceschanged = function () { voice = voice || pickVoice(); };
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

  function mark(el) {
    document.querySelectorAll(".speaking").forEach(function (n) { n.classList.remove("speaking"); });
    if (el) el.classList.add("speaking");
  }

  function update() {
    playBtn.textContent = playing ? "❚❚ Pause" : (index > 0 ? "▶ Resume" : "▶ Listen");
    playBtn.setAttribute("aria-pressed", playing ? "true" : "false");
    stopBtn.hidden = !playing && index === 0;
    var pct = chunks.length ? Math.round((index / chunks.length) * 100) : 0;
    bar.style.width = pct + "%";
    if (!playing && index === 0) status.textContent = status.dataset.idle;
    else status.textContent = playing ? "Reading… " + pct + "%" : "Paused at " + pct + "%";
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
      update();
      speakNext();
    };
    u.onerror = function (e) {
      if (mine !== gen || e.error === "interrupted" || e.error === "canceled") return;
      index += 1;
      speakNext();
    };
    mark(chunk.el);
    synth.speak(u);
  }

  function play() {
    if (!chunks.length) chunks = buildChunks();
    if (index >= chunks.length) index = 0;
    playing = true;
    gen += 1;
    synth.cancel();
    update();
    speakNext();
  }

  function pause() {   // our own pause: more reliable than synth.pause() on phones
    playing = false;
    gen += 1;
    synth.cancel();
    update();
  }

  function finish() {
    playing = false;
    index = 0;
    mark(null);
    update();
    status.textContent = "Done. Bon café! ☕";
  }

  playBtn.addEventListener("click", function () { playing ? pause() : play(); });
  stopBtn.addEventListener("click", function () { playing = false; gen += 1; synth.cancel(); index = 0; mark(null); update(); });
  speedBtn.addEventListener("click", function () {
    speed = SPEEDS[(SPEEDS.indexOf(speed) + 1) % SPEEDS.length];
    speedBtn.textContent = speed + "×";
    if (playing) { gen += 1; synth.cancel(); speakNext(); }
  });

  window.addEventListener("pagehide", function () { synth.cancel(); });
  update();
})();
