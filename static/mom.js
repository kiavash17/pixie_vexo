// Pixie guardian ("mom view"): what the parent sees on their phone.
// The server sends a full {type:"pixie"} snapshot on every change and once a second.
const $ = (id) => document.getElementById(id);
let S = null;                                   // latest snapshot
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined) e.textContent = text; return e; };
const clockTime = (t) => new Date(t * 1000).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', second: '2-digit' });
function ago(t) {
  if (!t) return '';
  const s = Math.max(0, Math.round(Date.now() / 1000 - t));
  if (s < 5) return 'just now';
  if (s < 60) return `${s} s ago`;
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  return clockTime(t);
}

// ------------------------------------------------------------------ alert sound
let audioCtx = null;
$('sound').onclick = () => {
  audioCtx = new AudioContext(); audioCtx.resume();
  $('sound').classList.add('hidden'); chime(1);
};
function chime(urgency) {
  if (!audioCtx) return;
  const notes = urgency >= 2 ? [880, 660, 880, 660] : [660, 880];
  notes.forEach((f, i) => {
    const o = audioCtx.createOscillator(), g = audioCtx.createGain();
    const t = audioCtx.currentTime + i * 0.18;
    o.frequency.value = f; o.type = 'sine';
    g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(0.3, t + 0.02); g.gain.exponentialRampToValueAtTime(0.0001, t + 0.16);
    o.connect(g).connect(audioCtx.destination); o.start(t); o.stop(t + 0.17);
  });
  if (navigator.vibrate) navigator.vibrate(urgency >= 2 ? [200, 100, 200, 100, 200] : [200]);
}
let lastChime = 0;
function maybeChime(a) {                         // repeat until acknowledged; faster when it matters
  if (!a || !['listening', 'waiting', 'checking'].includes(a.state)) return;
  const urgent = a.level >= 2 || a.escalation > 0;
  const every = urgent ? 3 : 8;
  if (Date.now() / 1000 - lastChime >= every) { lastChime = Date.now() / 1000; chime(urgent ? 2 : 1); }
}

// ------------------------------------------------------------------ render
function render() {
  if (!S) return;
  const b = S.band, a = S.active, child = S.child;
  $('child').textContent = child; $('avatar').textContent = child[0];
  $('dot').className = `dot ${b.connected ? 'on' : 'off'}`;
  $('notice').textContent = S.notice || ''; $('notice').classList.toggle('hidden', !S.notice);

  // status card
  $('s-conn').textContent = b.connected ? 'Connected' : b.state === 'connecting' ? 'Connecting…' : 'Offline';
  $('s-seen').textContent = b.last_seen ? `seen ${ago(b.last_seen)}` : '';
  $('s-bat').textContent = b.battery == null ? '–' : `${b.battery}%${b.charging ? ' ⚡' : ''}`;
  $('s-dist').textContent = b.signal || '–';
  $('s-rssi').textContent = b.rssi == null ? '' : `${b.rssi} dBm`;
  $('s-act').textContent = b.activity || '–';
  $('s-steps').textContent = b.steps == null ? '' : `${b.steps} steps since start`;
  $('b-fall').checked = S.fall_check;
  $('b-hug').disabled = $('b-find').disabled = !b.connected || b.mic;
  renderListen(S.listen);

  // alert vs calm
  $('calm').classList.toggle('hidden', !!a);
  $('alert').classList.toggle('hidden', !a);
  $('calm-sub').textContent = `${child} can double-tap the band whenever they need you.`;
  if (a) renderAlert(a, child);
  else { lastAlertId = null; $('a-outcomes').classList.add('hidden'); }
  renderHistory();
}

function renderListen(L) {
  if (!L) return;
  $('b-listen').checked = L.on;
  document.querySelector('.listen').classList.toggle('on', L.on);
  $('l-meters').classList.toggle('hidden', !L.on || !L.last);
  let text;
  if (!L.gemini) text = 'Needs GEMINI_API_KEY in .env on the server.';
  else if (!L.on) text = `Off. When on, Pixie listens for crying, screaming and angry adult voices (the band's light stays blue).`;
  else if (L.error) text = `Listening… last check failed: ${L.error}`;
  else if (L.quiet) text = `Listening… quiet around ${S.child}${L.t ? ` (checked ${ago(L.t)})` : ''}. Quiet moments aren't sent anywhere.`;
  else text = `Listening… checked ${ago(L.t)}: ${L.last.evidence || ''}`;
  $('l-body').textContent = `${text}${L.on ? ` · ${L.requests_hour} checks this hour` : ''}`;
  if (L.last) {
    for (const k of ['crying', 'screaming', 'adult_anger', 'adult_concerning']) {
      const v = L.last[k] || 0, bar = $(`m-${k}`);
      bar.style.width = `${Math.round(v * 100)}%`; bar.classList.toggle('hot', v >= 0.6);
    }
    $('l-voices').textContent = `Nearby: ${L.last.children} child${L.last.children === 1 ? '' : 'ren'} · ${L.last.adults} adult${L.last.adults === 1 ? '' : 's'}`;
  }
}

