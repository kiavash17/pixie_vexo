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
const OUTCOME_WORDS = { 'wanted me': '👋 Just wanted me', accidental: '🤚 Pocket tap', urgent: '❗ Real problem', ok: '👍 Said OK' };
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
  $('quick').classList.toggle('hidden', !!a);
  if (a) renderAlert(a, child); else { lastAlertId = null; $('a-sheet').classList.add('hidden'); }
  renderCalm(child);
  $('b-hug').disabled = $('b-find').disabled = !b.connected;
  $('b-hug').textContent = `💗 Send ${child} a hug`;
  renderHistory(child);
  renderWallet(S.wallet, child);
  renderSettings();
}

// ------------------------------------------------------------------ Pixie Card (demo)
const money = (v) => `$${Number(v).toFixed(2)}`;
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
  if (W.card) {
    $('w-left').textContent = money(W.left_today);
    $('w-bar').style.width = `${W.daily ? Math.min(100, (W.left_today / W.daily) * 100) : 0}%`;
    $('w-name').textContent = W.card.name.toUpperCase();
    $('w-paused').classList.toggle('hidden', !W.frozen);
  }
  $('w-recent').replaceChildren(...W.recent.slice(0, 4).map((t) => {
    const ok = t.status === 'approved';
    const li = el('li', ok ? '' : 'declined');
    li.title = `${t.item} · ${clockTime(t.t)}${ok ? (t.by_parent ? ' · you approved' : '') : ` · declined${t.note ? ': ' + t.note : ''}`}`;
    li.append(el('div', 'em', t.emoji), el('span', `amt ${ok ? '' : 'no'}`, ok ? money(t.amount) : 'No'),
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
  $('calm-sub').textContent = b.connected ? 'Double-tap the band = "I need you"' : 'Alerts can\'t reach you until it reconnects';
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
  // listening
  const worry = L.on && !L.quiet && L.last && Object.keys(SIGNAL_WORDS).some((k) => (L.last[k] || 0) >= 0.4);
  $('t-listen').textContent = !L.on ? '🔇' : worry ? '👂' : '🎧';
  $('t-listen').classList.toggle('off', !L.on);
  $('t-listen-l').textContent = !L.on ? 'Not listening' : worry ? 'Heard something' : 'All quiet';
}

let lastAlertId = null;
function renderAlert(a, child) {
  if (a.id !== lastAlertId) { lastAlertId = a.id; lastChime = 0; $('a-sheet').classList.add('hidden'); $('a-audio').removeAttribute('src'); $('a-details').open = false; }
  const urgent = a.level >= 2;
  const now = Date.now() / 1000;
  const waiting = ['listening', 'waiting'].includes(a.state);
  // worrying adult (luring / grooming patterns): the most dramatic state, details shown at once
  const danger = Boolean((a.signals && a.signals.adult_concerning >= 0.6) || (a.concern_quotes && a.concern_quotes.length));
  const cls = a.state === 'coming' ? 'coming' : a.state === 'checking' ? 'checking' : danger ? 'danger' : urgent ? 'urgent' : 'waiting';
  $('alert').className = `alert ${cls}${urgent && waiting && now - a.created < 180 ? ' fresh' : ''}`;

  // chip + title + ONE consistent reason line (#1)
  const chip = { coming: '✓ On the way', checking: '🤸 Checking', danger: '⚠ Possible luring', urgent: '🚨 Urgent', waiting: '⚠ Needs you' }[cls];
  $('a-chip').textContent = chip;
  const crying = a.signals && a.signals.crying >= 0.6;
  $('a-icon').textContent = { coming: '🏃', checking: '🤸', danger: '⚠️' }[cls]
    || (a.kind === 'distress' ? (crying && !urgent ? '😢' : a.signals && a.signals.adult_anger >= 0.6 ? '😠' : '😱') : urgent ? '🚨' : '🙋');
  let title;
  if (a.state === 'coming') title = danger ? `Go to ${child} now: you're on your way` : `You're on your way`;
  else if (a.state === 'checking') title = `Checking on ${child}`;
  else if (danger) title = `A worrying adult is talking to ${child}`;
  else if (a.kind === 'distress') title = plain(a.reasons[0]);
  else title = urgent ? `${child} needs you now` : `${child} wants you`;
  $('a-title').textContent = title;

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
  const quote = !listening && !danger && a.transcript ? `“${a.transcript}”` : '';
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
  const chips = [];
  if (a.voices && (a.voices.children || a.voices.adults)) chips.push(`👧 ${a.voices.children}  ·  🧑 ${a.voices.adults} nearby`);
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

// ------------------------------------------------------------------ history (#9)
function historyTitle(e, child) {
  if (e.kind === 'fall') return e.outcome === 'ok' ? `Fall check: ${child} said OK` : 'Possible fall';
  if (e.kind === 'distress' && e.concern_quotes && e.concern_quotes.length) return `Worrying adult talked to ${child}`;
  if (e.kind === 'distress') return plain(e.reasons[0]);
  if (e.kind === 'note') return plain(e.reasons[0].split(':')[0]);
  return e.level >= 2 ? `${child} needed you urgently` : `${child} asked for you`;
}
function historyIcon(e) {
  if (e.kind === 'fall') return '🤸';
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
    const sev = lure ? 3 : e.kind === 'note' ? 1 : e.outcome === 'ok' ? 0 : e.level >= 2 ? 2 : 1;
    const item = el('div', `item sev${sev}`);
    item.append(el('div', 'ic', lure ? '⚠️' : historyIcon(e)));
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
    if (e.kind !== 'note') {
      if (e.outcome) {
        const o = el('span', 'outcome'); o.append(el('b', '', OUTCOME_WORDS[e.outcome] || e.outcome)); foot.append(o);
      } else {
        for (const k of ['wanted me', 'accidental', 'urgent']) {
          const t = el('button', 'mini', OUTCOME_WORDS[k]);
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
  box.replaceChildren(...nodes);
  $('device-log-sum').textContent = `Device & app events (${device.length})`;
  $('device-events').replaceChildren(...device.map((e) => el('li', '', `${clockTime(e.created)} · ${plain(e.reasons[0])}`)));
}

// ------------------------------------------------------------------ settings (#10)
function renderSettings() {
  renderWalletSettings(S.wallet);
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
document.querySelectorAll('#a-sheet button').forEach((b) => {
  b.onclick = () => send({ cmd: 'resolve', by: 'Mom', outcome: b.dataset.o || null });
});
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
    if (typeof e.data !== 'string') return;       // live audio is for the control room
    const m = JSON.parse(e.data);
    if (m.type === 'pixie') { S = m; render(); }
  };
  ws.onclose = () => {
    if (S) { S.band.connected = false; S.band.state = 'offline'; S.notice = 'Lost connection to Pixie, retrying…'; render(); }
    setTimeout(open, 1500);
  };
}
open();
