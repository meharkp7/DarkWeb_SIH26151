/**
 * Standalone accessibility audit.
 *
 * Deliberately NOT part of the Playwright suite: `e2e/` and
 * `playwright.config.ts` belong to another agent, and this audit needs none of
 * their fixtures. It is a plain Node script so it can be run at any time with
 * nothing but a running API and dev server:
 *
 *   node e2e-axe/audit.mjs --base http://127.0.0.1:5173
 *
 * `playwright` and `axe-core` are resolved from the local `node_modules` when
 * they are there, and otherwise from `$AEGIS_A11Y_HARNESS` — a scratch install
 * kept outside the repo so this script can be run without adding anything to
 * `package.json`:
 *
 *   mkdir -p /tmp/aegis-a11y && cd /tmp/aegis-a11y
 *   npm i playwright axe-core
 *   AEGIS_A11Y_HARNESS=/tmp/aegis-a11y node e2e-axe/audit.mjs
 *
 * Every rule is enabled, `color-contrast` included: the palette is dark and
 * muted, which is exactly the case a colour-contrast pass is for.
 */

import { mkdir, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import process from 'node:process';

const HERE = dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);

/** Resolve a module from node_modules, falling back to the scratch harness. */
async function load(name) {
  try {
    return await import(name);
  } catch {
    const harness = process.env['AEGIS_A11Y_HARNESS'];
    if (!harness) {
      throw new Error(
        `${name} is not installed. Run \`npm i -D ${name}\`, or set ` +
          `AEGIS_A11Y_HARNESS to a directory whose node_modules has it.`,
      );
    }
    return import(pathToFileURL(resolve(harness, 'node_modules', name, 'index.js')).href);
  }
}

function arg(name, fallback) {
  const index = process.argv.indexOf(`--${name}`);
  return index !== -1 && process.argv[index + 1] !== undefined ? process.argv[index + 1] : fallback;
}

const BASE = arg('base', process.env['AEGIS_BASE_URL'] ?? 'http://127.0.0.1:5173');
const EMAIL = arg('email', process.env['AEGIS_EMAIL'] ?? 'analyst@aegis-intelligence.com');
const PASSWORD = arg('password', process.env['AEGIS_PASSWORD'] ?? 'AEGIS-Demo-2026!');
// `artifacts/` is gitignored, so the report lands outside version control
// without needing a new ignore rule.
const OUT = resolve(HERE, arg('out', '../../../artifacts/a11y'));
const VIEWPORT = { width: 1440, height: 900 };

/** Wait until the SPA has actually rendered something, not just loaded JS. */
async function settle(page, selector) {
  if (selector) await page.waitForSelector(selector, { timeout: 20000 });
  await page.waitForLoadState('networkidle', { timeout: 20000 }).catch(() => {});
  await page.waitForTimeout(600);
}

async function signIn(page) {
  await page.goto(`${BASE}/cases`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#corporate-email', { timeout: 20000 });
  await page.fill('#corporate-email', EMAIL);
  await page.fill('#corporate-password', PASSWORD);
  await page.click('button[type="submit"]');
  await page.waitForSelector('.app-shell', { timeout: 30000 });
  await page.waitForTimeout(1200);
}

async function main() {
  const { chromium } = await load('playwright');
  const axePath = require.resolve(
    process.env['AEGIS_A11Y_HARNESS']
      ? resolve(process.env['AEGIS_A11Y_HARNESS'], 'node_modules', 'axe-core')
      : 'axe-core',
  );
  const axeSource = await readFile(axePath, 'utf8');

  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: VIEWPORT, colorScheme: 'dark' });
  const page = await context.newPage();

  const consoleErrors = [];
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(`${page.url()} :: ${message.text()}`);
  });

  await mkdir(OUT, { recursive: true });
  await signIn(page);

  // A real case from the register, so the workspace tabs render data rather
  // than an empty shell — an empty state has almost no axe surface.
  const caseId = await page.evaluate(async () => {
    const read = (store) => store.getItem('aegis.session') ?? store.getItem('aegis.apiKey');
    const raw = read(window.sessionStorage) ?? read(window.localStorage) ?? '';
    let token = raw;
    try {
      const parsed = JSON.parse(raw);
      token = typeof parsed?.token === 'string' ? parsed.token : raw;
    } catch { /* a bare token, or no session at all */ }
    const response = await fetch('/api/v1/dashboard/cases', { headers: { Authorization: `Bearer ${token}` } });
    if (!response.ok) return null;
    const rows = await response.json();
    return rows?.[0]?.case_id ?? null;
  });
  if (caseId === null) throw new Error('No case available in the register; the workspace cannot be audited.');
  console.log(`  workspace case: ${caseId}`);

  const TABS = ['overview', 'evidence', 'network', 'timeline', 'assessment', 'notes'];
  const TARGETS = [
    { name: '/', path: '/', wait: '.app-main h1' },
    { name: '/cases', path: '/cases', wait: '.app-main h1' },
    { name: '/actors', path: '/actors', wait: '.app-main h1' },
    { name: '/infrastructure', path: '/infrastructure', wait: '.app-main h1' },
    { name: '/personas', path: '/personas', wait: '.app-main h1' },
    { name: '/threat-watch', path: '/threat-watch', wait: '.app-main h1' },
    { name: '/admin', path: '/admin', wait: '.app-main h1' },
    ...TABS.map((tab) => ({
      name: `/cases/:id?tab=${tab}`,
      path: tab === 'overview' ? `/cases/${caseId}` : `/cases/${caseId}?tab=${tab}`,
      wait: '.inv-tabpanel',
    })),
    // The surfaces that only exist behind a click: the command palette, a
    // register export popover and an open inspector rail. A route-only sweep
    // never sees them, and they are where the focus traps live.
    { name: 'command-palette', path: '/cases', wait: '.app-main h1', act: async (p) => {
      await p.keyboard.press('Meta+k');
      await p.waitForSelector('.pal-dialog', { timeout: 10000 });
      await p.waitForTimeout(400);
    } },
    { name: 'export-popover', path: '/cases', wait: '.app-main h1', act: async (p) => {
      await p.click('.exp-trigger');
      await p.waitForSelector('.exp-popover', { timeout: 10000 });
      await p.waitForTimeout(400);
    } },
    { name: 'global-search-open', path: '/actors', wait: '.app-main h1', act: async (p) => {
      await p.fill('.gsearch input', 'night');
      await p.waitForTimeout(1200);
    } },
  ];

  const results = [];
  for (const target of TARGETS) {
    await page.goto(`${BASE}${target.path}`, { waitUntil: 'domcontentloaded' });
    await settle(page, target.wait);
    if (target.act) await target.act(page);

    const result = await page.evaluate(async (source) => {
      // eslint-disable-next-line no-eval
      window.eval(source);
      // No `runOnly`: axe defaults to every rule it ships, which is what this
      // audit is for. Narrowing to a tag list is how `color-contrast` gets
      // quietly dropped from an accessibility report.
      return window.axe.run(document, {
        resultTypes: ['violations', 'incomplete'],
      });
    }, axeSource);

    results.push({ name: target.name, violations: result.violations, incomplete: result.incomplete });
    process.stdout.write(`  scanned ${target.name} — ${result.violations.length} violation rule(s)\n`);
  }

  const report = buildReport(results);
  await writeFile(resolve(OUT, 'axe-report.json'), JSON.stringify(report, null, 2), 'utf8');
  console.log(printReport(report));

  if (consoleErrors.length > 0) {
    console.log('\nConsole errors observed during the sweep:');
    for (const line of [...new Set(consoleErrors)]) console.log(`  ${line}`);
  }

  await browser.close();
  process.exit(report.totalViolations > 0 ? 1 : 0);
}

