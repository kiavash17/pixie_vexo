// Feature showcase video of the Pixie parent app: the top 10 features in ~2 minutes.
//
//   npm run showcase        -> demo/out/pixie-showcase.mp4 (1920x1080, phone centered, feature titles beside it,
//                              warm voice-over from demo/assets/vo/, made with `python demo/make_voiceover.py`)
//
// Same setup as record.js (pretend band, own server on port 8779, Edge as a 390x844 phone), but it
// walks through the features beyond the help loop. Slow AI notes (Maya's day, patterns) are warmed up
// before recording so the video never waits on them. Env: PIXIE_PYTHON, SHOWCASE_PORT, DEMO_BROWSER.
const { chromium } = require('playwright');
const { spawn, spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const OUT = path.join(__dirname, 'out');
const RAW = path.join(OUT, 'raw-showcase');
const PORT = Number(process.env.SHOWCASE_PORT || 8779);
const PYTHON = process.env.PIXIE_PYTHON || 'python';
const BASE = `http://127.0.0.1:${PORT}`;
const P = 1500;                                       // the deliberate pause between steps
const TOTAL = 10;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const log = (...a) => console.log('[showcase]', ...a);

// ------------------------------------------------------------------ backend (pretend band)
function startServer() {
  fs.rmSync(path.join(ROOT, 'data-sim'), { recursive: true, force: true });
  const out = fs.createWriteStream(path.join(OUT, 'showcase-server.log'));
  const proc = spawn(PYTHON, ['-u', 'server.py', '--sim', '--port', String(PORT),
    '--sim-audio', path.join(__dirname, 'assets', 'maya.ogg')], { cwd: ROOT });
  proc.stdout.pipe(out);
  proc.stderr.pipe(out);
  return proc;
}

function connectBand() {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(`ws://127.0.0.1:${PORT}/ws`);
    const st = { snap: null, day: {}, trends: {} };
    ws.onmessage = (e) => {
      if (typeof e.data !== 'string') return;
      const m = JSON.parse(e.data);
      if (m.type === 'pixie') st.snap = m;
      else if (m.type === 'day') st.day[m.which] = m;
      else if (m.type === 'trends') st.trends[m.view] = m;
    };
    ws.onerror = reject;
    ws.onopen = () => resolve({ send: (o) => ws.send(JSON.stringify(o)), st, close: () => ws.close() });
  });
}

async function waitFor(check, what, timeout = 60000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    try { if (await check()) return true; } catch { /* not yet */ }
    await sleep(250);
  }
  log(`(gave up waiting for ${what})`);
  return false;
}

// ------------------------------------------------------------------ narration: titles beside the phone + voice-over
// Voice-over lines (demo/make_voiceover.py): intro, f1..f10, outro. A new title waits until the previous line is spoken.
const VO_DIR = path.join(__dirname, 'assets', 'vo');
const VO = JSON.parse(fs.readFileSync(path.join(VO_DIR, 'vo.json'), 'utf8'));
const captions = [];
const voice = [];
let videoStart = 0;
let voiceEnd = 0;
const voiceDone = async () => { const w = voiceEnd - Date.now(); if (w > 0) await sleep(w); };
async function cap(n, text, sub, label) {
  await voiceDone();
  const id = label === 'Pixie' ? (n === 0 ? 'intro' : 'outro') : `f${n}`;
  const t = (Date.now() - videoStart) / 1000;
  captions.push({ t, text, sub: sub || '', n: Math.max(n, 0), total: TOTAL, label: label || `Feature ${n} of ${TOTAL}` });
  voice.push({ t: t + 0.3, path: path.join(VO_DIR, `${id}.wav`) });
  voiceEnd = Date.now() + (0.3 + VO[id] + 0.6) * 1000;
}

async function tap(page, selector) {
  const el = page.locator(selector).first();
  await el.scrollIntoViewIfNeeded();
  const box = await el.boundingBox();
  await page.evaluate(({ x, y }) => {
    const d = document.createElement('div');
    Object.assign(d.style, {
      position: 'fixed', left: `${x - 22}px`, top: `${y - 22}px`, width: '44px', height: '44px', borderRadius: '50%',
      background: 'rgba(43,34,64,.25)', border: '2px solid #2b2240', zIndex: 9998, pointerEvents: 'none',
      transition: 'transform .45s ease-out, opacity .45s ease-out',
    });
    document.body.appendChild(d);
    requestAnimationFrame(() => { d.style.transform = 'scale(1.8)'; d.style.opacity = '0'; });
    setTimeout(() => d.remove(), 600);
  }, { x: box.x + box.width / 2, y: box.y + box.height / 2 });
  await sleep(350);
  await el.click();
}

const scrollTo = (page, selector, block = 'start') =>
  page.evaluate(({ s, b }) => document.querySelector(s).scrollIntoView({ behavior: 'smooth', block: b }), { s: selector, b: block });
