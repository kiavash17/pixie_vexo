// Pixie control room: everything arrives over one WebSocket from server.py.
// Text frames = JSON band events; binary frames = 20 ms of PCM16 mono @16 kHz.
const $ = (id) => document.getElementById(id);
const RATE = 16000;

// ------------------------------------------------------------------ strip charts
class Strip {
  constructor(canvas, { series, colors, labels, window = 10, min, max, span = 0 }) {
    Object.assign(this, { canvas, series, colors, labels, window, min, max, span });
    this.data = Array.from({ length: series }, () => []);   // [ [t, v], ... ] per series
    this.ctx = canvas.getContext('2d');
  }
  add(t, values) {
    values.forEach((v, i) => { if (v !== null && v !== undefined) this.data[i].push([t, v]); });
    const cut = t - this.window;
    for (const d of this.data) while (d.length && d[0][0] < cut) d.shift();
  }
  draw(now) {
    const c = this.canvas, dpr = devicePixelRatio || 1;
    const w = c.clientWidth, h = c.clientHeight;
    if (c.width !== w * dpr) { c.width = w * dpr; c.height = h * dpr; }
    const g = this.ctx; g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, w, h);
    let lo = this.min, hi = this.max;
    if (lo === undefined || hi === undefined) {   // auto range
      const all = this.data.flat().map((p) => p[1]);
      if (!all.length) return;
      lo = Math.min(...all); hi = Math.max(...all);
      const pad = Math.max((hi - lo) * 0.15, this.span / 2);
      lo -= pad; hi += pad;
    }
    const y = (v) => h - 14 - ((v - lo) / (hi - lo || 1)) * (h - 22);
    const x = (t) => ((t - (now - this.window)) / this.window) * (w - 40) + 40;
    g.strokeStyle = '#30363d'; g.fillStyle = '#8b949e'; g.font = '10px system-ui'; g.lineWidth = 1;
    for (const v of [lo, (lo + hi) / 2, hi]) {
      g.beginPath(); g.moveTo(40, y(v)); g.lineTo(w, y(v)); g.stroke();
      g.fillText(v.toFixed(Math.abs(hi - lo) < 5 ? 2 : 0), 2, y(v) + 3);
    }
    this.data.forEach((d, i) => {
      g.strokeStyle = this.colors[i]; g.lineWidth = 1.5; g.beginPath();
      d.forEach(([t, v], k) => (k ? g.lineTo(x(t), y(v)) : g.moveTo(x(t), y(v))));
      g.stroke();
      const last = d[d.length - 1];
      if (this.labels && last) { g.fillStyle = this.colors[i]; g.fillText(`${this.labels[i]} ${last[1].toFixed(2)}`, w - 70 * (this.data.length - i), 10); }
    });
  }
}
const XYZ = ['#ff7b72', '#3fb950', '#58a6ff'];
const charts = {
  accel: new Strip($('c-accel'), { series: 3, colors: XYZ, labels: ['x', 'y', 'z'], span: 0.5 }),
  gyro: new Strip($('c-gyro'), { series: 3, colors: XYZ, labels: ['x', 'y', 'z'], span: 20 }),
  mic: new Strip($('c-mic'), { series: 2, colors: ['#d2a8ff', '#6e40c9'], labels: ['peak', 'rms'], min: -96, max: 0 }),
  temp: new Strip($('c-temp'), { series: 1, colors: ['#f0883e'], window: 180, span: 1 }),
  rssi: new Strip($('c-rssi'), { series: 1, colors: ['#58a6ff'], window: 60, span: 10 }),
};
const clock = () => performance.now() / 1000;
(function frame() { const n = clock(); Object.values(charts).forEach((c) => c.draw(n)); requestAnimationFrame(frame); })();

// ------------------------------------------------------------------ live audio + session buffer
let audioCtx = null, nextTime = 0, listening = false;
const session = [];                             // Int16Array chunks of this page session
let sessionSamples = 0, audioPackets = 0;

function onPcm(buf) {
  const pcm = new Int16Array(buf);
  session.push(pcm); sessionSamples += pcm.length; audioPackets++;
  if (!listening || !audioCtx) return;
  const ab = audioCtx.createBuffer(1, pcm.length, RATE);
  const ch = ab.getChannelData(0);
  for (let i = 0; i < pcm.length; i++) ch[i] = pcm[i] / 32768;
  const src = audioCtx.createBufferSource(); src.buffer = ab; src.connect(audioCtx.destination);
  const now = audioCtx.currentTime;
  if (nextTime < now + 0.05 || nextTime > now + 0.5) nextTime = now + 0.12;  // small jitter buffer
  src.start(nextTime); nextTime += ab.duration;
}
$('listen').onclick = () => {
  if (!audioCtx) audioCtx = new AudioContext({ sampleRate: RATE });
  audioCtx.resume();
  listening = !listening;
  $('listen').classList.toggle('on', listening);
  $('listen').textContent = listening ? '🔊 Listening' : '🔈 Listen live';
};

