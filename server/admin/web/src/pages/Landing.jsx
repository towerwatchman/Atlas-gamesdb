import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import './landing.css';

// Public landing page. Ported from the original static index.html, now the
// "/" route of the React app. Styling is scoped under .landing-page so it never
// touches the admin UI. The Admin link routes to the login-gated /admin area.
export default function Landing() {
  const [version, setVersion] = useState('latest');

  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const res = await fetch(
          'https://api.github.com/repos/towerwatchman/atlas/releases/latest',
          { headers: { Accept: 'application/vnd.github+json' } });
        if (res.ok) {
          const data = await res.json();
          if (live && data && data.tag_name) { setVersion(data.tag_name); return; }
        }
        if (live) setVersion('GitHub');
      } catch {
        if (live) setVersion('GitHub');
      }
    })();
    return () => { live = false; };
  }, []);

  return (
    <div className="landing-page">
      <nav>
        <div className="brand">
          <img src="/atlas_logo.png" alt="Atlas logo" />
          <span>Atlas</span>
        </div>
        <div className="nav-right">
          <a className="version-tag" id="version-tag"
            href="https://github.com/towerwatchman/atlas/releases/latest">
            <span className="dot"></span><span id="version-text">{version}</span>
          </a>
          <Link className="admin-link" to="/admin">Admin</Link>
        </div>
      </nav>

      <header>
        <svg className="starfield" viewBox="0 0 1080 620" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
          <defs>
            <radialGradient id="glow" cx="50%" cy="40%" r="60%">
              <stop offset="0%" stopColor="#2ba3c7" stopOpacity="0.20" />
              <stop offset="100%" stopColor="#2ba3c7" stopOpacity="0" />
            </radialGradient>
          </defs>
          <rect width="1080" height="620" fill="url(#glow)" />

          <g transform="translate(0,150)">
            <g className="backset-rotate">
              <g className="backset-pan" fill="#232b33">
                <circle cx="120" cy="40" r="0.8" /><circle cx="300" cy="120" r="0.7" /><circle cx="470" cy="30" r="0.8" />
                <circle cx="560" cy="180" r="0.6" /><circle cx="700" cy="70" r="0.8" /><circle cx="820" cy="150" r="0.7" />
                <circle cx="980" cy="50" r="0.8" /><circle cx="1050" cy="140" r="0.6" /><circle cx="60" cy="180" r="0.7" />
                <circle cx="380" cy="220" r="0.6" /><circle cx="640" cy="210" r="0.7" /><circle cx="900" cy="220" r="0.6" />
                <circle cx="200" cy="90" r="0.7" /><circle cx="1180" cy="60" r="0.8" /><circle cx="1360" cy="140" r="0.7" />
                <circle cx="1520" cy="40" r="0.8" /><circle cx="1640" cy="190" r="0.6" /><circle cx="1780" cy="80" r="0.8" />
                <circle cx="1900" cy="160" r="0.7" /><circle cx="2060" cy="50" r="0.8" /><circle cx="2130" cy="150" r="0.6" />
                <circle cx="1280" cy="210" r="0.6" /><circle cx="1720" cy="220" r="0.7" /><circle cx="1980" cy="210" r="0.6" />
                <circle cx="1450" cy="95" r="0.7" />
              </g>
            </g>

            <g className="sky-rotate"><g className="sky-pan">
              <g className="layer-back" fill="#2e3742">
                <circle cx="60" cy="70" r="1" /><circle cx="150" cy="140" r="0.9" /><circle cx="240" cy="55" r="1" />
                <circle cx="330" cy="200" r="0.8" /><circle cx="420" cy="95" r="1" /><circle cx="510" cy="250" r="0.9" />
                <circle cx="600" cy="120" r="1" /><circle cx="690" cy="60" r="0.8" /><circle cx="780" cy="210" r="1" />
                <circle cx="870" cy="100" r="0.9" /><circle cx="960" cy="180" r="1" /><circle cx="1030" cy="90" r="0.8" />
                <circle cx="110" cy="270" r="0.9" /><circle cx="380" cy="290" r="0.8" /><circle cx="640" cy="290" r="0.9" />
                <circle cx="900" cy="270" r="0.8" /><circle cx="200" cy="230" r="0.9" /><circle cx="720" cy="150" r="0.9" />
                <circle cx="1140" cy="80" r="1" /><circle cx="1230" cy="170" r="0.9" /><circle cx="1320" cy="60" r="1" />
                <circle cx="1410" cy="220" r="0.8" /><circle cx="1500" cy="110" r="1" /><circle cx="1590" cy="260" r="0.9" />
                <circle cx="1680" cy="90" r="1" /><circle cx="1770" cy="180" r="0.8" /><circle cx="1860" cy="70" r="1" />
                <circle cx="1950" cy="210" r="0.9" /><circle cx="2040" cy="120" r="1" /><circle cx="2130" cy="60" r="0.8" />
                <circle cx="1200" cy="280" r="0.9" /><circle cx="1500" cy="290" r="0.8" /><circle cx="1800" cy="270" r="0.9" />
                <circle cx="2080" cy="250" r="0.8" /><circle cx="1650" cy="150" r="0.9" />
              </g>

              <g className="layer-mid" fill="#4a5763">
                <circle cx="90" cy="90" r="1.6" /><circle cx="240" cy="60" r="1.8" /><circle cx="430" cy="80" r="1.5" />
                <circle cx="640" cy="55" r="1.7" /><circle cx="860" cy="90" r="1.6" /><circle cx="1010" cy="70" r="1.5" />
                <circle cx="360" cy="160" r="1.6" /><circle cx="560" cy="140" r="1.5" /><circle cx="720" cy="150" r="1.6" />
                <circle cx="500" cy="210" r="1.4" /><circle cx="720" cy="230" r="1.5" /><circle cx="900" cy="200" r="1.4" />
                <circle cx="150" cy="200" r="1.4" />
                <circle cx="1150" cy="100" r="1.6" /><circle cx="1320" cy="70" r="1.8" /><circle cx="1500" cy="120" r="1.5" />
                <circle cx="1700" cy="90" r="1.7" /><circle cx="1420" cy="190" r="1.6" /><circle cx="1620" cy="160" r="1.5" />
                <circle cx="1800" cy="200" r="1.6" /><circle cx="1980" cy="180" r="1.5" /><circle cx="2100" cy="80" r="1.6" />
                <circle cx="1560" cy="250" r="1.4" /><circle cx="1860" cy="70" r="1.5" />
              </g>

              <g className="twinkle" fill="#7fd3ea">
                <circle cx="240" cy="60" r="1.9"><animate attributeName="opacity" values="0.3;1;0.3" dur="4s" repeatCount="indefinite" /></circle>
                <circle cx="640" cy="55" r="1.8"><animate attributeName="opacity" values="1;0.35;1" dur="5.5s" repeatCount="indefinite" /></circle>
                <circle cx="360" cy="160" r="1.7"><animate attributeName="opacity" values="0.4;1;0.4" dur="6.5s" repeatCount="indefinite" /></circle>
                <circle cx="900" cy="200" r="1.6"><animate attributeName="opacity" values="1;0.3;1" dur="4.8s" repeatCount="indefinite" /></circle>
                <circle cx="1320" cy="70" r="1.8"><animate attributeName="opacity" values="0.35;1;0.35" dur="7s" repeatCount="indefinite" /></circle>
                <circle cx="1700" cy="90" r="1.7"><animate attributeName="opacity" values="1;0.4;1" dur="5s" repeatCount="indefinite" /></circle>
                <circle cx="1980" cy="180" r="1.6"><animate attributeName="opacity" values="0.4;1;0.4" dur="6s" repeatCount="indefinite" /></circle>
                <circle cx="1420" cy="190" r="1.6"><animate attributeName="opacity" values="1;0.35;1" dur="5.8s" repeatCount="indefinite" /></circle>
              </g>
            </g></g>
          </g>
        </svg>

        <div className="hero-inner wrap">
          <div className="eyebrow">Open source &middot; Electron</div>
          <h1>One library for<br />your entire collection</h1>
          <p className="lede">Atlas brings every game and visual novel into a single, beautifully organized launcher &mdash; metadata, artwork, and versions, all local and all yours.</p>
          <div className="cta-row">
            <a className="btn btn-primary" href="https://github.com/towerwatchman/atlas/releases/latest">Download for Windows or Linux</a>
            <a className="btn btn-ghost" href="https://github.com/towerwatchman/atlas">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C6.48 2 2 6.58 2 12.25c0 4.53 2.87 8.37 6.84 9.73.5.09.68-.22.68-.49 0-.24-.01-.87-.01-1.71-2.78.62-3.37-1.37-3.37-1.37-.45-1.18-1.11-1.49-1.11-1.49-.91-.64.07-.62.07-.62 1 .07 1.53 1.06 1.53 1.06.89 1.56 2.34 1.11 2.91.85.09-.66.35-1.11.63-1.37-2.22-.26-4.56-1.14-4.56-5.06 0-1.12.39-2.03 1.03-2.75-.1-.26-.45-1.3.1-2.71 0 0 .84-.28 2.75 1.05a9.36 9.36 0 0 1 5 0c1.91-1.33 2.75-1.05 2.75-1.05.55 1.41.2 2.45.1 2.71.64.72 1.03 1.63 1.03 2.75 0 3.93-2.35 4.8-4.58 5.05.36.32.68.94.68 1.9 0 1.37-.01 2.47-.01 2.81 0 .27.18.59.69.49A10.02 10.02 0 0 0 22 12.25C22 6.58 17.52 2 12 2z" /></svg>
              View source
            </a>
          </div>
        </div>
      </header>

      <section className="features wrap" id="features">
        <div className="grid">
          <div className="card">
            <div className="icon"><svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="16" rx="2" /><line x1="10" y1="4" x2="10" y2="20" /><line x1="10" y1="12" x2="21" y2="12" /></svg></div>
            <h3>Custom detail pages</h3>
            <p>Arrange each game's page with a rows and column-band layout. Drag panels to reorder exactly how you like.</p>
          </div>
          <div className="card">
            <div className="icon"><svg viewBox="0 0 24 24"><path d="M12 3v12" /><path d="M7 11l5 5 5-5" /><path d="M4 21h16" /></svg></div>
            <h3>Automatic metadata</h3>
            <p>Point Atlas at a folder and it fills in titles, cover art, engines, and versions for you.</p>
          </div>
          <div className="card">
            <div className="icon"><svg viewBox="0 0 24 24"><path d="M10 5h10" /><path d="M10 12h10" /><path d="M10 19h10" /><circle cx="4" cy="5" r="1.5" /><circle cx="4" cy="12" r="1.5" /><circle cx="4" cy="19" r="1.5" /></svg></div>
            <h3>Version tracking</h3>
            <p>Keep every build of a game in one place and see at a glance what's installed.</p>
          </div>
          <div className="card">
            <div className="icon"><svg viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2" /><circle cx="9" cy="9" r="2" /><path d="M21 15l-5-5L5 21" /></svg></div>
            <h3>Portable image cache</h3>
            <p>Banners and screenshots travel with your library &mdash; move it to any drive or machine.</p>
          </div>
          <div className="card">
            <div className="icon"><svg viewBox="0 0 24 24"><ellipse cx="12" cy="6" rx="8" ry="3" /><path d="M4 6v12c0 1.66 3.58 3 8 3s8-1.34 8-3V6" /><path d="M4 12c0 1.66 3.58 3 8 3s8-1.34 8-3" /></svg></div>
            <h3>Local &amp; private</h3>
            <p>Everything lives in a portable SQLite database on your machine. No account, no cloud, no tracking.</p>
          </div>
          <div className="card">
            <div className="icon"><svg viewBox="0 0 24 24"><path d="M7 4v16l13-8z" /></svg></div>
            <h3>Launch &amp; go</h3>
            <p>Start any title straight from your library and pick up right where you left off.</p>
          </div>
        </div>
      </section>

      <footer>
        <span className="stack"><span className="teal">&#9670;</span> Built with Electron &middot; React &middot; Vite &middot; SQLite</span>
        <a href="https://github.com/towerwatchman/atlas" style={{ color: '#7a848c' }}>towerwatchman/atlas</a>
      </footer>
    </div>
  );
}
