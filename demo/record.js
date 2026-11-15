// Scripted product demo of the Pixie parent app ("mom view"), recorded as a phone-sized video.
//
//   npm run demo                      -> demo/out/pixie-demo.mp4
//
// What it does, end to end, with no hardware:
//   1. starts its own Pixie server on the PRETEND band (port 8777, fresh demo data in data-sim/),
//   2. opens the mom view in Edge as a 390x844 phone (deviceScaleFactor 3) with video recording on,
//   3. plays the story with 1.5 s pauses: calm -> Maya taps her band -> alert card -> Mom taps
//      "I'm coming" -> the card turns green -> "All good" -> back to calm, logged in history,
//   4. converts Playwright's WebM to MP4 (H.264) with PyAV and stops the server.
//
// Band events are sent over the same WebSocket the pages use, exactly like the real band's events
// arrive at the server. Settings (env): PIXIE_PYTHON (Python with the project's packages; default
// "python"), DEMO_PORT (8777), DEMO_BROWSER ("msedge"; "chromium" needs `npx playwright install`).
const { chromium } = require('playwright');
const { spawn, spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const OUT = path.join(__dirname, 'out');
const RAW = path.join(OUT, 'raw');
const PORT = Number(process.env.DEMO_PORT || 8777);
const PYTHON = process.env.PIXIE_PYTHON || 'python';
const BASE = `http://127.0.0.1:${PORT}`;
const PAUSE = 1500;                                   // between steps: reads as a demo, not a test
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const log = (...a) => console.log('[demo]', ...a);

// ------------------------------------------------------------------ backend (pretend band)
function startServer() {
  fs.rmSync(path.join(ROOT, 'data-sim'), { recursive: true, force: true });   // fresh demo history
  const out = fs.createWriteStream(path.join(OUT, 'server.log'));
  // the pretend band's microphone plays a child's line (demo/assets/maya.ogg, made by demo/make_voice.py)
  const proc = spawn(PYTHON, ['-u', 'server.py', '--sim', '--port', String(PORT),
    '--sim-audio', path.join(__dirname, 'assets', 'maya.ogg')], { cwd: ROOT });
  proc.stdout.pipe(out);
  proc.stderr.pipe(out);
  proc.on('exit', (code) => { if (code) log(`server exited with code ${code} (see demo/out/server.log)`); });
  return proc;
}

/** The backend's WebSocket, used here the way the band's events reach the server. */
function connectBand() {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(`ws://127.0.0.1:${PORT}/ws`);
    let snap = null;
    ws.onmessage = (e) => {
      if (typeof e.data !== 'string') return;
      const m = JSON.parse(e.data);
      if (m.type === 'pixie') snap = m;
    };
    ws.onerror = reject;
    ws.onopen = () => resolve({
      send: (o) => ws.send(JSON.stringify(o)),
      snapshot: () => snap,
      close: () => ws.close(),
    });
  });
}

async function waitFor(check, what, timeout = 60000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    try { if (await check()) return; } catch { /* not yet */ }
    await sleep(300);
  }
  throw new Error(`timed out waiting for ${what}`);
}

// ------------------------------------------------------------------ on-screen narration
// landscape (default): captions are drawn beside the phone in the 1920x1080 video, not on the app;
// portrait (--portrait): captions float at the bottom of the phone screen.
const PORTRAIT = process.argv.includes('--portrait');
const captions = [];                                  // {t: seconds since the video started, text}
let videoStart = 0;
async function caption(page, text) {
  captions.push({ t: (Date.now() - videoStart) / 1000, text });
  if (!PORTRAIT) { await sleep(300); return; }
  await page.evaluate((t) => {
    let c = document.getElementById('demo-caption');
    if (!c) {
      c = document.createElement('div');
      c.id = 'demo-caption';
      Object.assign(c.style, {
        position: 'fixed', left: '12px', right: '12px', bottom: '18px', zIndex: 9999, padding: '12px 14px',
        borderRadius: '14px', background: 'rgba(27,24,48,.92)', color: '#fff', font: '600 15px system-ui',
        textAlign: 'center', boxShadow: '0 8px 24px rgba(0,0,0,.25)', transition: 'opacity .3s',
      });
      document.body.appendChild(c);
    }
    c.style.opacity = '0';
    setTimeout(() => { c.textContent = t; c.style.opacity = '1'; }, 150);
  }, text);
  await sleep(300);
}

/** Show a tap ripple where "Mom" taps, then tap. */
async function tap(page, selector) {
  const el = page.locator(selector);
  await el.scrollIntoViewIfNeeded();
  const box = await el.boundingBox();
  await page.evaluate(({ x, y }) => {
    const d = document.createElement('div');
    Object.assign(d.style, {
      position: 'fixed', left: `${x - 22}px`, top: `${y - 22}px`, width: '44px', height: '44px', borderRadius: '50%',
      background: 'rgba(91,63,217,.35)', border: '2px solid #5b3fd9', zIndex: 9998, pointerEvents: 'none',
      transition: 'transform .45s ease-out, opacity .45s ease-out',
    });
    document.body.appendChild(d);
    requestAnimationFrame(() => { d.style.transform = 'scale(1.8)'; d.style.opacity = '0'; });
    setTimeout(() => d.remove(), 600);
  }, { x: box.x + box.width / 2, y: box.y + box.height / 2 });
  await sleep(350);
  const info = await el.evaluate((n) => `${n.id} visible=${!!n.offsetParent} disabled=${n.disabled} text=${n.textContent}`);
  log('tap', selector, '->', info);
  await el.click();
}

