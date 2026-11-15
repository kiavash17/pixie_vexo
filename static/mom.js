// Pixie guardian ("mom view"): what the parent sees on their phone.
// The server sends a full {type:"pixie"} snapshot on every change and once a second.
// UX rules: action first, one consistent message per alert, plain words (no model names,
// percentages or dBm), colour only for alert states, technical detail folded away.
const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined) e.textContent = text; return e; };
const PARAMS = new URLSearchParams(location.search);
const DEMO = PARAMS.has('demo');
if (PARAMS.get('welcome') === '0') document.getElementById('welcome').classList.add('hidden');
let S = null;                                   // latest snapshot
let ws = null;
const send = (o) => ws && ws.readyState === 1 && ws.send(JSON.stringify(o));

// ------------------------------------------------------------------ words
const clockTime = (t) => new Date(t * 1000).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
function ago(t) {
  if (!t) return '';
  const s = Math.max(0, Math.round(Date.now() / 1000 - t));
  if (s < 10) return 'just now';
  if (s < 60) return `${s} s ago`;
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  return clockTime(t);
}
function dayLabel(t) {
  const d = new Date(t * 1000), today = new Date();
  const y = new Date(); y.setDate(today.getDate() - 1);
  if (d.toDateString() === today.toDateString()) return 'Today';
  if (d.toDateString() === y.toDateString()) return 'Yesterday';
  return d.toLocaleDateString([], { weekday: 'long', month: 'short', day: 'numeric' });
}
/** Server log text -> words for a parent: no percentages, model names or light-colour jargon. */
function plain(text) {
  return String(text || '')
    .replace(/\s*\(\d+%\)/g, '')
    .replace(/\s*\((simulated[^)]*|magenta blink|pink glow|band glows green)\)/gi, '')
    .replace(/^(Rules|Gemini|AI assistant): /, 'Pixie: ')
    .replace(/: \(simulated[^)]*\)$/i, '')
    .trim();
}
/** Outcome choices per kind of event: [stored value, icon, words]. The serious one is always 'urgent'. */
const OUTCOMES = {
  help: [['wanted me', '👋', 'Just wanted me'], ['accidental', '🤚', 'Pocket tap'], ['urgent', '❗', 'Real problem']],
  voice: [['wanted me', '👋', 'Just wanted me'], ['misheard', '🔇', "Wasn't calling"], ['urgent', '❗', 'Real problem']],
  fall: [['ok', '👍', 'Was fine'], ['hurt', '🤕', 'Got hurt'], ['dropped', '📉', 'Just dropped the band']],
  cry: [['small upset', '🙂', 'Small upset'], ['urgent', '💔', 'Really upset'], ['misheard', '🔇', "Wasn't crying"]],
  anger: [['loud', '🔊', 'Just loud'], ['urgent', '⚠️', 'Worrying'], ['misheard', '🔇', 'Misheard']],
  danger: [['safe', '✅', 'Safe, I know them'], ['urgent', '🚨', 'Real concern'], ['misheard', '🔇', 'Misheard']],
};
function outcomeWords(e, value) {
  const list = OUTCOMES[eventKind(e)] || OUTCOMES.help;
  const hit = list.find(([v]) => v === value) || Object.values(OUTCOMES).flat().find(([v]) => v === value);
  return hit ? `${hit[1]} ${hit[2]}` : value;
}
const SIGNAL_WORDS = { crying: '😢 Crying', screaming: '😱 Screaming', adult_anger: '😠 Angry adult', adult_concerning: '⚠ Worrying adult' };

// ------------------------------------------------------------------ sound (#7)
let audioCtx = null, lastChime = 0;
function enableSound() {
  audioCtx = audioCtx || new AudioContext();
  audioCtx.resume();
  $('welcome').classList.add('hidden');
  chime(1);
  render();
}
$('enable-sound').onclick = enableSound;
$('sound-off').onclick = enableSound;
$('s-sound-btn').onclick = () => { if (!audioCtx) enableSound(); else chime(2); };
$('skip-sound').onclick = () => { $('welcome').classList.add('hidden'); render(); };
function chime(urgency) {
  if (!audioCtx) return;
  const notes = urgency >= 2 ? [880, 660, 880, 660] : [660, 880];
  notes.forEach((f, i) => {
    const o = audioCtx.createOscillator(), g = audioCtx.createGain();
    const t = audioCtx.currentTime + i * 0.18;
    o.frequency.value = f;
    g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(0.3, t + 0.02); g.gain.exponentialRampToValueAtTime(0.0001, t + 0.16);
    o.connect(g).connect(audioCtx.destination); o.start(t); o.stop(t + 0.17);
  });
  if (navigator.vibrate) navigator.vibrate(urgency >= 2 ? [200, 100, 200, 100, 200] : [200]);
}
function maybeChime(a) {                          // repeat until someone answers; faster when it matters
  if (!a || !['listening', 'waiting', 'checking'].includes(a.state)) return;
  const urgent = a.level >= 2 || a.escalation > 0;
  if (Date.now() / 1000 - lastChime >= (urgent ? 3 : 8)) { lastChime = Date.now() / 1000; chime(urgent ? 2 : 1); }
}

// ------------------------------------------------------------------ render
function render() {
  if (!S) return;
  const b = S.band, a = S.active, child = S.child;
  $('child').textContent = child; $('avatar').textContent = child[0];

  // #6 band status always in the header
  const line = $('bandline');
  if (b.connected) {
    const bat = b.battery == null ? '' : ` · ${b.battery}%${b.charging ? ' ⚡' : ''}`;
    $('bandtext').textContent = `Band on${bat} · ${ago(b.last_seen) || 'just now'}`;
    line.className = 'bandline ok';
  } else {
    $('bandtext').textContent = b.state === 'connecting' ? 'Connecting to band…' : 'Band offline';
    line.className = 'bandline bad';
  }
  const notice = S.notice || (!b.connected && b.state !== 'connecting' ? `${child}'s band is offline: alerts can't reach you` : '');
  $('banner').textContent = notice ? `⚠ ${notice}` : '';
  $('banner').className = `banner ${notice && !/offline|connection/i.test(notice) ? 'warn' : ''} ${notice ? '' : 'hidden'}`;
  $('sound-off').classList.toggle('hidden', !!audioCtx || !$('welcome').classList.contains('hidden'));

  // alert vs calm
  $('alert').classList.toggle('hidden', !a);
  $('calm').classList.toggle('hidden', !!a);
  if (a) renderAlert(a, child); else { lastAlertId = null; $('a-sheet').classList.add('hidden'); }
  renderCalm(child);
  $('b-hug').disabled = $('b-find').disabled = !b.connected;
  $('b-hug').textContent = `💗 Send ${child} a hug`;
  renderHistory(child);
  renderWallet(S.wallet, child);
  renderNudge(child);
  renderListenIn(child);
  renderNearby(child);
  renderCaptions();
  renderTodos();
  renderSettings();
}

