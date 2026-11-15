// Smoke test for /stage on the pretend band: opens it at laptop size, runs a few scenes, saves screenshots.
const { chromium } = require('playwright');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');
const ROOT = path.resolve(__dirname, '..');
const OUT = path.join(__dirname, 'out');
const PORT = 8781;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  fs.rmSync(path.join(ROOT, 'data-sim'), { recursive: true, force: true });
  const server = spawn(process.env.PIXIE_PYTHON || 'python', ['-u', 'server.py', '--sim', '--port', String(PORT)], { cwd: ROOT });
  const browser = await chromium.launch({ channel: 'msedge' });
  try {
    for (let i = 0; i < 40; i++) { try { if ((await fetch(`http://127.0.0.1:${PORT}/stage`)).ok) break; } catch {} await sleep(500); }
    const page = await browser.newPage({ viewport: { width: 1536, height: 864 } });
    const errors = [];
    page.on('pageerror', (e) => errors.push(e.message));
    await page.goto(`http://127.0.0.1:${PORT}/stage`);
    await page.waitForFunction(() => document.getElementById('status').textContent.includes('connected'), null, { timeout: 30000 });
    await sleep(1500);
    await page.screenshot({ path: path.join(OUT, 'stage-1-calm.png') });
    await page.keyboard.press('1'); await sleep(2500);
    await page.screenshot({ path: path.join(OUT, 'stage-2-worrying.png') });
    await page.keyboard.press('8'); await sleep(3000);
    await page.screenshot({ path: path.join(OUT, 'stage-3-card.png') });
    await page.keyboard.press('0'); await sleep(6000);
    await page.screenshot({ path: path.join(OUT, 'stage-4-patterns.png') });
    await page.keyboard.press('Escape'); await sleep(1000);
    await page.keyboard.press('h'); await sleep(2500);
    await page.screenshot({ path: path.join(OUT, 'stage-5-help.png') });
    console.log(errors.length ? 'page errors: ' + errors.join(' | ') : 'no page errors');
  } finally { await browser.close(); server.kill(); }
})();