// ------------------------------------------------------------------ the demo
async function main() {
  fs.mkdirSync(RAW, { recursive: true });
  log('starting Pixie on the pretend band…');
  const server = startServer();
  let browser;
  try {
    await waitFor(async () => (await fetch(`${BASE}/mom`)).ok, 'the server');
    const band = await connectBand();
    await waitFor(() => band.snapshot() && band.snapshot().band.connected, 'the pretend band to connect');
    // Listening mode turns itself on after connecting; switch it off to keep the story deterministic
    await waitFor(() => band.snapshot().listen && band.snapshot().listen.on, 'listening mode', 8000).catch(() => {});
    band.send({ cmd: 'listen', on: false });
    await waitFor(() => !band.snapshot().band.mic, 'the mic to close', 8000).catch(() => {});

    log('recording…');
    browser = await chromium.launch({ channel: process.env.DEMO_BROWSER || 'msedge' });
    const context = await browser.newContext({
      viewport: { width: 390, height: 844 }, deviceScaleFactor: 3, isMobile: true, hasTouch: true,
      // exactly the viewport: Playwright only scales the page DOWN to fit, so a bigger size left the
      // app in the top-left corner of a grey canvas. to_mp4.py scales it up when composing.
      recordVideo: { dir: RAW, size: { width: 390, height: 844 } },
    });
    const page = await context.newPage();
    const pageLog = fs.createWriteStream(path.join(OUT, 'page.log'));
    page.on('console', (m) => pageLog.write(`[${m.type()}] ${m.text()}\n`));
    page.on('pageerror', (e) => pageLog.write(`[pageerror] ${e.message}\n`));
    videoStart = Date.now();                           // the video starts with the page: trim the blank load
    page.on('websocket', (s) => {
      pageLog.write(`[ws] open ${s.url()}\n`);
      s.on('framesent', (f) => pageLog.write(`[ws] sent ${String(f.payload).slice(0, 80)}\n`));
      s.on('close', () => pageLog.write('[ws] closed\n'));
      s.on('socketerror', (e) => pageLog.write(`[ws] error ${e}\n`));
    });
    await page.goto(`${BASE}/mom`);
    await page.waitForFunction(() => document.getElementById('bandtext').textContent.startsWith('Band on'));
    await sleep(500);
    const trim = (Date.now() - videoStart) / 1000;
    await sleep(PAUSE);

    // 1. calm
    await caption(page, 'Maya is out playing. All calm.');
    await sleep(PAUSE * 2);

    // 2. the child asks for help: double-tap twice on the band
    await caption(page, 'Maya double-taps her band: “I need you”');
    await sleep(PAUSE);
    band.send({ cmd: 'simulate', what: 'double-tap' });
    await page.waitForSelector('#alert:not(.hidden)');
    await sleep(PAUSE);

    // 3. the alert card, then the 8 s voice note with what Maya said
    await caption(page, 'Mom’s phone lights up right away');
    await sleep(PAUSE * 2);
    await caption(page, 'Pixie listens for a few seconds…');
    await page.waitForSelector('#a-quote:not(.hidden)', { timeout: 20000 }).catch(() => {});
    await caption(page, '…so Mom hears what Maya said');
    await sleep(PAUSE * 2);

    // 4. the parent answers
    await caption(page, 'Mom taps “I’m coming”');
    await sleep(PAUSE);
    await tap(page, '#b-coming');
    await page.waitForSelector('#alert.coming');
    await sleep(PAUSE);

    // 5. green: help is on the way, and the band glows green on Maya's wrist
    await caption(page, 'Green: Maya’s band glows so she knows help is coming');
    await sleep(PAUSE * 2);

    // 6. wrap-up: all good, logged
    await caption(page, 'All good: Mom notes what happened');
    await sleep(PAUSE);
    await tap(page, '#b-allgood');
    await sleep(PAUSE);
    await tap(page, '#a-choices button:first-child');
    await page.waitForSelector('#alert.hidden', { state: 'attached' });
    await caption(page, 'Back to calm, saved in Maya’s history');
    await sleep(PAUSE * 2);

    const video = page.video();
    await context.close();                             // finishes the WebM
    const webm = await video.path();
    band.close();

    const mp4 = path.join(OUT, PORTRAIT ? 'pixie-demo-portrait.mp4' : 'pixie-demo.mp4');
    const capFile = path.join(OUT, 'captions.json');
    fs.writeFileSync(capFile, JSON.stringify(captions, null, 1));
    log(PORTRAIT ? 'converting to MP4 (portrait)…' : 'composing the 1920x1080 video…');
    const args = [path.join(__dirname, 'to_mp4.py'), webm, mp4, String(trim)];
    if (!PORTRAIT) args.push('--landscape', capFile);
    const conv = spawnSync(PYTHON, args, { stdio: 'inherit' });
    if (conv.status !== 0) throw new Error('MP4 conversion failed (the WebM is in demo/out/raw/)');
    log(`done: ${path.relative(ROOT, mp4)}`);
  } finally {
    if (browser) await browser.close();
    server.kill();
  }
}

main().catch((e) => { console.error('[demo] failed:', e.message); process.exit(1); });