async function readFile(path, encoding) {
  const { readFile: read } = await import('node:fs/promises');
  return read(path, encoding);
}

function buildReport(results) {
  const byRule = new Map();
  for (const { name, violations } of results) {
    for (const violation of violations) {
      const entry = byRule.get(violation.id) ?? {
        id: violation.id,
        impact: violation.impact,
        help: violation.help,
        helpUrl: violation.helpUrl,
        description: violation.description,
        tags: violation.tags,
        occurrences: 0,
        routes: new Map(),
        selectors: new Map(),
      };
      entry.occurrences += violation.nodes.length;
      const route = entry.routes.get(name) ?? { route: name, nodes: 0, selectors: [] };
      route.nodes += violation.nodes.length;
      for (const node of violation.nodes) {
        const selector = node.target.join(' ');
        if (!route.selectors.includes(selector)) route.selectors.push(selector);
        const detail = entry.selectors.get(selector) ?? { selector, samples: [], routes: new Set() };
        if (detail.samples.length < 3) {
          detail.samples.push({
            route: name,
            html: node.html.slice(0, 300),
            summary: node.failureSummary ?? '',
          });
        }
        detail.routes.add(name);
        entry.selectors.set(selector, detail);
      }
      entry.routes.set(name, route);
      byRule.set(violation.id, entry);
    }
  }

  const rules = [...byRule.values()]
    .map((entry) => ({
      ...entry,
      routes: [...entry.routes.values()],
      selectors: [...entry.selectors.values()].map((s) => ({
        ...s,
        routes: [...s.routes],
      })),
    }))
    .sort((a, b) => b.occurrences - a.occurrences || a.id.localeCompare(b.id));

  return {
    generatedAt: new Date().toISOString(),
    base: BASE,
    routesScanned: results.map((r) => r.name),
    totalViolations: rules.reduce((sum, rule) => sum + rule.occurrences, 0),
    ruleCount: rules.length,
    rules,
    incomplete: results
      .filter((r) => r.incomplete.length > 0)
      .map((r) => ({ route: r.name, rules: r.incomplete.map((i) => i.id) })),
  };
}

function printReport(report) {
  const lines = [];
  lines.push('');
  lines.push('='.repeat(78));
  lines.push(`AEGIS accessibility audit — ${report.generatedAt}`);
  lines.push(`routes scanned : ${report.routesScanned.length}`);
  lines.push(`rules violated : ${report.ruleCount}`);
  lines.push(`violations     : ${report.totalViolations}`);
  lines.push('='.repeat(78));
  for (const rule of report.rules) {
    lines.push('');
    lines.push(`[${rule.impact ?? 'unknown'}] ${rule.id} — ${rule.help}  (${rule.occurrences})`);
    lines.push(`  ${rule.helpUrl}`);
    for (const selector of rule.selectors) {
      lines.push(`  ✗ ${selector.selector}   [${selector.routes.length} route(s)]`);
      for (const sample of selector.samples) {
        lines.push(`      ${sample.route}: ${sample.summary.replace(/\s+/g, ' ').split('Fix any of the following:')[1]?.trim() ?? ''}`);
        lines.push(`        html: ${sample.html}`);
      }
    }
  }
  return lines.join('\n');
}

main().catch((error) => {
  console.error(error);
  process.exit(2);
});