// ------------------------------------------------------------------ listen in (live sound)
let liveCtx = null, liveNext = 0;
function playPcm(buf) {                          // 20 ms of PCM16 mono @16 kHz from the server
  if (!S || !S.listen_in || !liveCtx) return;
  const pcm = new Int16Array(buf);
  const ab = liveCtx.createBuffer(1, pcm.length, 16000);
  const ch = ab.getChannelData(0);
  let peak = 0;
  for (let i = 0; i < pcm.length; i++) { ch[i] = pcm[i] / 32768; peak = Math.max(peak, Math.abs(ch[i])); }
  const src = liveCtx.createBufferSource(); src.buffer = ab; src.connect(liveCtx.destination);
  const now = liveCtx.currentTime;
  if (liveNext < now + 0.05 || liveNext > now + 0.6) liveNext = now + 0.15;   // small jitter buffer
  src.start(liveNext); liveNext += ab.duration;
  $('vu').style.width = `${Math.min(100, peak * 160)}%`;
}
function renderListenIn(child) {
  const li = S.listen_in;
  $('livebar').classList.toggle('hidden', !li);
  $('b-listen-in').disabled = !S.band.connected;
  $('b-listen-in').textContent = li ? '🎧 Listening…' : '🎧 Listen in';
  if (li) {
    const s = Math.round(Date.now() / 1000 - li.t);
    $('live-title').textContent = `Listening live · ${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
    $('live-sub').textContent = `${child}'s band light is blue so ${child} can see it · stops after 2 min`;
  }
}
$('b-listen-in').onclick = () => {
  liveCtx = liveCtx || new AudioContext({ sampleRate: 16000 });   // the tap itself unlocks audio
  liveCtx.resume();
  send({ cmd: 'listen_in', on: !(S && S.listen_in), by: 'Mom' });
};
$('live-stop').onclick = () => send({ cmd: 'listen_in', on: false });

// ------------------------------------------------------------------ who's around (Gemini voice counts)
let peopleKey = '';
function renderNearby(child) {
  const n = S.nearby || {}, L = S.listen || {};
  const box = $('nearby');
  if (!L.on) {
    box.className = 'nearby stale'; $('people').replaceChildren();
    $('nearby-t').textContent = 'Turn on Listening to see who is around';
    return;
  }
  const others = Math.max(0, (n.children || 0) - 1);           // the wearer is one of the children heard
  const adults = n.adults || 0;
  const fresh = n.recent && n.t && Date.now() / 1000 - n.t < 120;
  box.className = `nearby ${fresh ? '' : 'stale'}`;
  const key = `${fresh}|${others}|${adults}`;
  if (key !== peopleKey) {                                    // only rebuild (and animate) when it changes
    peopleKey = key;
    const nodes = [];
    const me = el('div', 'person me'); me.append(el('span', 'me-face', child[0]), el('small', '', child)); nodes.push(me);
    if (fresh && (others || adults)) nodes.push(el('span', 'sep'));
    const add = (count, icons, cls, label) => {
      for (let i = 0; i < Math.min(count, 5); i++) {
        const p = el('div', `person ${cls}`);
        p.append(document.createTextNode(icons[i % icons.length]), el('small', '', i === 0 ? `${count} ${label}` : ''));
        nodes.push(p);
      }
      if (count > 5) nodes.push(el('span', 'more', `+${count - 5}`));
    };
    if (fresh) {
      add(others, ['👧', '👦'], 'kid', others === 1 ? 'child' : 'children');
      add(adults, ['👩', '👨'], 'adult', adults === 1 ? 'adult' : 'adults');
    }
    $('people').replaceChildren(...nodes);
  }
  const words = [];
  if (others) words.push(`${others} other ${others === 1 ? 'child' : 'children'}`);
  if (adults) words.push(`${adults} ${adults === 1 ? 'adult' : 'adults'}`);
  const spoke = S.voice && S.voice.child_t ? ` · ${child} spoke ${ago(S.voice.child_t)}` : '';
  $('nearby-t').textContent = (!fresh
    ? (n.t ? `No voices heard recently (last ${ago(n.t)})` : 'No voices heard yet')
    : words.length ? `${words.join(' · ')} · heard ${ago(n.t)}` : `Only ${child} heard · ${ago(n.t)}`) + spoke;
}

