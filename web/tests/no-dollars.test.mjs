/* The studio shows CREDITS, never dollars (2026-10-08,
   docs/tasks/task-metering-and-credits.md part 2). Dollars stay on the
   operator's dev pages (/costs, the Dev Studio) and on the public plan
   prices -- neither lives under these folders. Dollars survived in three
   fallbacks ("~$" when a quote had no credits) long after credits were the
   rule, so this reads the source rather than trusting a reviewer to spot
   the next one. */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const ROOTS = [
  'src/app/studio',
  'src/components/studio',
  'src/components/flows',
  'src/components/cut',
  'src/lib/render-choice.ts',
  '../app/static/zpf/queue.js', // the legacy /ui Queue: it can still approve
];
// what formatting a price in dollars looks like in this codebase
const PATTERNS = [
  [/~\$/, '"~$" (an approximate dollar price)'],
  [/\$\$\{/, '"$${" (a dollar sign before an interpolated number)'],
  [/est\. \$/, '"est. $"'],
  [/(usd|estimate_usd)\)?\.toFixed\(/, 'a USD value formatted with toFixed'],
  [/['"]\$['"]\s*\+/, '"$" + a number'],
];

function* files(path) {
  const st = statSync(path);
  if (st.isFile()) {
    if (/\.(tsx?|m?js)$/.test(path)) yield path;
    return;
  }
  for (const name of readdirSync(path)) yield* files(join(path, name));
}

test('no studio page or component formats a price in dollars', () => {
  const hits = [];
  for (const root of ROOTS) {
    for (const file of files(join(WEB, root))) {
      readFileSync(file, 'utf8')
        .split('\n')
        .forEach((line, i) => {
          for (const [re, what] of PATTERNS) {
            if (re.test(line)) hits.push(`${relative(WEB, file)}:${i + 1}  ${what}\n    ${line.trim()}`);
          }
        });
    }
  }
  assert.deepEqual(hits, [], `credits, never dollars:\n${hits.join('\n')}`);
});

test('the guard would catch the fallbacks it was written for', () => {
  // the three shapes that shipped before 2026-10-08, so a pattern that
  // stops matching them fails here rather than passing everything
  const shipped = [
    '${charge ?? `~$${Number(r.estimate_usd).toFixed(2)}`}',
    '? `est. $${Number(rw.estimate_usd).toFixed(2)}`',
    ": usd === null || usd === undefined ? 'unpriced' : '~$' + usd.toFixed(2)}`;",
  ];
  for (const line of shipped) assert.ok(PATTERNS.some(([re]) => re.test(line)), line);
});
