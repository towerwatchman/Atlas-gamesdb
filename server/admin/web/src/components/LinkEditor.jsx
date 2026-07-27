import React, { useState } from 'react';
import { api } from '../lib/api.js';
import Favicon from './Favicon.jsx';

const KINDS = [
  { value: 'steam', label: 'Steam' },
  { value: 'gog', label: 'GOG' },
  { value: 'itch', label: 'itch.io' },
  { value: 'custom', label: 'Custom' },
];
const STORE_KINDS = new Set(['steam', 'gog', 'itch']);
const KIND_LABEL = Object.fromEntries(KINDS.map((k) => [k.value, k.label]));

// Human description of what a DLC is tied to.
function parentText(link, links) {
  if (link.entry_type !== 'dlc') return null;
  if (!link.parent_kind) return 'unparented';
  if (link.parent_kind === 'manual') {
    const p = links.find((x) => x.link_id === link.parent_link_id);
    return p ? `part of ${p.label || KIND_LABEL[p.kind] || p.kind}` : 'part of a removed link';
  }
  return `part of ${link.parent_kind} ${link.parent_source_id}`;
}

function ParentPicker({ options, value, onChange }) {
  // One flat dropdown over both parent flavours, encoded as "kind:id", because a
  // DLC can hang off either a manual link or a source mapping and asking the
  // admin to first pick a category would be a pointless extra step.
  const items = [
    ...(options.manual || []).map((m) => ({
      key: `manual:${m.link_id}`, label: `${KIND_LABEL[m.kind] || m.kind} — ${m.title}`,
    })),
    ...(options.sources || []).map((s) => ({
      key: `${s.parent_kind}:${s.id}`, label: `${s.parent_kind} ${s.id}`,
    })),
  ];
  return (
    <select style={{ width: 'auto', maxWidth: 260 }} value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">Belongs to… (optional)</option>
      {items.map((i) => <option key={i.key} value={i.key}>{i.label}</option>)}
    </select>
  );
}

function decodeParent(encoded) {
  if (!encoded) return { parentKind: null, parentLinkId: null, parentSourceId: null };
  const [kind, id] = encoded.split(':');
  if (kind === 'manual') return { parentKind: 'manual', parentLinkId: Number(id) };
  return { parentKind: kind, parentSourceId: id };
}

function encodeParent(link) {
  if (!link.parent_kind) return '';
  return link.parent_kind === 'manual'
    ? `manual:${link.parent_link_id}`
    : `${link.parent_kind}:${link.parent_source_id}`;
}

/**
 * The scraper's own external_ids, rendered as links (read-only).
 *
 * These live in atlas.external_ids, a JSON blob the scraper rewrites in full on
 * every refresh — so they can't be edited here; anything typed would vanish on
 * the next crawl. To pin something permanently, add it as a manual link below,
 * which the scraper never touches.
 */
function ScrapedLinks({ links }) {
  if (!links || !links.length) return null;
  return (
    <div style={{ marginBottom: 12 }}>
      <div className="row" style={{ gap: 8, alignItems: 'baseline', marginBottom: 6 }}>
        <span className="hint" style={{ fontWeight: 600 }}>From the scraper</span>
        <span className="hint">
          read-only — rewritten on every refresh
        </span>
      </div>
      <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
        {links.map((l) => {
          const inner = (
            <>
              <Favicon host={l.favicon_host} size={14} />
              <span>{l.label}</span>
              <span className="mono" style={{ opacity: 0.75 }}>{l.value}</span>
            </>
          );
          return l.url ? (
            <a
              key={`${l.key}-${l.value}`}
              className="badge badge-ext row"
              style={{ gap: 6, alignItems: 'center' }}
              href={l.url}
              target="_blank"
              rel="noreferrer"
              title={l.url}
            >
              {inner}
              <span aria-hidden="true">↗</span>
            </a>
          ) : (
            <span
              key={`${l.key}-${l.value}`}
              className="badge badge-ext row"
              style={{ gap: 6, alignItems: 'center' }}
              title={l.known ? 'No public URL can be built from this id alone' : 'Unrecognised key'}
            >
              {inner}
            </span>
          );
        })}
      </div>
    </div>
  );
}