// ------------------------------------------------------------------ live captions
const capLines = [];
function onCaption(m) {
  if (!S || !S.captions) return;
  if (!m.final) { $('cap-interim').textContent = m.text; return; }
  $('cap-interim').textContent = '';
  capLines.push({ t: Date.now() / 1000, text: m.text, who: null });
  while (capLines.length > 8) capLines.shift();
  drawCaptions();
  $('cap-lines').scrollTop = $('cap-lines').scrollHeight;
}
function drawCaptions() {
  const child = S ? S.child : 'Maya';
  const tagging = S && S.voice && S.voice.on;
  $('cap-lines').replaceChildren(...capLines.map((l) => {
    const p = el('p'); p.append(el('time', '', clockTime(l.t)));
    if (l.who) p.append(el('span', `who ${l.who}`, l.who === 'child' ? child : 'someone else'));
    else if (tagging && Date.now() / 1000 - l.t < 40) p.append(el('span', 'who pending', 'identifying…'));
    p.append(document.createTextNode(l.text));
    return p;
  }));
}
const wordsOf = (s) => new Set(s.toLowerCase().replace(/[^\p{L}\p{N}' ]/gu, ' ').split(/\s+/).filter((w) => w.length > 1));
/** Scribe's speaker tags arrive ~15 s after the words: put them on the matching caption lines. */
function onVoices(m) {
  for (const seg of m.segments) {
    const sw = wordsOf(seg.text);
    if (!sw.size) continue;
    let best = null, bestScore = 0;
    for (const l of capLines) {
      if (l.who || l.t < seg.t - 8 || l.t > seg.end + 20) continue;
      const lw = wordsOf(l.text);
      const shared = [...lw].filter((w) => sw.has(w)).length;
      const score = lw.size ? shared / lw.size : 0;
      if (score > bestScore) { bestScore = score; best = l; }
    }
    if (best && bestScore >= 0.4) best.who = seg.who;
  }
  drawCaptions();
}
function renderCaptions() {
  $('captions').classList.toggle('hidden', !S.captions);
  $('b-captions').textContent = S.captions ? '📝 Captions on' : '📝 Captions';
  $('b-captions').disabled = !S.band.connected;
  if (S.captions && capLines.length) drawCaptions();   // lets "identifying…" badges expire
}
$('b-captions').onclick = () => send({ cmd: 'captions', on: !(S && S.captions) });
$('cap-stop').onclick = () => send({ cmd: 'captions', on: false });

// ------------------------------------------------------------------ for Mom & Dad (to-dos from what others said)
let lastTodoId = null;
function renderTodos() {
  const list = S.todos || [];
  $('todos').classList.toggle('hidden', !list.length);
  const open = list.filter((t) => !t.done);
  $('todo-count').textContent = open.length ? `${open.length} to do` : 'all done ✓';
  if (list[0] && list[0].id !== lastTodoId) { if (lastTodoId !== null) chime(1); lastTodoId = list[0].id; }
  const sorted = [...open, ...list.filter((t) => t.done)];
  $('todo-list').replaceChildren(...sorted.map((t) => {
    const li = el('li', t.done ? 'done' : '');
    const cb = el('input'); cb.type = 'checkbox'; cb.checked = !!t.done;
    cb.onchange = () => send({ cmd: 'todo_done', id: t.id, done: cb.checked });
    const body = el('div', 'todo-body');
    body.append(el('b', '', t.action + (t.when ? ` · ${t.when}` : '')),
      el('small', '', `${t.who.charAt(0).toUpperCase() + t.who.slice(1)} · ${clockTime(t.t)}${t.quote ? ` · “${t.quote}”` : ''}`));
    const del = el('button', 'todo-del', '✕'); del.title = 'Remove';
    del.onclick = () => send({ cmd: 'todo_delete', id: t.id });
    li.append(cb, body, del);
    return li;
  }));
}

// ------------------------------------------------------------------ full-day transcript (backseat)
let trWhich = 'today', trLines = [];
async function openTranscript(which) {
  trWhich = which || 'today';
  $('tr').classList.remove('hidden');
  document.querySelectorAll('#tr-tabs button').forEach((b) => b.classList.toggle('on', b.dataset.tr === trWhich));
  $('tr-title').textContent = `${S ? S.child : 'Maya'}'s transcript`;
  $('tr-lines').replaceChildren(el('p', 'empty', 'Loading…'));
  const r = await fetch(`/api/transcript?which=${trWhich}`);
  trLines = (await r.json()).lines || [];
  renderTranscript();
}
function renderTranscript() {
  const q = $('tr-search').value.trim().toLowerCase();
  const lines = trLines.filter((l) => !q || l.text.toLowerCase().includes(q));
  const nodes = [];
  let hour = null;
  for (const l of lines) {
    const h = new Date(l.t * 1000).getHours();
    if (h !== hour) { hour = h; nodes.push(el('div', 'day', `${h % 12 || 12} ${h < 12 ? 'AM' : 'PM'}`)); }
    const p = el('p', `tr-line ${l.who || ''}`); p.append(el('time', '', clockTime(l.t)));
    if (l.who) p.append(el('span', `who ${l.who}`, l.who === 'child' ? (S ? S.child : 'Maya') : 'someone else'));
    p.append(document.createTextNode(l.text));
    nodes.push(p);
  }
  if (!nodes.length) nodes.push(el('p', 'empty', q ? 'No matches.' : 'Nothing recorded yet today. Turn on Listening mode or Captions.'));
  $('tr-lines').replaceChildren(...nodes);
}
$('tr-search').oninput = renderTranscript;
document.querySelectorAll('#tr-tabs button').forEach((b) => { b.onclick = () => openTranscript(b.dataset.tr); });
$('tr-close').onclick = () => $('tr').classList.add('hidden');
$('tr').onclick = (e) => { if (e.target === $('tr')) $('tr').classList.add('hidden'); };
$('open-transcript').onclick = () => openTranscript('today');
$('day-transcript').onclick = () => openTranscript(dayWhich || 'today');

// ------------------------------------------------------------------ patterns vs baseline (weeks / months)
let ptView = 'weeks';
function openPatterns(view) {
  ptView = view || 'weeks';
  $('pt').classList.remove('hidden');
  document.querySelectorAll('#pt-tabs button').forEach((b) => b.classList.toggle('on', b.dataset.pt === ptView));
  $('pt-ai').replaceChildren(el('span', 'pulse'), document.createTextNode(' Looking for patterns…'));
  send({ cmd: 'trends', view: ptView });
}
function spark(series, low, high, flag) {
  const w = 120, h = 34, max = Math.max(...series, high) * 1.1 || 1, min = Math.min(0, ...series);
  const y = (v) => h - ((v - min) / (max - min)) * h;
  const pts = series.map((v, i) => `${(i / (series.length - 1)) * w},${y(v).toFixed(1)}`).join(' ');
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg'); svg.setAttribute('viewBox', `0 0 ${w} ${h}`); svg.setAttribute('class', 'spark');
  const band = document.createElementNS(ns, 'rect');
  band.setAttribute('x', 0); band.setAttribute('width', w); band.setAttribute('y', y(high)); band.setAttribute('height', Math.max(1, y(low) - y(high)));
  band.setAttribute('class', 'band');
  const line = document.createElementNS(ns, 'polyline'); line.setAttribute('points', pts); line.setAttribute('class', flag ? 'ln flag' : 'ln');
  const last = series.length - 1, dot = document.createElementNS(ns, 'circle');
  dot.setAttribute('cx', w); dot.setAttribute('cy', y(series[last])); dot.setAttribute('r', 3); dot.setAttribute('class', flag ? 'dot flag' : 'dot');
  svg.append(band, line, dot);
  return svg;
}
function renderTrends(d) {
  if (d.view !== ptView) return;
  const per = d.unit === 'week' ? 'this week' : 'this month';
  $('pt-title').textContent = `${d.child}'s patterns`;
  $('pt-sub').textContent = `${per[0].toUpperCase() + per.slice(1)} compared with ${d.child}'s own baseline (the ${d.baseline_periods} ${d.unit}s before)${d.example ? ' · example data' : ''}.`;
  const row = (m, isMention) => {
    const r = el('div', `pt-row ${m.flag ? 'flag' : m.better ? 'better' : ''}`);
    const left = el('div', 'pt-l');
    left.append(el('span', 'pt-ic', m.icon), el('div', '', ''));
    const fmt = (v) => (v >= 100 ? Math.round(v).toLocaleString() : String(Math.round(v * 10) / 10));
    left.lastChild.append(el('b', '', m.label), el('small', '', `usually ${fmt(m.low)}–${fmt(m.high)}${m.unit ? ' ' + m.unit : ''}`));
    const right = el('div', 'pt-r');
    const now = el('b', 'pt-now', `${typeof m.now === 'number' && m.now > 999 ? m.now.toLocaleString() : m.now}`);
    const tag = m.flag ? (isMention ? '⬆ more than usual' : '⚠ outside usual') : m.better ? '✓ better' : 'normal';
    right.append(now, el('small', `pt-tag ${m.flag ? 'warn' : ''}`, tag));
    r.append(left, spark(m.series, m.low, m.high, m.flag), right);
    return r;
  };
  $('pt-metrics').replaceChildren(...d.metrics.map((m) => row(m, false)));
  $('pt-mentions').replaceChildren(...d.mentions.map((m) => row(m, true)));
  const ai = d.ai;
  if (ai && !ai.error) {
    const nodes = [el('p', 'pt-sum', ai.summary)];
    for (const p of ai.patterns || []) {
      const c = el('div', `pt-card ${p.kind}`);
      c.append(el('b', '', `${{ health: '🩺', anxiety: '😟', isolation: '🫥', activity: '🏃', positive: '🌟' }[p.kind] || '•'} ${p.title}`),
        el('p', '', p.detail), el('p', 'pt-sug', `→ ${p.suggest}`));
      nodes.push(c);
    }
    nodes.push(el('p', 'tr-note', 'Pixie points out patterns; it does not diagnose. Talk to your pediatrician about health worries.'));
    $('pt-ai').replaceChildren(...nodes);
  } else if (ai && ai.error) {
    $('pt-ai').textContent = 'Patterns couldn\'t be written just now.';
  }
}
document.querySelectorAll('#pt-tabs button').forEach((b) => { b.onclick = () => openPatterns(b.dataset.pt); });
$('pt-close').onclick = () => $('pt').classList.add('hidden');
$('pt').onclick = (e) => { if (e.target === $('pt')) $('pt').classList.add('hidden'); };
$('open-patterns').onclick = () => openPatterns('weeks');

// ------------------------------------------------------------------ quiet-time nudge
function renderNudge(child) {
  const n = S.nudge;
  $('nudge').classList.toggle('hidden', !n);
  if (!n) return;
  const mins = Math.round((Date.now() / 1000 - n.since) / 60);
  const h = Math.floor(mins / 60), m = mins % 60;
  $('nudge-title').textContent = `${child} hasn't talked with anyone for ${h ? `${h} h${m ? ` ${m} min` : ''}` : `${m} min`}`;
  $('nudge-sub').textContent = `It's been quiet since ${clockTime(n.since)}. Some kids need a gentle check-in.`;
}
$('nudge-hug').onclick = () => { send({ cmd: 'hug' }); send({ cmd: 'nudge_dismiss' }); };
$('nudge-ok').onclick = () => send({ cmd: 'nudge_dismiss' });
$('s-quiet').onchange = (e) => send({ cmd: 'quiet_check', minutes: Number(e.target.value) });
$('s-gesture').onchange = (e) => send({ cmd: 'gesture', value: e.target.value });
$('s-enroll').onclick = () => send({ cmd: 'enroll_voice' });

// ------------------------------------------------------------------ the day as a picture
let dayWhich = null;
function openDay(which) {
  dayWhich = which;
  $('day').classList.remove('hidden');
  $('day-ai').replaceChildren(el('span', 'pulse'), document.createTextNode(' Writing the day\'s note…'));
  document.querySelectorAll('#day-tabs button').forEach((b) => b.classList.toggle('on', b.dataset.day === which));
  send({ cmd: 'day', which });
}
document.querySelectorAll('[data-day]').forEach((b) => { b.onclick = () => openDay(b.dataset.day); });
$('day-close').onclick = () => { $('day').classList.add('hidden'); dayWhich = null; };
$('day').onclick = (e) => { if (e.target === $('day')) $('day-close').onclick(); };
const hm = (mins) => { const h = Math.floor(mins / 60), m = mins % 60; return h ? `${h}h${m ? ` ${m}m` : ''}` : `${m}m`; };
function renderDay(d) {
  if (d.which !== dayWhich) return;
  const [r0, r1] = d.range, span = r1 - r0;
  const pos = (m) => `${Math.max(0, Math.min(100, ((m - r0) / span) * 100))}%`;
  const width = (s, e) => `${Math.max(0.3, ((Math.min(e, r1) - Math.max(s, r0)) / span) * 100)}%`;
  $('day-title').textContent = `${d.child}'s day · ${d.label}`;
  const st = d.stats;
  const tiles = [
    ['👣', st.steps.toLocaleString(), 'steps', st.steps >= 6000 ? 'good' : ''],
    ['🏃', hm(st.active_min), 'active', ''],
    ['💬', hm(st.talk_min), 'talking', ''],
    ['🫥', st.longest_alone ? hm(st.longest_alone) : '–', 'longest alone', st.longest_alone >= 60 ? 'warn' : ''],
    ['🙋', String(st.help + st.distress), st.avg_answer != null ? `alerts · ${st.avg_answer}s reply` : 'alerts', st.distress ? 'warn' : ''],
    ['💳', `$${st.spent.toFixed(2)}`, `${st.purchases} bought`, ''],
  ];
  $('day-stats').replaceChildren(...tiles.map(([i, v, l, c]) => {
    const t = el('div', `dstat ${c}`); t.append(el('span', 'i', i), el('b', '', v), el('small', '', l)); return t;
  }));
  const segs = (list, cls) => list.filter(([s, e]) => e > r0 && s < r1).map(([s, e, v]) => {
    const n = el('div', `seg ${cls || v}`); n.style.left = pos(s); n.style.width = width(s, e); return n;
  });
  $('strip-move').replaceChildren(...segs(d.activity));
  $('strip-talk').replaceChildren(...segs(d.social), ...segs(d.alone, 'alone'));
  $('strip-marks').replaceChildren(...d.markers.filter((m) => m.m >= r0 && m.m <= r1).map((m) => {
    const n = el('div', 'mark', m.icon); n.style.left = pos(m.m); n.title = `${String(Math.floor(m.m / 60)).padStart(2, '0')}:${String(m.m % 60).padStart(2, '0')} ${m.text}`; return n;
  }));
  const axis = [];
  for (let h = r0 / 60; h <= r1 / 60; h += 2) {
    const s = el('span', '', `${h % 12 || 12}${h < 12 ? 'a' : 'p'}`); s.style.left = pos(h * 60); axis.push(s);
  }
  $('strip-axis').replaceChildren(...axis);
  const ai = d.ai;
  $('day-headline').textContent = ai && ai.headline ? ai.headline : '';
  if (ai && !ai.error) {
    const box = [el('p', '', ai.summary)];
    const ul = el('ul'); (ai.highlights || []).forEach((h) => ul.append(el('li', '', h))); box.push(ul);
    if (ai.action_items && ai.action_items.length) {
      box.push(el('h3', 'section', '✅ Next steps'));
      const steps = el('ul', 'steps'); ai.action_items.forEach((s) => steps.append(el('li', '', s))); box.push(steps);
    }
    if (ai.watch_for) box.push(el('div', 'watch', `👀 ${ai.watch_for}`));
    $('day-ai').replaceChildren(...box);
  } else if (ai && ai.error) {
    $('day-ai').textContent = 'The day\'s note couldn\'t be written just now.';
  }
}

// ------------------------------------------------------------------ Pixie Card (demo)
const money = (v) => `$${Number(v).toFixed(2)}`;
const CAT_ICON = { snacks: '🍬', drinks: '🧃', toys: '🧸', games: '🎮' };
function openSettings(anchor) {
  $('settings').classList.remove('hidden');
  if (anchor) setTimeout(() => $(anchor).scrollIntoView({ behavior: 'smooth', block: 'start' }), 50);
}
$('w-edit').onclick = () => openSettings('s-card');
$('t-listen-btn').onclick = () => send({ cmd: 'listen', on: !(S && S.listen && S.listen.on) });
$('t-money').onclick = () => (S && S.wallet && S.wallet.card ? $('wallet').scrollIntoView({ behavior: 'smooth' }) : openSettings('s-card'));
let lastAskId = null;
function renderWallet(W, child) {
  if (!W) return;
  document.querySelectorAll('.w-child').forEach((n) => { n.textContent = child; });
  const p = W.pending;
  const asking = p && p.state === 'asking';
  $('w-ask').classList.toggle('hidden', !asking);
  if (asking) {
    $('w-ask-title').textContent = `${child} wants to buy ${p.item.emoji} ${p.item.name} · ${money(p.item.price)}`;
    $('w-ask-why').textContent = `It's ${p.why}. Approve just this once?`;
    if (p.id !== lastAskId) { lastAskId = p.id; chime(1); }
  }
  $('w-setup').classList.toggle('hidden', !!W.card);
  $('w-card').classList.toggle('hidden', !W.card);
  $('w-stats').classList.toggle('hidden', !W.card);
  $('w-edit').classList.toggle('hidden', !W.card);
  if (W.card) {
    $('w-left').textContent = money(W.left_today);
    $('w-bar').style.width = `${W.daily ? Math.min(100, (W.left_today / W.daily) * 100) : 0}%`;
    $('w-spent').textContent = `Spent ${money(W.spent_today)} of ${money(W.daily)} today`;
    $('w-name').textContent = W.card.name.toUpperCase();
    $('w-last4').textContent = `•••• ${W.card.last4 === 'DEMO' ? '0606' : W.card.last4}`;
    $('w-paused').classList.toggle('hidden', !W.frozen);
    $('w-per').textContent = money(W.per_purchase).replace('.00', '');
    $('w-cats').textContent = Object.entries(W.categories).filter(([, on]) => on).map(([k]) => CAT_ICON[k] || '•').join('') || '—';
    $('w-status').textContent = W.frozen ? '⏸' : '✅';
    $('w-status-l').textContent = W.frozen ? 'paused' : 'active';
  }
  $('w-recent-h').classList.toggle('hidden', !W.recent.length);
  $('w-recent').replaceChildren(...W.recent.map((t) => {
    const ok = t.status === 'approved';
    const li = el('li', ok ? '' : 'declined');
    li.title = `${t.item} · ${clockTime(t.t)}${ok ? (t.by_parent ? ' · you approved' : '') : ` · declined${t.note ? ': ' + t.note : ''}`}`;
    li.append(el('div', 'em', t.emoji), el('span', 'nm', t.item), el('span', `amt ${ok ? '' : 'no'}`, ok ? money(t.amount) : 'Declined'),
      el('small', '', clockTime(t.t)));
    if (t.by_parent) li.append(el('span', 'badge-x', ok ? '👍' : '✋'));
    else if (!ok) li.append(el('span', 'badge-x', '✋'));
    return li;
  }));
}
$('w-create').onclick = () => send({ cmd: 'wallet', action: 'create_card' });
$('w-approve').onclick = () => send({ cmd: 'wallet', action: 'decide', id: S.wallet.pending.id, approve: true });
$('w-decline').onclick = () => send({ cmd: 'wallet', action: 'decide', id: S.wallet.pending.id, approve: false });
function renderWalletSettings(W) {
  if (!W) return;
  if (document.activeElement !== $('s-daily')) $('s-daily').value = W.daily;
  if (document.activeElement !== $('s-per')) $('s-per').value = W.per_purchase;
  $('s-frozen').checked = W.frozen;
  const box = $('s-cats');
  if (!box.children.length) {
    for (const [k, name] of Object.entries(W.category_names)) {
      const lab = el('label'); const cb = el('input'); cb.type = 'checkbox'; cb.dataset.cat = k;
      cb.onchange = () => send({ cmd: 'wallet', action: 'set', categories: { [k]: cb.checked } });
      lab.append(cb, document.createTextNode(name)); box.append(lab);
    }
  }
  box.querySelectorAll('input').forEach((cb) => { cb.checked = !!W.categories[cb.dataset.cat]; });
}
/** Two-tap confirm on the page itself: first tap arms the button for 4 s, second tap runs it. */
function confirmButton(btn, label, run) {
  let timer = null;
  btn.onclick = () => {
    if (!btn.classList.contains('confirm')) {
      btn.classList.add('confirm'); btn.textContent = 'Tap again to delete';
      timer = setTimeout(() => { btn.classList.remove('confirm'); btn.textContent = label; }, 4000);
      return;
    }
    clearTimeout(timer); btn.classList.remove('confirm'); btn.textContent = 'Cleared ✓';
    run();
    setTimeout(() => { btn.textContent = label; }, 2000);
  };
}
confirmButton($('s-clear-history'), 'Clear', () => send({ cmd: 'clear_history' }));
confirmButton($('h-clear'), '🗑 Clear', () => send({ cmd: 'clear_history' }));
confirmButton($('s-clear-tx'), 'Clear', () => send({ cmd: 'wallet', action: 'clear_tx' }));

$('s-daily').onchange = (e) => send({ cmd: 'wallet', action: 'set', daily: e.target.value });
$('s-per').onchange = (e) => send({ cmd: 'wallet', action: 'set', per_purchase: e.target.value });
$('s-frozen').onchange = (e) => send({ cmd: 'wallet', action: 'set', frozen: e.target.checked });

const ACTIVITY_ICON = { still: ['🧍', 'Still'], walk: ['🚶', 'Walking'], run: ['🏃', 'Running'] };
function signalBars(rssi) {
  if (rssi == null) return 0;
  return rssi > -60 ? 4 : rssi > -70 ? 3 : rssi > -80 ? 2 : 1;
}
function renderCalm(child) {
  const b = S.band, L = S.listen || {};
  $('hero-avatar').textContent = child[0];
  $('ring').className = `ring ${!b.connected ? 'offline' : L.on ? 'listening' : ''}`;
  $('hero-title').textContent = b.connected ? `${child} is OK` : `Can't reach ${child}'s band`;
  $('calm-sub').textContent = !b.connected ? 'Alerts can\'t reach you until it reconnects'
    : S.gesture === 'once' ? 'Double-tap the band = "I need you"' : 'Double-tap twice = "I need you"';
  // battery gauge
  const bat = b.battery;
  const g = $('t-bat');
  g.style.setProperty('--p', bat == null ? 0 : bat);
  g.style.setProperty('--c', bat == null ? '#dedbe9' : bat < 20 ? '#c62828' : bat < 50 ? '#f2a51a' : '#2fbf71');
  $('t-bat-v').textContent = bat == null ? '–' : `${bat}%${b.charging ? '⚡' : ''}`;
  // distance as signal bars
  const lit = b.connected ? signalBars(b.rssi) : 0;
  $('t-sig').querySelectorAll('i').forEach((i, n) => i.classList.toggle('on', n < lit));
  $('t-sig-l').textContent = !b.connected ? 'Offline' : lit >= 4 ? 'Very close' : lit >= 2 ? 'Nearby' : lit ? 'Far' : 'Distance';
  // activity
  const [ic, word] = ACTIVITY_ICON[b.activity] || ['🧍', 'Activity'];
  $('t-act').textContent = ic; $('t-act-l').textContent = word;
  $('t-steps').textContent = b.steps == null ? '' : `👣 ${b.steps}`;
  // Pixie Card: money left today
  const W = S.wallet;
  const mg = $('t-money-g');
  if (W && W.card) {
    const pct = W.daily ? (W.left_today / W.daily) * 100 : 0;
    mg.style.setProperty('--p', pct);
    mg.style.setProperty('--c', W.frozen ? '#9e9e9e' : pct < 20 ? '#c62828' : '#b5179e');
    $('t-money-v').textContent = `$${Math.floor(W.left_today)}`;
    $('t-money-l').textContent = W.frozen ? 'Card paused' : 'Left today';
  } else {
    mg.style.setProperty('--p', 0);
    $('t-money-v').textContent = '💳';
    $('t-money-l').textContent = 'Set up card';
  }
  // listening
  const worry = L.on && !L.quiet && L.last && Object.keys(SIGNAL_WORDS).some((k) => (L.last[k] || 0) >= 0.4);
  $('t-listen').textContent = !L.on ? '🔇' : worry ? '👂' : '🎧';
  $('t-listen').classList.toggle('off', !L.on);
  $('t-listen-l').textContent = !L.on ? 'Not listening' : worry ? 'Heard something' : 'All quiet';
  const lb = $('t-listen-btn');
  lb.classList.toggle('on', !!L.on);
  lb.setAttribute('aria-pressed', L.on ? 'true' : 'false');
  lb.disabled = !L.gemini || !b.connected;
  $('t-listen-sw').textContent = !L.gemini ? 'No key' : L.on ? 'On · tap off' : 'Tap to listen';
}

let lastAlertId = null;
function renderAlert(a, child) {
  if (a.id !== lastAlertId) { lastAlertId = a.id; lastChime = 0; $('a-sheet').classList.add('hidden'); $('a-audio').removeAttribute('src'); $('a-details').open = false; }
  $('b-allgood').textContent = { fall: "They're OK", danger: 'Resolve' }[eventKind(a)] || 'All good';
  const choicesKey = `${a.id}|${eventKind(a)}`;
  if ($('a-choices').dataset.key !== choicesKey) { $('a-choices').dataset.key = choicesKey; renderChoices(a); }
  const urgent = a.level >= 2;
  const now = Date.now() / 1000;
  const waiting = ['listening', 'waiting'].includes(a.state);
  // worrying adult (luring / grooming patterns): the most dramatic state, details shown at once
  const danger = Boolean((a.signals && a.signals.adult_concerning >= 0.6) || (a.concern_quotes && a.concern_quotes.length));
  // one colour + icon per kind of event; urgency is a red ring + tag, so the kind stays recognisable
  const kind = eventKind(a);
  const [kIcon, kLabel] = kindMeta(a, kind);
  const coming = a.state === 'coming';
  $('alert').className = ['alert', `k-${kind}`, kind === 'danger' ? 'danger' : '', (kind !== 'help' || coming) ? 'dark' : '',
    coming ? 'coming' : '', urgent && !coming ? 'is-urgent' : ''].filter(Boolean).join(' ');
  $('a-chip').textContent = coming ? '✓ On the way' : `${kIcon} ${kLabel}`;
  $('a-urgent').classList.toggle('hidden', !(urgent && !coming && kind !== 'danger'));
  $('a-icon').textContent = coming ? '🏃' : kIcon;
  let title;
  if (a.state === 'coming') title = danger ? `Go to ${child} now: you're on your way` : `You're on your way`;
  else if (a.state === 'checking') title = `Checking on ${child}`;
  else if (danger) title = `A worrying adult is talking to ${child}`;
  else if (a.kind === 'distress') title = plain(a.reasons[0]);
  else if (a.trigger === 'voice') title = urgent ? `${child} is calling for you, urgently` : `${child} is calling for you`;
  else title = urgent ? `${child} needs you now` : `${child} wants you`;
  $('a-title').textContent = title;
  if (a.trigger === 'voice' && ['listening', 'waiting'].includes(a.state)) $('a-icon').textContent = '🗣️';

  $('a-danger').classList.toggle('hidden', !danger);
  if (danger) {
    $('a-behaviour').textContent = a.concern ? a.concern.charAt(0).toUpperCase() + a.concern.slice(1) : 'Behaviour that matches luring patterns';
    const quotes = (a.concern_quotes || []).slice(-4);
    $('a-quotes').replaceChildren(...(quotes.length ? quotes : ['(listen to the recording in Details)']).map((q) => el('li', '', quotes.length ? `“${q}”` : q)));
  }

  const latestReason = plain(a.reasons[a.reasons.length - 1]);
  const aiFits = a.ai && (a.ai.urgency === 'urgent' || !urgent);       // never "calm" under an urgent header
  let reason;
  if (a.state === 'coming') reason = `${child}'s band is glowing green, so they know you're coming.`;
  else if (a.state === 'checking') reason = `Possible fall. ${child}'s band is asking if everything is OK.`;
  else reason = aiFits ? plain(a.ai.summary) : latestReason;
  if (reason === title || (danger && reason === plain(a.reasons[0]))) reason = '';   // never repeat the title
  $('a-reason').textContent = reason;
  $('a-reason').classList.toggle('hidden', !reason);
  $('a-meta').textContent = `${ago(a.created)}${a.acked_by ? ` · ${a.acked_by} is on the way` : ''}`;

  // live listening + quote (#3: only when there is something)
  const listening = a.state === 'listening';
  $('a-live').classList.toggle('hidden', !listening);
  $('a-live-text').textContent = a.live_text ? `“${a.live_text}”` : `Listening to ${child}…`;
  const said = a.trigger === 'voice' && a.call_words ? a.call_words : (!listening ? a.transcript : '');
  const quote = !danger && said ? `“${said}”` : '';
  $('a-quote').textContent = quote; $('a-quote').classList.toggle('hidden', !quote);

  // actions (#2 first) + next step (#4 no dead end)
  const stalled = Boolean(a.stalled && waiting);   // must be a real boolean: toggle(x, undefined) flips!
  $('a-actions').classList.toggle('hidden', stalled);
  $('a-stalled').classList.toggle('hidden', !stalled);
  $('b-coming').classList.toggle('hidden', a.state === 'coming');
  $('b-coming').textContent = a.state === 'checking' ? `I'll check` : `I'm coming`;
  $('a-actions').style.gridTemplateColumns = a.state === 'coming' ? '1fr' : '';
  $('b-call').textContent = `📞 Call ${S.guardians[1].name}`;
  let next = '';
  if (a.state === 'checking') next = `If ${child} doesn't answer, you'll get an alert in ${Math.max(0, Math.round(a.created + 15 - now))} s.`;
  else if (stalled) next = `Everyone has been alerted and ${child} is still waiting.`;
  $('a-next').textContent = next; $('a-next').classList.toggle('hidden', !next);
  renderLadder(a, waiting && !stalled, now);

  // evidence chips in plain words
  const chips = [];                               // who's around is shown in its own strip below the card
  if (a.signals) for (const [k, v] of Object.entries(a.signals)) {
    if (v >= 0.6 && SIGNAL_WORDS[k] && !(danger && k === 'adult_concerning')) chips.push(SIGNAL_WORDS[k]);
  }
  if (a.ai && a.ai.tone) chips.push(`Sounds ${a.ai.tone.toLowerCase()}`);
  $('a-chips').replaceChildren(...chips.map((c) => el('span', '', c)));

  // details (folded)
  $('a-ai').classList.toggle('hidden', !a.ai || a.ai.source === 'rules');
  if (a.ai) { $('a-ai-why').textContent = plain(a.ai.why); $('a-ai-act').textContent = plain(a.ai.suggested_action); }
  const hasClip = !!a.audio && !listening;
  $('a-voice').classList.toggle('hidden', !hasClip);
  if (hasClip) {
    $('a-voice-label').textContent = a.kind === 'distress' ? 'What Pixie heard' : 'Voice note';
    if (!$('a-audio').getAttribute('src')) $('a-audio').setAttribute('src', `/recordings/${encodeURIComponent(a.audio)}`);
  }
  $('a-timeline').replaceChildren(...a.timeline.map((x) => {
    const li = el('li'); li.append(el('time', '', clockTime(x.t)), document.createTextNode(plain(x.text))); return li;
  }));
  maybeChime(a);
}

/** Escalation as a picture: 👩 Mom → 👨 Dad → 📞 Call, with a countdown ring on the current step. */
function renderLadder(a, show, now) {
  const box = $('a-ladder');
  box.classList.toggle('hidden', !show);
  if (!show) return;
  const [g1, g2] = S.guardians;
  const steps = [['👩', g1.name], ['👨', g2.name], ['📞', 'Call']];
  const nodes = [];
  steps.forEach(([ic, name], i) => {
    if (i) nodes.push(el('div', 'link-line'));
    const state = i < a.escalation + 1 ? (i === a.escalation ? 'now' : 'done') : 'pending';
    const step = el('div', `step ${state}`);
    const dot = el('div', 'dot');
    if (state === 'now' && i < steps.length - 1) {
      const start = a.created + S.ack_timeout * i, due = start + S.ack_timeout;
      dot.style.setProperty('--p', Math.max(0, Math.min(100, ((due - now) / S.ack_timeout) * 100)));
      dot.append(el('b', '', ic));
      step.append(dot, el('span', '', `${name} · ${Math.max(0, Math.round(due - now))}s`));
    } else {
      dot.textContent = ic;
      step.append(dot, el('span', '', name));
    }
    nodes.push(step);
  });
  box.replaceChildren(...nodes);
}

/** The kind of event decides its colour and icon everywhere (alert card, history). */
function eventKind(e) {
  const s = e.signals || {};
  if ((e.concern_quotes && e.concern_quotes.length) || s.adult_concerning >= 0.6) return 'danger';
  if (e.kind === 'fall' || e.state === 'checking') return 'fall';
  if (e.kind === 'distress') return (s.adult_anger >= 0.6 || s.screaming >= 0.6) ? 'anger' : 'cry';
  if (e.trigger === 'voice') return 'voice';
  if (e.kind === 'alone') return 'alone';
  return 'help';
}
function kindMeta(e, kind) {
  const s = e.signals || {};
  return {
    danger: ['⚠️', 'Possible luring'], fall: ['🤸', 'Possible fall'], voice: ['🗣️', 'Calling you'],
    cry: ['😢', 'Crying'], anger: s.screaming >= 0.6 && !(s.adult_anger >= 0.6) ? ['😱', 'Screaming'] : ['😠', 'Angry voice'],
    alone: ['💬', 'Quiet time'], help: ['🙋', 'Needs you'],
  }[kind];
}

// ------------------------------------------------------------------ history (#9)
function historyTitle(e, child) {
  if (e.kind === 'fall') return e.outcome === 'ok' ? `Fall check: ${child} said OK` : 'Possible fall';
  if (e.kind === 'distress' && e.concern_quotes && e.concern_quotes.length) return `Worrying adult talked to ${child}`;
  if (e.kind === 'distress') return plain(e.reasons[0]);
  if (e.kind === 'note') return plain(e.reasons[0].split(':')[0]);
  if (e.kind === 'alone') return plain(e.reasons[0]);
  if (e.trigger === 'voice') return `${child} called for you`;
  return e.level >= 2 ? `${child} needed you urgently` : `${child} asked for you`;
}
function historyIcon(e) {
  if (e.kind === 'fall') return '🤸';
  if (e.kind === 'alone') return '💬';
  if (e.trigger === 'voice') return '🗣️';
  if (e.kind === 'note') return '🗣';
  if (e.kind === 'distress') return e.level >= 2 ? '🚨' : '😢';
  return e.level >= 2 ? '🚨' : '🙋';
}
function renderHistory(child) {
  const all = S.history || [];
  const important = all.filter((e) => e.kind !== 'note' || e.audio);
  const device = all.filter((e) => e.kind === 'note' && !e.audio);
  const box = $('history');
  const nodes = [];
  let lastDay = null;
  for (const e of important) {
    const d = dayLabel(e.created);
    if (d !== lastDay) { nodes.push(el('div', 'day', d)); lastDay = d; }
    const lure = e.concern_quotes && e.concern_quotes.length;
    const k = e.kind === 'note' ? 'note' : eventKind(e);
    const item = el('div', `item k-${k}`);
    item.append(el('div', 'ic', k === 'note' ? '🗣' : kindMeta(e, k)[0]));
    const body = el('div', 'body');
    const top = el('div', 'top');
    top.append(el('span', 'title', historyTitle(e, child)), el('span', 'time', clockTime(e.created)));
    body.append(top);
    const sub = lure ? `${e.concern ? e.concern + ': ' : ''}“${e.concern_quotes[0]}”`
      : e.transcript ? `“${e.transcript}”` : e.kind === 'note' ? plain(e.reasons[0].split(':').slice(1).join(':')) : (e.ai ? plain(e.ai.summary) : '');
    if (sub) body.append(el('div', 'sub', sub));
    const foot = el('div', 'foot');
    if (e.acked_at) foot.append(el('span', 'outcome', `⏱ ${Math.round(e.acked_at - e.created)} s · ${e.acked_by}`));
    if (e.audio) {
      const play = el('button', 'mini', '▶ Play');
      play.onclick = () => new Audio(`/recordings/${encodeURIComponent(e.audio)}`).play();
      foot.append(play);
    }
    if (!['note', 'alone'].includes(e.kind)) {
      if (e.outcome) {
        const o = el('span', 'outcome'); o.append(el('b', '', outcomeWords(e, e.outcome))); foot.append(o);
      } else {
        for (const [k, icon, words] of OUTCOMES[eventKind(e)] || OUTCOMES.help) {
          const t = el('button', 'mini', `${icon} ${words}`);
          t.onclick = () => send({ cmd: 'label', id: e.id, outcome: k });
          foot.append(t);
        }
      }
    }
    body.append(foot);
    item.append(body);
    nodes.push(item);
  }
  if (!nodes.length) nodes.push(el('div', 'empty', `Nothing yet. Alerts from ${child}'s band will show up here.`));
  $('h-clear').classList.toggle('hidden', !all.length);
  box.replaceChildren(...nodes);
  $('device-log-sum').textContent = `Device & app events (${device.length})`;
  $('device-events').replaceChildren(...device.map((e) => el('li', '', `${clockTime(e.created)} · ${plain(e.reasons[0])}`)));
}

// ------------------------------------------------------------------ settings (#10)
function renderSettings() {
  renderWalletSettings(S.wallet);
  if (document.activeElement !== $('s-quiet')) $('s-quiet').value = String(S.quiet_minutes);
  if (document.activeElement !== $('s-gesture')) $('s-gesture').value = S.gesture || 'twice';
  const v = S.voice || {};
  $('s-enroll').disabled = !v.on || v.enrolling || !S.band.connected;
  $('s-enroll').textContent = v.enrolling ? '🔴 Recording… ask Maya to talk' : (v.enrolled ? '🎙 Record again' : '🎙 Record 10 s');
  $('s-voice').textContent = !v.on ? 'Needs an ElevenLabs key (.env.local)'
    : v.error ? `Couldn't check: ${v.error}`
    : `${v.enrolled ? 'Enrolled ✓' : 'Not enrolled yet: record Maya talking alone for 10 s'} · ${v.method === 'library' ? 'matched by ElevenLabs speaker profile' : v.method === 'loudness' ? 'told apart by how close the voice is to the band' : 'waiting for speech'}`;
  const n = (S.history || []).length;
  $('s-hist-count').textContent = n ? `${n} entr${n === 1 ? 'y' : 'ies'}: past alerts, device events and their recordings` : 'Nothing to clear';
  $('s-clear-history').disabled = !n;
  $('s-listen').checked = !!(S.listen && S.listen.on);
  $('s-listen').disabled = !(S.listen && S.listen.gemini);
  $('s-fall').checked = S.fall_check;
  const [g1, g2] = S.guardians;
  $('s-guardians').textContent = `${g1.name} first, then ${g2.name} if no one answers in ${S.ack_timeout} s`;
  $('s-sound').textContent = audioCtx ? 'On (sound and vibration)' : 'Off: tap Test sound to turn on';
  const b = S.band;
  $('s-band-name').textContent = b.name || 'Band';
  const bits = [b.connected ? 'Connected' : 'Offline'];
  if (b.battery != null) bits.push(`battery ${b.battery}%${b.charging ? ' (charging)' : ''}`);
  if (b.signal) bits.push(b.signal.toLowerCase());
  if (b.activity) bits.push(b.activity);
  $('s-band-detail').textContent = bits.join(' · ');
}
$('open-settings').onclick = () => $('settings').classList.remove('hidden');
$('close-settings').onclick = () => $('settings').classList.add('hidden');
$('settings').onclick = (e) => { if (e.target === $('settings')) $('settings').classList.add('hidden'); };
$('s-listen').onchange = (e) => send({ cmd: 'listen', on: e.target.checked });
$('s-fall').onchange = (e) => send({ cmd: 'fall_check', on: e.target.checked });

// ------------------------------------------------------------------ actions
$('b-coming').onclick = () => send({ cmd: 'ack', by: 'Mom' });
$('b-allgood').onclick = () => $('a-sheet').classList.toggle('hidden');
$('b-handled').onclick = () => $('a-sheet').classList.remove('hidden');
$('b-call').onclick = () => send({ cmd: 'call', by: 'Mom', who: S.guardians[1].name });
/** The "what happened?" choices fit the kind of event (a fall is not a "pocket tap"). */
function renderChoices(a) {
  const list = [...(OUTCOMES[eventKind(a)] || OUTCOMES.help), ['', '⏭', 'Skip']];
  $('a-choices').replaceChildren(...list.map(([v, icon, words]) => {
    const b = el('button'); b.append(el('span', '', icon), document.createTextNode(words));
    b.onclick = () => send({ cmd: 'resolve', by: 'Mom', outcome: v || null });
    return b;
  }));
}
$('b-hug').onclick = () => send({ cmd: 'hug' });
$('b-find').onclick = () => send({ cmd: 'find' });
if (DEMO) {
  $('demo').classList.remove('hidden');
  document.querySelectorAll('#demo [data-sim]').forEach((b) => { b.onclick = () => send({ cmd: 'simulate', what: b.dataset.sim }); });
}
setInterval(render, 1000);                        // countdowns and "x s ago"

// ------------------------------------------------------------------ socket
function open() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.binaryType = 'arraybuffer';
  ws.onmessage = (e) => {
    if (typeof e.data !== 'string') return playPcm(e.data);   // live sound (only played while listening in)
    const m = JSON.parse(e.data);
    if (m.type === 'pixie') {
      const first = !S;
      S = m; render();
      if (first && PARAMS.get('day')) openDay(PARAMS.get('day'));   // /mom?day=typical opens the day picture
      if (first && PARAMS.get('patterns')) openPatterns(PARAMS.get('patterns'));   // /mom?patterns=weeks
      if (first && PARAMS.get('transcript')) openTranscript(PARAMS.get('transcript'));
    }
    else if (m.type === 'day') renderDay(m);
    else if (m.type === 'trends') renderTrends(m);
    else if (m.type === 'transcript') onCaption(m);
    else if (m.type === 'voices') onVoices(m);
  };
  ws.onclose = () => {
    if (S) { S.band.connected = false; S.band.state = 'offline'; S.notice = 'Lost connection to Pixie, retrying…'; render(); }
    setTimeout(open, 1500);
  };
}
open();
