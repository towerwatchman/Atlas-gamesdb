import React, { useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';

// Public landing page. Animated starfield canvas behind a simple hero, with a
// discreet Admin link that routes to the login-gated admin area.
export default function Landing() {
  const canvasRef = useRef(null);
  const navigate = useNavigate();

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d');
    let raf;
    let stars = [];
    let w, h;

    function resize() {
      w = canvas.width = canvas.offsetWidth * devicePixelRatio;
      h = canvas.height = canvas.offsetHeight * devicePixelRatio;
      const count = Math.min(400, Math.floor((w * h) / 6000));
      stars = Array.from({ length: count }, () => ({
        x: Math.random() * w,
        y: Math.random() * h,
        z: Math.random() * 0.8 + 0.2,      // depth -> size & speed
        tw: Math.random() * Math.PI * 2,   // twinkle phase
      }));
    }

    function frame(t) {
      ctx.clearRect(0, 0, w, h);
      for (const s of stars) {
        s.y += s.z * 0.25 * devicePixelRatio;         // gentle drift
        if (s.y > h) { s.y = 0; s.x = Math.random() * w; }
        const r = s.z * 1.6 * devicePixelRatio;
        const a = 0.5 + 0.5 * Math.sin(t / 800 + s.tw);
        ctx.beginPath();
        ctx.arc(s.x, s.y, r, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(150, 210, 230, ${a * s.z})`;
        ctx.fill();
      }
      raf = requestAnimationFrame(frame);
    }

    resize();
    window.addEventListener('resize', resize);
    raf = requestAnimationFrame(frame);
    return () => { cancelAnimationFrame(raf); window.removeEventListener('resize', resize); };
  }, []);

  return (
    <div className="landing">
      <canvas ref={canvasRef} className="landing-stars" />
      <div className="landing-top">
        <div className="brand"><span className="mark" /> Atlas</div>
        <button className="btn btn-sm" onClick={() => navigate('/admin')}>Admin</button>
      </div>
      <div className="landing-hero">
        <h1>Atlas</h1>
        <p>A curated games database, continuously updated.</p>
      </div>
    </div>
  );
}