function LinkRow({ atlasId, link, links, options, onChanged, onRemoved, onError }) {
  const [editing, setEditing] = useState(false);
  const [label, setLabel] = useState(link.label || '');
  const [entryType, setEntryType] = useState(link.entry_type || 'game');
  const [parent, setParent] = useState(encodeParent(link));
  const [busy, setBusy] = useState(false);
  const isStore = STORE_KINDS.has(link.kind);
  const name = link.label || KIND_LABEL[link.kind] || link.kind;
  const tie = parentText(link, links);

  async function save() {
    onError(''); setBusy(true);
    try {
      const body = { label: label.trim(), entryType, ...decodeParent(entryType === 'dlc' ? parent : '') };
      onChanged(await api.patch(`/api/atlas/${atlasId}/manual-links/${link.link_id}`, body));
      setEditing(false);
    } catch (e) { onError(e.message); } finally { setBusy(false); }
  }

  async function remove() {
    onError('');
    try {
      const res = await api.del(`/api/atlas/${atlasId}/manual-links/${link.link_id}`);
      onRemoved(link, res.orphaned);
    } catch (e) { onError(e.message); }
  }

  return (
    <div className="panel panel-pad" style={{ padding: '8px 10px', marginBottom: 6, background: 'var(--panel)' }}>
      <div className="row" style={{ gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <Favicon link={link} />
        {link.url
          ? <a href={link.url} target="_blank" rel="noreferrer" title={link.url}>{name}</a>
          : <span>{name}</span>}
        {link.ext_id && <span className="mono hint">{link.ext_id}</span>}
        {isStore && (
          <span className={`badge ${link.entry_type === 'dlc' ? 'badge-ext' : 'badge-edited'}`}>
            {link.entry_type === 'dlc' ? 'DLC' : 'game'}
          </span>
        )}
        {tie && <span className="hint">{tie}</span>}
        <span style={{ marginLeft: 'auto' }} className="row">
          {isStore && (
            <button className="btn btn-sm" onClick={() => setEditing(!editing)}>
              {editing ? 'Close' : 'Edit'}
            </button>
          )}
          <button className="btn btn-sm" onClick={remove}>Remove</button>
        </span>
      </div>

      {editing && (
        <div className="row" style={{ gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
          <input
            placeholder="Label (e.g. Base game, Season 2 DLC)"
            value={label} onChange={(e) => setLabel(e.target.value)}
            style={{ flex: '1 1 180px' }}
          />
          <select style={{ width: 'auto' }} value={entryType} onChange={(e) => setEntryType(e.target.value)}>
            <option value="game">Game</option>
            <option value="dlc">DLC</option>
          </select>
          {entryType === 'dlc' && (
            <ParentPicker options={options} value={parent} onChange={setParent} />
          )}
          <button className="btn btn-sm btn-primary" onClick={save} disabled={busy}>
            {busy ? 'Saving…' : 'Save'}
          </button>
        </div>
      )}
    </div>
  );
}

/**
 * External-links editor (issues #285 / #278).
 *
 * Admin-only links stored apart from scraped data, so a re-scrape never
 * overwrites them. Store kinds (Steam / GOG / itch.io) additionally carry a
 * label, a game/DLC type, and — for a DLC — the mapping it belongs to. `custom`
 * links are plain web pages, so they get a name and nothing else.
 */
export default function LinkEditor({
  atlasId, links, setLinks, options, setOptions, onError, onNotice, scrapedLinks,
}) {
  const [kind, setKind] = useState('steam');
  const [label, setLabel] = useState('');
  const [extId, setExtId] = useState('');
  const [url, setUrl] = useState('');
  const [entryType, setEntryType] = useState('game');
  const [parent, setParent] = useState('');
  const [busy, setBusy] = useState(false);
  const isStore = STORE_KINDS.has(kind);

  async function refreshOptions() {
    try {
      setOptions(await api.get(`/api/atlas/${atlasId}/manual-links/parent-options`));
    } catch { /* the picker just stays as it was */ }
  }

  async function add() {
    onError('');
    if (!extId.trim() && !url.trim()) { onError('Provide an ID, a URL, or both.'); return; }
    setBusy(true);
    try {
      const created = await api.post(`/api/atlas/${atlasId}/manual-links`, {
        kind,
        label: label.trim() || undefined,
        extId: extId.trim() || undefined,
        url: url.trim() || undefined,
        entryType: isStore ? entryType : 'game',
        ...(isStore && entryType === 'dlc' ? decodeParent(parent) : {}),
      });
      setLinks([created, ...links]);
      setLabel(''); setExtId(''); setUrl(''); setParent('');
      await refreshOptions();
    } catch (e) { onError(e.message); } finally { setBusy(false); }
  }

  const games = links.filter((l) => l.entry_type !== 'dlc');
  const dlc = links.filter((l) => l.entry_type === 'dlc');

  function onChanged(updated) {
    setLinks(links.map((l) => (l.link_id === updated.link_id ? { ...l, ...updated } : l)));
    refreshOptions();
  }
  function onRemoved(removed, orphaned) {
    setLinks(links
      .filter((l) => l.link_id !== removed.link_id)
      // The server clears the FK rather than cascading, so mirror that locally.
      .map((l) => (l.parent_link_id === removed.link_id
        ? { ...l, parent_kind: null, parent_link_id: null } : l)));
    if (orphaned > 0 && onNotice) {
      onNotice(`Removed. ${orphaned} DLC entr${orphaned === 1 ? 'y is' : 'ies are'} now unparented.`);
    }
    refreshOptions();
  }

  const rowProps = { atlasId, links, options, onChanged, onRemoved, onError };

  return (
    <div className="panel panel-pad" style={{ marginTop: 12, background: 'var(--panel-2)' }}>
      <h3 style={{ fontSize: 14, margin: '0 0 4px', color: 'var(--muted)' }}>External links</h3>

      <ScrapedLinks links={scrapedLinks} />

      <div className="row" style={{ gap: 8, alignItems: 'baseline', marginBottom: 4 }}>
        <span className="hint" style={{ fontWeight: 600 }}>Admin links</span>
      </div>
      <p className="hint" style={{ marginBottom: 10 }}>
        Steam, GOG, itch.io or custom links. Stored separately from scraped data, so
        they survive re-scrapes. Store links can be labelled and marked as a game or
        a DLC; a DLC can be tied to another link or to a source mapping.
      </p>

      {games.length > 0 && games.map((l) => <LinkRow key={l.link_id} link={l} {...rowProps} />)}
      {dlc.length > 0 && (
        <>
          <div className="hint" style={{ margin: '8px 0 4px' }}>DLC</div>
          {dlc.map((l) => <LinkRow key={l.link_id} link={l} {...rowProps} />)}
        </>
      )}
      {links.length === 0 && <p className="hint">No admin links yet.</p>}

      <div className="ext-add" style={{ marginTop: 10 }}>
        <select style={{ width: 'auto' }} value={kind} onChange={(e) => setKind(e.target.value)}>
          {KINDS.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}
        </select>
        <input
          placeholder={isStore ? 'Label (optional)' : 'Label (e.g. Patreon)'}
          value={label} onChange={(e) => setLabel(e.target.value)} style={{ flex: '1 1 130px' }}
        />
        <input placeholder="ID (optional)" value={extId} onChange={(e) => setExtId(e.target.value)} style={{ flex: '1 1 100px' }} />
        <input placeholder="https:// URL (optional)" value={url} onChange={(e) => setUrl(e.target.value)} style={{ flex: '2 1 180px' }} />
        {isStore && (
          <select style={{ width: 'auto' }} value={entryType} onChange={(e) => setEntryType(e.target.value)}>
            <option value="game">Game</option>
            <option value="dlc">DLC</option>
          </select>
        )}
        {isStore && entryType === 'dlc' && (
          <ParentPicker options={options} value={parent} onChange={setParent} />
        )}
        <button className="btn btn-sm btn-primary" onClick={add} disabled={busy || (!extId.trim() && !url.trim())}>
          {busy ? 'Adding…' : 'Add link'}
        </button>
      </div>
    </div>
  );
}
