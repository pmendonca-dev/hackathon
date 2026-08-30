import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const shell = await readFile(path.join(root, 'src', 'components', 'Shell.tsx'), 'utf8');
const css = await readFile(path.join(root, 'src', 'index.css'), 'utf8');

test('desktop navigation can collapse while the header keeps its left-to-right hierarchy', () => {
  assert.match(shell, /const \[sidebarCollapsed, setSidebarCollapsed\] = useState\(false\)/);
  assert.match(shell, /lg:grid-cols-\[76px_minmax\(0,1fr\)\]/);
  assert.match(shell, /aria-label=\{sidebarCollapsed \? 'Expand sidebar' : 'Collapse sidebar'\}/);

  const header = shell.slice(shell.indexOf('<header'), shell.indexOf('</header>'));
  assert.match(header, /className="flex w-full items-center justify-between gap-4"/);
  assert.match(header, /<div className="min-w-0">/);
  assert.match(header, /Reload/);
  assert.ok(header.indexOf('<div className="min-w-0">') < header.indexOf('Reload'));
});

test('the shell retains the indigo palette and collapse transitions', () => {
  assert.match(css, /--color-verify: #3E4FE0/);
  assert.match(css, /rgba\(62, 79, 224/);
  assert.match(css, /\.sidebar-brand-copy--collapsed/);
  assert.match(css, /\.sidebar-nav-item--collapsed/);
  assert.match(css, /\.sidebar-footer--collapsed/);
});
