// Townie backup web app: hold-to-talk, GPS, compass heading, demo locations.
const $ = (id) => document.getElementById(id);
const state = { lat: null, lon: null, heading: null, recorder: null, chunks: [], busy: false };

// ---------- location ----------
async function loadSpots() {
  try {
    const cfg = await (await fetch("/api/config")).json();
    for (const s of cfg.demo_spots) {
      const o = document.createElement("option");
      o.value = s.id;
      o.textContent = `Demo: ${s.name}`;
      $("loc").appendChild(o);
    }
    const saved = localStorageGet("townie-loc");
    if (saved && [...$("loc").options].some((o) => o.value === saved)) $("loc").value = saved;
  } catch (e) { console.warn(e); }
  onLocChange();
}

function localStorageGet(k) { try { return localStorage.getItem(k); } catch { return null; } }
function localStorageSet(k, v) { try { localStorage.setItem(k, v); } catch {} }

let watchId = null;
function onLocChange() {
  localStorageSet("townie-loc", $("loc").value);
  if ($("loc").value !== "gps") {
    $("gpsChip").textContent = "Using demo spot";
    $("gpsChip").classList.add("on");
    return;
  }
  if (!navigator.geolocation) { $("gpsChip").textContent = "GPS: unavailable"; return; }
  $("gpsChip").textContent = "GPS: finding you…";
  if (watchId === null) {
    watchId = navigator.geolocation.watchPosition(
      (p) => {
        state.lat = p.coords.latitude; state.lon = p.coords.longitude;
        if ($("loc").value === "gps") {
          $("gpsChip").textContent = `GPS: ±${Math.round(p.coords.accuracy)} m`;
          $("gpsChip").classList.add("on");
        }
      },
      () => { $("gpsChip").textContent = "GPS: blocked, pick a demo spot"; $("gpsChip").classList.remove("on"); },
      { enableHighAccuracy: true, maximumAge: 5000 }
    );
  }
}
$("loc").addEventListener("change", onLocChange);

// ---------- compass ----------
function onOrientation(e) {
  let h = null;
  if (typeof e.webkitCompassHeading === "number") h = e.webkitCompassHeading;
  else if (e.absolute && typeof e.alpha === "number") h = (360 - e.alpha) % 360;
  if (h !== null) {
    state.heading = Math.round(h);
    $("compassChip").textContent = `Compass: ${state.heading}°`;
    $("compassChip").classList.add("on");
  }
}
$("compassBtn").addEventListener("click", async () => {
  try {
    if (typeof DeviceOrientationEvent !== "undefined" && typeof DeviceOrientationEvent.requestPermission === "function") {
      const res = await DeviceOrientationEvent.requestPermission();
      if (res !== "granted") throw new Error("denied");
    }
    window.addEventListener("deviceorientationabsolute", onOrientation);
    window.addEventListener("deviceorientation", onOrientation);
    $("compassBtn").hidden = true;
    $("compassChip").textContent = "Compass: waiting…";
  } catch {
    $("compassChip").textContent = "Compass: not allowed";
  }
});

// ---------- asking ----------
function where() {
  const loc = $("loc").value;
  const out = {};
  if (loc !== "gps") out.demo = loc;
  else if (state.lat !== null) { out.lat = state.lat; out.lon = state.lon; }
  if (state.heading !== null) out.heading = state.heading;
  return out;
}

function setBusy(on, text) {
  state.busy = on;
  $("talk").classList.toggle("busy", on);
  $("talk").textContent = on ? "Thinking…" : "Hold to ask";
  if (text) $("hint").textContent = text;
}

function show(data) {
  $("empty").hidden = true;
  $("q").hidden = $("say").hidden = $("meta").hidden = false;
  $("q").textContent = data.question ? `“${data.question}”` : "";
  $("say").textContent = data.say;
  $("meta").textContent = `${data.intent?.intent || "answer"} · ${data.seconds}s`;
  if (data.audio_b64) {
    $("player").src = `data:audio/mpeg;base64,${data.audio_b64}`;
    $("player").play().catch(() => {});
  }
}

async function send(body, isForm) {
  setBusy(true, "Okay, so…  (stall for a beat)");
  try {
    const res = await fetch("/api/ask?format=json", isForm
      ? { method: "POST", body }
      : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    show(await res.json());
    setBusy(false, "Say it like you always knew.");
  } catch {
    show({ say: "Give me one sec, let me check my maps.", seconds: "–" });
    setBusy(false, "Connection hiccup. Try again.");
  }
}

$("typeForm").addEventListener("submit", (e) => {
  e.preventDefault();
  const q = $("typed").value.trim();
  if (!q || state.busy) return;
  send({ question: q, want_audio: true, source: "web", ...where() }, false);
});

// Unlock audio on iOS with the first touch, so the answer can autoplay later.
let unlocked = false;
function unlockAudio() {
  if (unlocked) return;
  unlocked = true;
  const a = $("player");
  a.muted = true;
  a.src = "/static/fallback.m4a";
  a.play().then(() => { a.pause(); a.muted = false; }).catch(() => { a.muted = false; });
}

// ---------- hold to talk ----------
async function startRec(e) {
  e.preventDefault();
  unlockAudio();
  if (state.busy || state.recorder) return;
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const rec = new MediaRecorder(stream);
    state.chunks = [];
    rec.ondataavailable = (ev) => ev.data.size && state.chunks.push(ev.data);
    rec.onstop = () => {
      stream.getTracks().forEach((t) => t.stop());
      const type = rec.mimeType || "audio/webm";
      const blob = new Blob(state.chunks, { type });
      state.recorder = null;
      $("talk").classList.remove("rec");
      if (blob.size < 2000) { setBusy(false, "Too short. Hold while you talk."); return; }
      const fd = new FormData();
      fd.append("audio", blob, type.includes("mp4") ? "q.mp4" : "q.webm");
      fd.append("want_audio", "1");
      fd.append("source", "web");
      for (const [k, v] of Object.entries(where())) fd.append(k, v);
      send(fd, true);
    };
    rec.start();
    state.recorder = rec;
    $("talk").classList.add("rec");
    $("talk").textContent = "Listening…";
  } catch {
    $("hint").textContent = "Microphone blocked. Type your question instead.";
  }
}
function stopRec(e) {
  e.preventDefault();
  if (state.recorder && state.recorder.state === "recording") state.recorder.stop();
}
$("talk").addEventListener("pointerdown", startRec);
$("talk").addEventListener("pointerup", stopRec);
$("talk").addEventListener("pointerleave", stopRec);
$("talk").addEventListener("pointercancel", stopRec);
document.addEventListener("click", unlockAudio, { once: true });

loadSpots();