let lastAlertId = null;
function renderAlert(a, child) {
  if (a.id !== lastAlertId) { lastAlertId = a.id; lastChime = 0; $('a-outcomes').classList.add('hidden'); $('a-audio').removeAttribute('src'); }
  const urgent = a.level >= 2;
  const box = $('alert');
  box.className = `alert ${a.state === 'coming' ? 'coming' : a.state === 'checking' ? 'checking' : urgent ? 'urgent' : ''}`;
  const titles = {
    checking: [`🤸`, `Checking on ${child}…`],
    coming: [`🏃`, `You're on your way`],
    listening: urgent ? ['🚨', `URGENT: ${child} needs you`] : ['🙋', `${child} wants you`],
    waiting: urgent ? ['🚨', `URGENT: ${child} needs you`] : ['🙋', `${child} wants you`],
  };
  let [icon, title] = titles[a.state] || ['🙋', `${child} wants you`];
  if (a.kind === 'distress' && a.state !== 'coming') {
    icon = a.signals && a.signals.crying >= 0.6 && a.level < 2 ? '😢' : '🚨';
    title = a.reasons[0];
  }
  $('a-icon').textContent = icon; $('a-title').textContent = title;
  $('a-sub').textContent = `${a.reasons[0]} · ${ago(a.created)}${a.acked_by ? ` · ${a.acked_by} is coming` : ''}`;

  // countdown to the next escalation step / fall answer
  let cd = '';
  if (a.state === 'checking') cd = `Possible fall. ${child}'s band is blinking magenta: a double-tap means "I'm OK". Escalating in ${Math.max(0, Math.round(a.created + 15 - Date.now() / 1000))} s`;
  else if (['listening', 'waiting'].includes(a.state)) {
    const steps = [`louder alert + ${S.guardians[1].name} notified`, `automated call`];
    if (a.escalation < steps.length) {
      const due = a.created + S.ack_timeout * (a.escalation + 1) - Date.now() / 1000;
      cd = `No answer yet. ${steps[a.escalation]} in ${Math.max(0, Math.round(due))} s`;
    } else cd = 'All escalation steps done: still waiting for a guardian';
  } else if (a.state === 'coming') cd = `${child}'s band is glowing green: they know help is coming.`;
  $('a-countdown').textContent = cd; $('a-countdown').classList.toggle('hidden', !cd);

  // evidence chips: who's nearby, what was heard
  const chips = [];
  if (a.voices) chips.push(`👧 ${a.voices.children} · 🧑 ${a.voices.adults} nearby`);
  if (a.signals) for (const [k, v] of Object.entries(a.signals)) if (v >= 0.4) chips.push(`${k.replace('_', ' ')} ${Math.round(v * 100)}%`);
  if (a.ai && a.ai.tone) chips.push(`tone: ${a.ai.tone}`);
  if (a.concern) chips.push(`⚠ ${a.concern}`);
  $('a-chips').replaceChildren(...chips.map((c) => el('span', '', c)));

  // live listening
  const listening = a.state === 'listening';
  $('a-listen').classList.toggle('hidden', !listening);
  $('a-live').textContent = [a.transcript, a.live_text].filter(Boolean).join(' ');

  // AI / rules assessment
  $('a-ai').classList.toggle('hidden', !a.ai);
  if (a.ai) {
    $('a-ai-src').textContent = { gemini: 'GEMINI', ai: 'AI', rules: 'RULES' }[a.ai.source] || 'AI';
    $('a-ai-src').className = `badge ${a.ai.source === 'ai' ? '' : a.ai.source}`;
    $('a-ai-sum').textContent = a.ai.summary;
    $('a-ai-why').textContent = `${a.ai.urgency.toUpperCase()} · ${a.ai.why}`;
    $('a-ai-act').textContent = a.ai.suggested_action;
  }

  // voice note
  const hasVoice = !!a.audio && !listening;
  $('a-voice').classList.toggle('hidden', !hasVoice);
  if (hasVoice) {
    $('a-quote').textContent = a.transcript ? `“${a.transcript}”` : '(nothing said)';
    const src = `/recordings/${encodeURIComponent(a.audio)}`;
    if (!$('a-audio').getAttribute('src')) $('a-audio').setAttribute('src', src);
  }

  // buttons
  $('b-coming').classList.toggle('hidden', a.state === 'coming');
  $('b-coming').textContent = a.state === 'checking' ? `I'm going to check` : `I'm coming`;

  // timeline
  $('a-timeline').replaceChildren(...a.timeline.map((x) => {
    const li = el('li'); li.append(el('time', '', clockTime(x.t)), document.createTextNode(x.text)); return li;
  }));
  maybeChime(a);
}