const scrollTop = (page) => page.evaluate(() => window.scrollTo({ top: 0, behavior: 'smooth' }));
const scrollPanel = (page, overlay, top) =>
  page.evaluate(({ o, t }) => document.querySelector(`${o} .panel`).scrollTo({ top: t, behavior: 'smooth' }), { o: overlay, t: top });

// ------------------------------------------------------------------ the showcase
async function main() {
  fs.mkdirSync(RAW, { recursive: true });
  log('starting Pixie on the pretend band…');
  const server = startServer();
  let browser;
  try {
    await waitFor(async () => (await fetch(`${BASE}/mom`)).ok, 'the server');
    const band = await connectBand();
    const { send, st } = band;
    await waitFor(() => st.snap && st.snap.band.connected, 'the pretend band');
    await waitFor(() => st.snap.listen && st.snap.listen.on, 'listening mode', 8000);
    send({ cmd: 'listen', on: false });                  // deterministic: events come from the script
    await waitFor(() => !st.snap.band.mic, 'the mic to close', 8000);

    log('warming up (card, Maya\'s day note, patterns note)…');
    send({ cmd: 'wallet', action: 'create_card' });
    send({ cmd: 'day', which: 'rough' });
    send({ cmd: 'trends', view: 'weeks' });
    await waitFor(() => st.day.rough && st.day.rough.ai, 'the day note', 90000);
    await waitFor(() => st.trends.weeks && st.trends.weeks.ai, 'the patterns note', 90000);

    log('recording…');
    browser = await chromium.launch({ channel: process.env.DEMO_BROWSER || 'msedge' });
    const context = await browser.newContext({
      viewport: { width: 390, height: 844 }, deviceScaleFactor: 3, isMobile: true, hasTouch: true,
      recordVideo: { dir: RAW, size: { width: 390, height: 844 } },
    });
    const page = await context.newPage();
    videoStart = Date.now();
    await page.goto(`${BASE}/mom`);
    await page.waitForFunction(() => document.getElementById('bandtext').textContent.startsWith('Band on'));
    await sleep(500);
    // sync marker: a magenta flash at a known moment lets to_mp4.py line the video clock up with this one
    const sync = (Date.now() - videoStart) / 1000;
    await page.evaluate(() => {
      const d = document.createElement('div'); d.id = 'sync-flash';
      Object.assign(d.style, { position: 'fixed', inset: '0', background: '#ff00ff', zIndex: 99999 });
      document.body.appendChild(d);
    });
    await sleep(400);
    await page.evaluate(() => document.getElementById('sync-flash').remove());
    await sleep(400);
    const trim = (Date.now() - videoStart) / 1000;
    const resolve = async () => { send({ cmd: 'resolve', by: 'Mom', outcome: null }); await page.waitForSelector('#alert.hidden', { state: 'attached' }); };

    // intro
    await cap(0, 'Ten more things Pixie does', 'Beyond the help button: it listens, notices, and keeps Mom in the loop.', 'Pixie');
    await sleep(P * 2);

    // 1. worrying adult
    await cap(1, 'Spots a worrying adult', 'Luring patterns, with the exact words and a saved recording.');
    send({ cmd: 'simulate', what: 'adult_concerning' });
    send({ cmd: 'simulate', what: 'adult_concerning' });
    await page.waitForSelector('#alert.k-danger');
    await sleep(P * 2);
    await voiceDone();
    await resolve();

    // 2. help by voice
    await cap(2, 'Hears Maya call for help', '“Mommy!” works like a double-tap: no button needed.');
    await sleep(600);
    send({ cmd: 'simulate', what: 'voice' });
    await page.waitForSelector('#alert.k-voice');
    await sleep(P * 1.5);
    await voiceDone();
    await resolve();

    // 3. crying and an angry adult
    await cap(3, 'Notices crying and angry voices', 'Each kind of moment has its own colour.');
    send({ cmd: 'simulate', what: 'crying' });
    await page.waitForSelector('#alert.k-cry');
    await sleep(P * 2);
    await resolve();
    send({ cmd: 'simulate', what: 'adult_anger' });
    await page.waitForSelector('#alert.k-anger');
    await sleep(P);
    await voiceDone();
    await resolve();

    // 4. fall check
    await cap(4, 'Checks on Maya after a fall', 'The band asks “are you OK?”, and a double-tap answers.');
    send({ cmd: 'simulate', what: 'fall' });
    await page.waitForSelector('#alert.k-fall');
    await sleep(P * 2.2);                                  // past the 2.5 s "landing" grace
    send({ cmd: 'simulate', what: 'double-tap' });        // Maya: I'm OK
    await page.waitForSelector('#alert.hidden', { state: 'attached' });
    await scrollTo(page, '#history .item', 'center');
    await sleep(P);
    await voiceDone();
    await scrollTop(page);
    await sleep(600);

    // 5. live captions + who's around
    await cap(5, 'Live captions', 'Mom can read what’s being said around Maya, as it’s said.');
    await scrollTo(page, '#nearby', 'start');
    await sleep(P);
    await tap(page, '#b-captions');
    await waitFor(async () => (await page.locator('#cap-lines p').count()) > 0, 'a caption', 15000);
    await sleep(P);
    await voiceDone();
    await tap(page, '#cap-stop');
    await sleep(600);

    // 6. teacher messages -> to-dos
    await cap(6, 'Turns teacher messages into to-dos', '“Tell your mom to pack a lunch tomorrow” lands on Mom’s list.');
    send({ cmd: 'simulate', what: 'teacher' });
    await waitFor(async () => page.locator('#todos:not(.hidden)').count(), 'the to-do list', 40000);
    await scrollTo(page, '#todos', 'start');
    await sleep(P * 2.5);

    // 7. Pixie Card
    await cap(7, 'Tap-to-pay pocket money', 'Within the budget it just pays. Anything more asks Mom.');
    await scrollTo(page, '#wallet', 'start');
    await sleep(P);
    send({ cmd: 'wallet', action: 'arm', item: 'candy' });
    send({ cmd: 'wallet', action: 'tap' });
    await sleep(P * 1.5);
    send({ cmd: 'wallet', action: 'arm', item: 'car' });
    send({ cmd: 'wallet', action: 'tap' });
    await page.waitForSelector('#w-ask:not(.hidden)');
    await scrollTo(page, '#w-ask', 'center');
    await sleep(P * 1.5);
    await tap(page, '#w-approve');
    await sleep(P * 1.5);

    // 8. quiet-time nudge
    await cap(8, 'A gentle nudge after quiet time', 'If Maya hasn’t talked with anyone for an hour, Mom gets a soft check-in.');
    await scrollTop(page);
    send({ cmd: 'simulate', what: 'quiet' });
    await page.waitForSelector('#nudge:not(.hidden)');
    await scrollTo(page, '#nudge', 'center');
    await sleep(P * 1.8);
    await tap(page, '#nudge-hug');
    await sleep(P);

    // 9. Maya's day
    await cap(9, 'A picture of Maya’s day', 'Activity, talking and time alone, with an honest note and next steps.');
    await scrollTo(page, '.daycard', 'center');
    await sleep(700);
    await tap(page, '.daybtns [data-day="rough"]');
    await page.waitForSelector('#day-ai p', { timeout: 20000 }).catch(() => {});
    await sleep(P * 1.5);
    await scrollPanel(page, '#day', 520);
    await sleep(P);
    await voiceDone();
    await tap(page, '#day-close');
    await sleep(500);

    // 10. patterns vs baseline
    await cap(10, 'Patterns against Maya’s own baseline', 'Weeks of activity, talking and things Maya said, with gentle next steps.');
    await tap(page, '#open-patterns');
    await page.waitForSelector('#pt-ai .pt-card', { timeout: 20000 }).catch(() => {});
    await sleep(P * 2);
    await scrollPanel(page, '#pt', 700);
    await sleep(P);
    await voiceDone();
    await tap(page, '#pt-close');

    // outro
    await cap(TOTAL, 'Pixie', 'A screenless help band for kids. More freedom for them, peace of mind for you.', 'Pixie');
    await scrollTop(page);
    await sleep(P);
    await voiceDone();
    await sleep(3000);                                  // the recording loses its last ~2 s; keep the end calm

    const video = page.video();
    await context.close();
    const webm = await video.path();
    band.close();
    const total = (Date.now() - videoStart) / 1000 - trim;
    log(`recorded ${total.toFixed(0)} s`);

    const mp4 = path.join(OUT, 'pixie-showcase.mp4');
    const capFile = path.join(OUT, 'showcase-captions.json');
    const voFile = path.join(OUT, 'showcase-voice.json');
    fs.writeFileSync(capFile, JSON.stringify(captions, null, 1));
    fs.writeFileSync(voFile, JSON.stringify(voice, null, 1));
    log('composing the 1920x1080 video with the voice-over…');
    const conv = spawnSync(PYTHON, [path.join(__dirname, 'to_mp4.py'), webm, mp4, String(trim), '--landscape', capFile,
      '--audio', voFile, '--sync', String(sync)], { stdio: 'inherit' });
    if (conv.status !== 0) throw new Error('video conversion failed (the WebM is in demo/out/raw-showcase/)');
    log(`done: ${path.relative(ROOT, mp4)}`);
  } finally {
    if (browser) await browser.close();
    server.kill();
  }
}

main().catch((e) => { console.error('[showcase] failed:', e.message); process.exit(1); });
