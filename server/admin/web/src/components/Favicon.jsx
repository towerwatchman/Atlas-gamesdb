import React, { useState } from 'react';
import { faviconUrl, hostFor } from '../lib/favicon.js';

// A 16px favicon for an external link. Renders nothing if there's no host or the
// image fails, so a dead icon service degrades to the plain text label rather
// than littering the UI with broken images.
export default function Favicon({ link, host, size = 16, style }) {
  const [failed, setFailed] = useState(false);
  const resolved = host || hostFor(link);
  const src = faviconUrl(resolved);
  if (!src || failed) return null;
  return (
    <img
      src={src}
      alt=""
      aria-hidden="true"
      width={size}
      height={size}
      loading="lazy"
      onError={() => setFailed(true)}
      style={{ width: size, height: size, borderRadius: 3, flex: '0 0 auto', ...style }}
    />
  );
}