function wav(chunks, n) {
  const out = new DataView(new ArrayBuffer(44 + n * 2));
  const str = (o, s) => [...s].forEach((c, i) => out.setUint8(o + i, c.charCodeAt(0)));
  str(0, 'RIFF'); out.setUint32(4, 36 + n * 2, true); str(8, 'WAVEfmt ');
  out.setUint32(16, 16, true); out.setUint16(20, 1, true); out.setUint16(22, 1, true);
  out.setUint32(24, RATE, true); out.setUint32(28, RATE * 2, true); out.setUint16(32, 2, true); out.setUint16(34, 16, true);
  str(36, 'data'); out.setUint32(40, n * 2, true);
  let o = 44; for (const c of chunks) for (const s of c) { out.setInt16(o, s, true); o += 2; }
  return new Blob([out], { type: 'audio/wav' });
}
let sessionUrl = null;
$('play-session').onclick = () => {
  if (!sessionSamples) return;
  if (sessionUrl) URL.revokeObjectURL(sessionUrl);
  sessionUrl = URL.createObjectURL(wav(session, sessionSamples));
  $('dl-session').href = sessionUrl;
  $('player').src = sessionUrl; $('player').play();
};
$('dl-session').onclick = () => { if (!sessionUrl) $('play-session').onclick(); };

// ------------------------------------------------------------------ UI helpers
const hhmmss = (t) => new Date((t || Date.now() / 1000) * 1000).toLocaleTimeString();
function logEvent(text, t) {
  const li = document.createElement('li');
  const tm = document.createElement('time'); tm.textContent = hhmmss(t);
  li.append(tm, document.createTextNode(text));
  $('events').prepend(li);
  while ($('events').children.length > 200) $('events').lastChild.remove();
}
let motionCount = 0, motionT0 = clock(), stepsAtStart = null;
setInterval(() => {
  const dt = clock() - motionT0;
  $('t-rate').textContent = `${(motionCount / dt).toFixed(0)} Hz`;
  $('t-audio').textContent = `${(audioPackets / dt).toFixed(0)} pkt/s`;
  $('session-len').textContent = `${(sessionSamples / RATE).toFixed(1)} s`;
  motionCount = 0; audioPackets = 0; motionT0 = clock();
}, 1000);

// ------------------------------------------------------------------ messages
const handlers = {
  status(m) {
    $('status').textContent = m.state; $('status').className = `pill ${m.state}`;
    if (m.message) $('message').textContent = m.message;
    $('t-band').textContent = m.band;
    $('connect').disabled = ['connecting', 'connected', 'reconnecting'].includes(m.state);
    $('mic').disabled = m.state !== 'connected';
    $('mic').textContent = m.mic ? '🎙 Mic on' : 'Mic off';
    $('mic').classList.toggle('on', m.mic);
    $('mic').dataset.on = m.mic ? '1' : '';
    $('engine').textContent = m.transcript ? `· ${m.transcript}` : (m.mic ? '· recording only (no transcript)' : '');
  },
  motion(m) {
    motionCount++;
    const t = clock();
    charts.accel.add(t, [m.ax, m.ay, m.az]);
    charts.gyro.add(t, [m.gx, m.gy, m.gz]);
  },
  'mic-level'(m) { charts.mic.add(clock(), [-m.peak_db, -m.rms_db]); },
  temperature(m) { charts.temp.add(clock(), [m.celsius]); $('t-temp').textContent = `${m.celsius.toFixed(1)} °C`; },
  link(m) {
    if (m.rssi === null) return;
    charts.rssi.add(clock(), [m.rssi]); $('t-rssi').textContent = `${m.rssi} dBm`;
  },
  battery(m) { $('t-battery').textContent = `${m.percent}%${m.charging ? ' ⚡' : ''}`; },
  activity(m) {
    if (stepsAtStart === null) stepsAtStart = m.steps;
    $('t-steps').textContent = `${m.steps - stepsAtStart} (${m.steps})`;
    $('t-state').textContent = `${m.state} · ${m.cadence}/min`;
  },
  event(m) { logEvent(`${m.kind}${m.face ? ' ' + m.face : ''}`, m.time); },
  transcript(m) {
    if (!m.final) { $('interim').textContent = m.text; return; }
    $('interim').textContent = '';
    const p = document.createElement('p');
    const tm = document.createElement('time'); tm.textContent = hhmmss();
    p.append(tm, document.createTextNode(m.text));       // band text: never innerHTML
    $('lines').append(p); $('lines').scrollTop = $('lines').scrollHeight;
  },
  recordings(m) {
    $('files').replaceChildren(...m.files.map((f) => {
      const li = document.createElement('li'), a = document.createElement('a');
      a.textContent = f; a.onclick = () => { $('player').src = `/recordings/${encodeURIComponent(f)}`; $('player').play(); };
      li.append(a); return li;
    }));
  },
};

// ------------------------------------------------------------------ socket
let ws;
function open() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';   // https pages (dev tunnels) need wss
  try {
    ws = new WebSocket(`${proto}://${location.host}/ws`);
  } catch (err) {
    handlers.status({ state: 'error', band: '–', message: `WebSocket failed: ${err.message}` });
    return setTimeout(open, 3000);
  }
  ws.binaryType = 'arraybuffer';
  ws.onmessage = (e) => {
    if (typeof e.data !== 'string') return onPcm(e.data);
    const m = JSON.parse(e.data);
    handlers[m.type]?.(m);
  };
  ws.onclose = () => { handlers.status({ state: 'error', band: '–', message: 'Server not reachable, retrying...' }); setTimeout(open, 1500); };
}
open();
const send = (o) => ws.readyState === 1 && ws.send(JSON.stringify(o));
$('connect').onclick = () => send({ cmd: 'connect' });
$('mic').onclick = () => send({ cmd: 'mic', on: !$('mic').dataset.on });
