/**
 * Render smoke tests for the admin UI.
 *
 * These bundle the real JSX with esbuild and render it through
 * react-dom/server, then assert on the markup. That is not a substitute for
 * clicking around, but it does catch the class of mistake that a successful
 * `vite build` cannot: a typo'd prop, a variable referenced but never defined, a
 * crash on empty/missing data, `.map` on something that came back null.
 *
 * useEffect does not run during server rendering, so no fetch mocking is needed
 * — the data-loading components render their loading state and the presentation
 * components render whatever props we hand them.
 *
 *   node tests/render.test.mjs
 */
import { build } from 'esbuild';
import { writeFileSync, mkdtempSync, rmSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';
import { fileURLToPath } from 'url';
import { createRequire } from 'module';
import { dirname, resolve } from 'path';

const here = dirname(fileURLToPath(import.meta.url));
const webSrc = resolve(here, '..', 'web', 'src');

let passed = 0;
const failures = [];
function ok(name) { passed += 1; console.log(`ok    ${name}`); }
function fail(name, err) {
  failures.push(`${name}: ${err?.message || err}`);
  console.log(`FAIL  ${name}: ${err?.message || err}`);
}
function assert(cond, msg) { if (!cond) throw new Error(msg || 'assertion failed'); }
function has(html, needle, msg) {
  if (!html.includes(needle)) {
    throw new Error(`${msg || 'missing'}: expected to find ${JSON.stringify(needle)}`);
  }
}
function lacks(html, needle, msg) {
  if (html.includes(needle)) {
    throw new Error(`${msg || 'unexpected'}: found ${JSON.stringify(needle)}`);
  }
}

// The entry we hand to esbuild. It exports a render helper plus the components
// under test, so the assertions below stay in plain JS.
const ENTRY = `
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';

import Favicon from '${webSrc}/components/Favicon.jsx';
import SourcePanel from '${webSrc}/components/SourcePanel.jsx';
import LinkEditor from '${webSrc}/components/LinkEditor.jsx';
import AdminActivity from '${webSrc}/pages/AdminActivity.jsx';
import AtlasList from '${webSrc}/pages/AtlasList.jsx';
import Queue from '${webSrc}/pages/Queue.jsx';

export function render(el) { return renderToStaticMarkup(el); }
export function routed(el) {
  return renderToStaticMarkup(React.createElement(MemoryRouter, null, el));
}
export { React, Favicon, SourcePanel, LinkEditor, AdminActivity, AtlasList, Queue };
`;

async function bundle() {
  const dir = mkdtempSync(join(tmpdir(), 'atlas-render-'));
  const entry = join(dir, 'entry.jsx');
  // CJS, not ESM: react-dom/server is CommonJS and dynamically requires node
  // builtins ('stream'). Bundled into ESM those requires hit esbuild's interop
  // shim and throw "Dynamic require of \"stream\" is not supported".
  const out = join(dir, 'bundle.cjs');
  writeFileSync(entry, ENTRY);
  await build({
    entryPoints: [entry],
    bundle: true,
    outfile: out,
    format: 'cjs',
    platform: 'node',
    jsx: 'automatic',
    loader: { '.js': 'jsx' },
    logLevel: 'silent',
    absWorkingDir: resolve(here, '..'),
    // The entry lives in a temp dir, so bare specifiers ('react',
    // 'react-dom/server') can't be resolved by walking up from it. Point
    // esbuild at the workspace's hoisted node_modules explicitly.
    nodePaths: [resolve(here, '..', 'node_modules')],
  });
  return { dir, out };
}

// --- fixtures ---------------------------------------------------------------
const SOURCE_DETAIL_TWO = [
  {
    source: 'f95_zone', source_label: 'F95zone', id_col: 'f95_id', id: '93340',
    site_url: 'https://f95zone.to/threads/eternum.93340/',
    fields: [
      { field: 'f95_id', value: 93340 },
      { field: 'rating', value: 4.9 },
      { field: 'thread_updated', value: 1700000001 },
      { field: 'tags', value: 'a'.repeat(400) },
      { field: 'floating', value: null },
    ],
    row: {},
  },
  {
    source: 'lewdcorner', source_label: 'LewdCorner', id_col: 'lc_id', id: '555',
    site_url: 'https://lewdcorner.com/threads/eternum.555/',
    fields: [{ field: 'lc_id', value: 555 }, { field: 'tier', value: 'Gold' }],
    row: {},
  },
];

const LINKS = [
  {
    link_id: 1, kind: 'steam', label: 'Base game', ext_id: '1126320',
    url: 'https://store.steampowered.com/app/1126320/', entry_type: 'game',
    parent_kind: null, parent_link_id: null, parent_source_id: null,
    _store: true, _favicon_host: 'store.steampowered.com',
  },
  {
    link_id: 2, kind: 'steam', label: 'Season 2 DLC', ext_id: '1126321',
    url: 'https://store.steampowered.com/app/1126321/', entry_type: 'dlc',
    parent_kind: 'manual', parent_link_id: 1, parent_source_id: null,
    _store: true, _favicon_host: 'store.steampowered.com',
  },
  {
    link_id: 3, kind: 'gog', label: 'Artbook', ext_id: 'art', url: null,
    entry_type: 'dlc', parent_kind: 'f95_zone', parent_link_id: null,
    parent_source_id: '93340', _store: true, _favicon_host: 'www.gog.com',
  },
  {
    link_id: 4, kind: 'custom', label: 'Dev blog', ext_id: null,
    url: 'https://blog.example.com/', entry_type: 'game',
    parent_kind: null, parent_link_id: null, parent_source_id: null,
    _store: false, _favicon_host: 'blog.example.com',
  },
];

const PARENT_OPTIONS = {
  manual: [{ parent_kind: 'manual', link_id: 1, kind: 'steam', label: 'Base game', title: 'Base game' }],
  sources: [
    { parent_kind: 'f95_zone', id_col: 'f95_id', id: '93340', site_url: 'x' },
    { parent_kind: 'lewdcorner', id_col: 'lc_id', id: '555', site_url: 'y' },
  ],
};

async function main() {
  // react-router's MemoryRouter uses useLayoutEffect, which React warns about
  // under server rendering. It's harness noise, not a problem with the code
  // under test, so keep it out of the results.
  const realError = console.error;
  console.error = (...args) => {
    if (typeof args[0] === 'string' && args[0].includes('useLayoutEffect does nothing on the server')) return;
    realError(...args);
  };

  const { dir, out } = await bundle();
  const m = createRequire(import.meta.url)(out);
  const { React, render, routed } = m;
  const h = React.createElement;
  const test = (name, fn) => { try { fn(); ok(name); } catch (e) { fail(name, e); } };

  // ------------------------------------------------------------- Favicon
  test('Favicon renders an img for a known host', () => {
    const html = render(h(m.Favicon, { link: { kind: 'steam', url: 'https://store.steampowered.com/app/1/' } }));
    has(html, '<img', 'img tag');
    has(html, 'store.steampowered.com', 'host in the icon url');
    has(html, 'aria-hidden="true"', 'decorative icons must be hidden from AT');
  });

  test('Favicon renders nothing without a host', () => {
    const html = render(h(m.Favicon, { link: { kind: 'custom', url: null } }));
    assert(html === '', `expected empty output, got ${JSON.stringify(html)}`);
  });

  test('Favicon derives the host from a custom url', () => {
    const html = render(h(m.Favicon, { link: { kind: 'custom', url: 'https://blog.example.com/x' } }));
    has(html, 'blog.example.com', 'host from url');
  });

  test('Favicon survives a malformed url', () => {
    const html = render(h(m.Favicon, { link: { kind: 'custom', url: 'not a url' } }));
    assert(html === '', 'a malformed url must not produce a broken img');
  });

  // ---------------------------------------------------------- SourcePanel
  test('SourcePanel shows a switcher for two mapped sources', () => {
    const html = render(h(m.SourcePanel, { detail: SOURCE_DETAIL_TWO }));
    has(html, 'Mapped sources (2)', 'header with count');
    has(html, 'F95zone 93340', 'f95 switcher button');
    has(html, 'LewdCorner 555', 'lc switcher button');
    has(html, 'open thread', 'link out');
  });

  test('SourcePanel hides the switcher for a single source', () => {
    const html = render(h(m.SourcePanel, { detail: [SOURCE_DETAIL_TWO[0]] }));
    has(html, 'Mapped sources', 'header');
    lacks(html, 'Mapped sources (', 'no count when there is nothing to switch');
    lacks(html, 'LewdCorner 555', 'other source should not appear');
  });

  test('SourcePanel handles no mappings', () => {
    const html = render(h(m.SourcePanel, { detail: [] }));
    has(html, 'No source mappings', 'empty state');
  });

  test('SourcePanel handles undefined detail', () => {
    // A stale client or a partial response must not crash the modal.
    const html = render(h(m.SourcePanel, {}));
    has(html, 'No source mappings', 'empty state for undefined');
  });

  test('SourcePanel formats epochs as dates and collapses blobs', () => {
    const html = render(h(m.SourcePanel, { detail: SOURCE_DETAIL_TWO }));
    lacks(html, '1700000001', 'epoch should be rendered as a date, not a number');
    has(html, '<details', 'long blob should collapse');
    has(html, '400 chars', 'blob size hint');
  });

  test('SourcePanel renders a dash for null values', () => {
    const html = render(h(m.SourcePanel, { detail: SOURCE_DETAIL_TWO }));
    has(html, '—', 'null placeholder');
  });

  // ----------------------------------------------------------- LinkEditor
  test('LinkEditor separates games from DLC', () => {
    const html = render(h(m.LinkEditor, {
      atlasId: 2, links: LINKS, setLinks() {}, options: PARENT_OPTIONS,
      setOptions() {}, onError() {}, onNotice() {},
    }));
    has(html, 'Base game', 'game label');
    has(html, 'Season 2 DLC', 'dlc label');
    has(html, '>DLC<', 'DLC section heading or badge');
  });

  test('LinkEditor describes what a DLC is tied to', () => {
    const html = render(h(m.LinkEditor, {
      atlasId: 2, links: LINKS, setLinks() {}, options: PARENT_OPTIONS,
      setOptions() {}, onError() {}, onNotice() {},
    }));
    has(html, 'part of Base game', 'manual parent described by label');
    has(html, 'part of f95_zone 93340', 'source parent described');
  });

  test('LinkEditor shows the game/DLC badge only for store kinds', () => {
    const custom = LINKS.filter((l) => l.kind === 'custom');
    const html = render(h(m.LinkEditor, {
      atlasId: 2, links: custom, setLinks() {}, options: PARENT_OPTIONS,
      setOptions() {}, onError() {}, onNotice() {},
    }));
    has(html, 'Dev blog', 'custom link name');
    lacks(html, '>game<', 'a plain web page must not be typed');
  });

  test('LinkEditor renders favicons for links', () => {
    const html = render(h(m.LinkEditor, {
      atlasId: 2, links: LINKS, setLinks() {}, options: PARENT_OPTIONS,
      setOptions() {}, onError() {}, onNotice() {},
    }));
    has(html, 'store.steampowered.com.ico', 'steam favicon');
    has(html, 'blog.example.com.ico', 'custom favicon from url');
  });

  test('LinkEditor handles an empty link list', () => {
    const html = render(h(m.LinkEditor, {
      atlasId: 2, links: [], setLinks() {}, options: { manual: [], sources: [] },
      setOptions() {}, onError() {}, onNotice() {},
    }));
    has(html, 'No external links yet', 'empty state');
    has(html, 'Add link', 'add form still present');
  });

  test('LinkEditor survives missing options', () => {
    // parent-options can fail independently of the link list.
    const html = render(h(m.LinkEditor, {
      atlasId: 2, links: LINKS, setLinks() {}, options: {},
      setOptions() {}, onError() {}, onNotice() {},
    }));
    has(html, 'Base game', 'still renders the links');
  });

  test('LinkEditor names a DLC whose parent link is gone', () => {
    const orphan = [{ ...LINKS[1], parent_link_id: 999 }];
    const html = render(h(m.LinkEditor, {
      atlasId: 2, links: orphan, setLinks() {}, options: PARENT_OPTIONS,
      setOptions() {}, onError() {}, onNotice() {},
    }));
    has(html, 'part of a removed link', 'dangling parent is described, not crashed on');
  });

  test('LinkEditor labels an unparented DLC', () => {
    const un = [{ ...LINKS[1], parent_kind: null, parent_link_id: null }];
    const html = render(h(m.LinkEditor, {
      atlasId: 2, links: un, setLinks() {}, options: PARENT_OPTIONS,
      setOptions() {}, onError() {}, onNotice() {},
    }));
    has(html, 'unparented', 'unparented DLC');
  });

  // --------------------------------------------------------- whole pages
  test('AdminActivity renders its loading state', () => {
    const html = routed(h(m.AdminActivity));
    has(html, 'Admin activity', 'page title');
    has(html, 'Last 30 days', 'range selector');
  });

  test('AtlasList renders without data', () => {
    const html = routed(h(m.AtlasList));
    has(html, 'Games', 'page title');
    has(html, 'Add a game', 'create button (requirement 1)');
    has(html, 'paste an id', 'updated search placeholder');
  });

  test('Queue renders without data', () => {
    const html = routed(h(m.Queue));
    has(html, 'queue', 'page renders');
  });

  rmSync(dir, { recursive: true, force: true });
  console.error = realError;

  console.log(`\n${passed}/${passed + failures.length} passed`);
  if (failures.length) {
    console.log('\nfailures:');
    for (const f of failures) console.log(`  - ${f}`);
    process.exit(1);
  }
}

main().catch((err) => { console.error('\nsuite crashed:', err); process.exit(1); });