function renderHistory() {
  const items = S.history.filter((e) => e.kind !== 'note' || true).slice(0, 25);
  $('history').replaceChildren(...items.map((e) => {
    const li = el('li');
    if (e.kind === 'note') {
      li.append(el('div', 'h-note', `${clockTime(e.created)} · ${e.reasons[0]}`));
      if (e.audio) {
        const play = el('button', 'tag', '▶ clip');
        play.onclick = () => new Audio(`/recordings/${encodeURIComponent(e.audio)}`).play();
        const tags = el('div', 'h-tags'); tags.append(play); li.append(tags);
      }
      return li;
    }
    const top = el('div', 'h-top');
    const title = e.kind === 'fall' ? 'Fall check' : e.kind === 'distress' ? e.reasons[0] : (e.level >= 2 ? 'Urgent request' : 'Help request');
    top.append(el('span', `h-title ${e.level >= 2 ? 'lvl2' : ''}`, title), el('span', 'h-time', clockTime(e.created)));
    li.append(top);
    const said = e.transcript ? `“${e.transcript}”` : (e.ai ? e.ai.summary : e.reasons[0]);
    const took = e.acked_at ? ` · answered in ${Math.round(e.acked_at - e.created)} s by ${e.acked_by}` : '';
    li.append(el('div', 'h-sub', `${said}${took}`));
    const tags = el('div', 'h-tags');
    for (const o of ['accidental', 'wanted me', 'urgent']) {
      const t = el('button', `tag ${e.outcome === o ? 'set' : ''}`, o);
      t.onclick = () => send({ cmd: 'label', id: e.id, outcome: o });
      tags.append(t);
    }
    if (e.outcome === 'ok') tags.replaceChildren(el('span', 'tag set', 'said OK'));
    if (e.audio) {
      const play = el('button', 'tag', '▶ voice');
      play.onclick = () => new Audio(`/recordings/${encodeURIComponent(e.audio)}`).play();
      tags.append(play);
    }
    li.append(tags);
    return li;
  }));
}
setInterval(render, 1000);                       // countdowns and "x s ago"

// ------------------------------------------------------------------ actions
let ws;
const send = (o) => ws && ws.readyState === 1 && ws.send(JSON.stringify(o));
$('b-coming').onclick = () => send({ cmd: 'ack', by: 'Mom' });
$('b-resolve').onclick = () => $('a-outcomes').classList.toggle('hidden');
document.querySelectorAll('#a-outcomes button').forEach((b) => { b.onclick = () => send({ cmd: 'resolve', by: 'Mom', outcome: b.dataset.o }); });
$('b-hug').onclick = () => send({ cmd: 'hug' });
$('b-find').onclick = () => send({ cmd: 'find' });
$('b-fall').onchange = (e) => send({ cmd: 'fall_check', on: e.target.checked });
$('sim-tap').onclick = () => send({ cmd: 'simulate', what: 'double-tap' });
$('sim-fall').onclick = () => send({ cmd: 'simulate', what: 'fall' });
$('sim-cry').onclick = () => send({ cmd: 'simulate', what: 'crying' });
$('sim-anger').onclick = () => send({ cmd: 'simulate', what: 'adult_anger' });
$('sim-concern').onclick = () => send({ cmd: 'simulate', what: 'adult_concerning' });
$('b-listen').onchange = (e) => send({ cmd: 'listen', on: e.target.checked });

// ------------------------------------------------------------------ socket
function open() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.binaryType = 'arraybuffer';
  ws.onmessage = (e) => {
    if (typeof e.data !== 'string') return;      // live audio is for the control room
    const m = JSON.parse(e.data);
    if (m.type === 'pixie') { S = m; render(); }
  };
  ws.onclose = () => {
    if (S) { S.band.connected = false; S.band.state = 'offline'; S.notice = 'Lost connection to Pixie, retrying…'; render(); }
    setTimeout(open, 1500);
  };
}
open();
