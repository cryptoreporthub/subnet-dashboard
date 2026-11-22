// Autopsy chip in the living-focus panel (#1578 postmortems).
// Drives the real static/js/living_focus.js in headless Chromium with the
// stored postmortem shape, and asserts the text a user sees for a focused subnet.
// Run: node tests/js/living_focus_autopsy.test.js

const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const ROOT = path.join(__dirname, '..', '..');
const SCRIPT = fs.readFileSync(path.join(ROOT, 'static', 'js', 'living_focus.js'), 'utf8');

const IDS = [
  'habit-pin-btn', 'inv-netuid', 'inv-sellers-btn', 'living-focus-body',
  'living-focus-cta', 'living-focus-evidence', 'living-focus-identity-chip',
  'living-focus-learn', 'living-focus-pin-btn', 'living-focus-prove-btn',
  'living-focus-share-link', 'living-focus-status-chip', 'living-focus-sub',
  'living-focus-switcher', 'living-focus-trail-teaser', 'living-focus-weights',
  'market-drawer', 'section-investigation', 'section-living-focus',
];

// Shape copied from GET /api/postmortems on the deployed app: top-level netuid,
// answers under questions, no prediction/lesson keys.
function record(judge, createdAt, what) {
  return {
    judge,
    prediction_id: `pred-${judge}`,
    netuid: 31,
    name: 'SN31',
    direction: 'up',
    predicted_pct: 2.0,
    actual_pct: 0.4436,
    signal_source: 'momentum',
    created_at: createdAt,
    questions: {
      what,
      why: 'canned',
      rule: 'canned',
      devil: 'canned',
    },
  };
}

// Oracle's entry is older than echo's, so the chip must show echo's.
const FIXTURE = {
  postmortems: {
    oracle: [record('oracle', '2026-11-20T09:00:00Z', 'Oracle old text.')],
    echo: [record('echo', '2026-11-22T01:33:50Z', 'Magnitude was wrong: the move was much smaller than predicted.')],
    pulse: [],
  },
};

// Minimal judge payload so the panel hydrates and the evidence enrichment runs.
const JUDGES = { netuid: 31, consensus: { action: 'HOLD', score: 0.5 }, judges: [] };

async function run() {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  const pageErrors = [];
  page.on('pageerror', (e) => pageErrors.push(e.message));
  // Serve the page from an http origin so relative /api/ fetches reach the route.
  const ORIGIN = 'http://fixture.test';
  const body = IDS.map((id) => `<div id="${id}"></div>`).join('');
  const html = `<!doctype html><html><body>${body}</body></html>`;
  await page.route(`${ORIGIN}/**`, (route) => {
    const url = route.request().url();
    if (url.includes('/api/postmortems')) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(FIXTURE) });
    }
    if (url.includes('/api/judges/')) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(JUDGES) });
    }
    if (url.includes('/api/')) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: '{}' });
    }
    return route.fulfill({ status: 200, contentType: 'text/html', body: html });
  });
  await page.goto(ORIGIN + '/');
  await page.addScriptTag({ content: SCRIPT });
  await page.evaluate(() => window.LivingFocus.setFocus(31, 'SN31'));
  await page.evaluate(() => window.LivingFocus.refresh());
  await page.waitForFunction(() => {
    const el = document.getElementById('living-focus-evidence');
    return el && el.textContent.includes('Evidence desk');
  }, null, { timeout: 15000 }).catch(() => {});
  const evidence = await page.textContent('#living-focus-evidence');
  if (pageErrors.length) console.error('page errors: ' + pageErrors.join(' | '));
  await browser.close();

  const failures = [];
  if (!evidence.includes('Autopsy')) failures.push('no Autopsy chip rendered');
  if (!evidence.includes('Echo')) failures.push('chip did not use the newest judge entry (echo)');
  if (!evidence.includes('Magnitude was wrong')) failures.push('chip text is not the stored questions.what');
  if (evidence.includes('Oracle old text')) failures.push('chip showed the older oracle entry');

  if (failures.length) {
    console.error('FAIL living_focus autopsy chip:\n  - ' + failures.join('\n  - '));
    console.error('evidence panel text: ' + JSON.stringify(evidence));
    process.exit(1);
  }
  console.log('PASS living_focus autopsy chip');
}

run().catch((err) => {
  console.error(err);
  process.exit(1);
});
