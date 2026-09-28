/* Lead report runtime. Inlined into the HTML by report.py. Vanilla JS, no dependencies, no network. */
(function () {
  'use strict';

  const D = JSON.parse(document.getElementById('leadgen-data').textContent);
  const M = D.meta, K = D.kpi, LEADS = D.leads || [];
  const THR = typeof M.threshold === 'number' ? M.threshold : 40;
  const REDUCED = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const root = document.documentElement;

  // ------------------------------------------------------------------ helpers
  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const fmt = n => (Number(n) || 0).toLocaleString('en-US');
  const pct = (a, b) => (b ? Math.round((100 * a) / b) : 0);
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const cap = s => (s ? String(s).charAt(0).toUpperCase() + String(s).slice(1) : '');
  const lc = s => (/^[A-Z]{2}/.test(s) ? s : s.charAt(0).toLowerCase() + s.slice(1));
  const safeUrl = u => (typeof u === 'string' && /^https?:\/\//i.test(u) ? u : '');
  const loc = l => [l.city, l.state].filter(Boolean).join(', ');
  const cityKey = l => (l.city ? l.city + '|' + (l.state || '') : '');
  const cityLabel = k => k.split('|').filter(Boolean).join(', ');
  const telOf = p => { const d = String(p || '').replace(/[^\d+]/g, ''); return /\d{3}/.test(d) ? 'tel:' + d : ''; };
  const sum = a => a.reduce((s, x) => s + x, 0);
  const fold = s => String(s || '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, ''); // "Café" matches "cafe"

  const ICONS = {
    search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>',
    phone: '<path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2"/>',
    mail: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/>',
    copy: '<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1"/>',
    pin: '<path d="M12 21s-7-6.1-7-11a7 7 0 0 1 14 0c0 4.9-7 11-7 11z"/><circle cx="12" cy="10" r="2.5"/>',
    x: '<path d="M18 6 6 18M6 6l12 12"/>',
    left: '<path d="m15 18-6-6 6-6"/>',
    right: '<path d="m9 18 6-6-6-6"/>',
    arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    moon: '<path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/>',
    table: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 10h18M3 15h18M9 4v16"/>',
    grid: '<rect x="3" y="3" width="7.5" height="7.5" rx="1.5"/><rect x="13.5" y="3" width="7.5" height="7.5" rx="1.5"/><rect x="3" y="13.5" width="7.5" height="7.5" rx="1.5"/><rect x="13.5" y="13.5" width="7.5" height="7.5" rx="1.5"/>',
    ext: '<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
    check: '<path d="m5 12 5 5L20 7"/>',
    shield: '<path d="M12 3 5 6v6c0 4.5 3 7.5 7 9 4-1.5 7-4.5 7-9V6z"/><path d="m9 12 2 2 4-4"/>',
    building: '<rect x="4" y="3" width="16" height="18" rx="2"/><path d="M9 7h1M14 7h1M9 11h1M14 11h1M9 15h1M14 15h1M10 21v-3h4v3"/>',
    users: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0M16 4.5a3.5 3.5 0 0 1 0 7M18 14a6 6 0 0 1 3.5 6"/>',
    scan: '<path d="M4 8V5a1 1 0 0 1 1-1h3M16 4h3a1 1 0 0 1 1 1v3M20 16v3a1 1 0 0 1-1 1h-3M8 20H5a1 1 0 0 1-1-1v-3M7 12h10"/>',
    target: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.5"/>',
    flame: '<path d="M12 22a7 7 0 0 0 7-7c0-4-3-6-4-9-2 2-2 4-2 4s-2-1-2-4c-3 2-6 5.5-6 9a7 7 0 0 0 7 7z"/>',
    map: '<path d="m9 4-6 2v14l6-2 6 2 6-2V4l-6 2z"/><path d="M9 4v14M15 6v14"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    minus: '<path d="M5 12h14"/>',
    reset: '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/>',
    file: '<path d="M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8z"/><path d="M14 3v5h5M9 13h6M9 17h6"/>',
    alert: '<path d="M12 3 2 20h20z"/><path d="M12 10v4M12 17v.01"/>',
    link: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
    linkedin: '<rect x="3" y="3" width="18" height="18" rx="3"/><path d="M8 10v7M8 7v.01M12 17v-4a2 2 0 0 1 4 0v4M12 10v7"/>',
    facebook: '<path d="M15 3h-2a4 4 0 0 0-4 4v3H7v4h2v7h4v-7h3l1-4h-4V7a1 1 0 0 1 1-1h2z"/>',
    instagram: '<rect x="3" y="3" width="18" height="18" rx="5"/><circle cx="12" cy="12" r="4"/><path d="M17.5 6.5v.01"/>',
    youtube: '<rect x="2" y="5" width="20" height="14" rx="4"/><path d="m10 9 5 3-5 3z"/>',
    sparkle: '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/><path d="M19 17v4M17 19h4"/>'
  };
  const icon = (n, cls) => `<svg class="i ${cls || ''}" viewBox="0 0 24 24" aria-hidden="true">${ICONS[n] || ''}</svg>`;

  const SIG = {
    booking_widget: 'Online booking', chat_widget: 'Chat widget', analytics_pixel: 'Analytics or ad pixel',
    reviews_widget: 'Reviews widget', email_marketing: 'Email marketing', ai_or_chatbot: 'AI or chatbot',
    financing_or_pricing: 'Financing or pricing', hiring: 'Hiring', site_stale: 'Stale site', https: 'HTTPS',
    mobile_viewport: 'Mobile friendly', has_form: 'Contact form', ecommerce: 'E-commerce'
  };
  const sigLabel = k => SIG[k] || cap(String(k).replace(/_/g, ' '));
  const PLATFORM = { wordpress: 'WordPress', wix: 'Wix', squarespace: 'Squarespace', shopify: 'Shopify', godaddy: 'GoDaddy', weebly: 'Weebly', webflow: 'Webflow', duda: 'Duda', hubspot: 'HubSpot', ghl: 'GoHighLevel', other: 'Custom or unknown' };
  const SOURCE = { osm: 'OpenStreetMap', places: 'Google Places', apollo: 'Apollo', csv: 'CSV import', web_research: 'Web research', hunter: 'Hunter', manual: 'Manual entry' };
  const PROVIDER = { google_places: 'Google Places', overpass: 'OpenStreetMap (free)', hunter: 'Hunter', apollo: 'Apollo', instantly: 'Instantly', ghl: 'GoHighLevel' };
  const VIA = { crawl: 'Found on site', hunter: 'Hunter', apollo: 'Apollo', pattern: 'Pattern guess', csv: 'CSV import', manual: 'Manual' };
  const VERIFY = {
    valid: ['Verified', 'var(--good)'], catch_all: ['Catch-all', 'var(--accent-2)'], unknown: ['MX ok', 'var(--info)'],
    risky: ['Risky', 'var(--warn)'], invalid: ['Invalid', 'var(--bad)'], unverified: ['Not checked', 'var(--neutral)']
  };
  const ETYPE = {
    personal: ['Personal', 'var(--accent)', 'A named person on the company domain'],
    role: ['Role inbox', 'var(--accent-2)', 'Shared inboxes like info@ or office@'],
    personal_webmail: ['Webmail', 'var(--warn)', 'Owner-operated businesses often use gmail and similar'],
    third_party: ['Third party', 'var(--neutral)', 'Belongs to another org (web agency, franchisor); never exported'],
    unknown: ['Other', 'var(--muted)', '']
  };
  const WLABEL = {
    has_email: 'Usable email', personal_email: 'Personal email', verified_email: 'Verified email', catch_all_email: 'Catch-all email',
    mx_ok_email: 'Mail server responds', has_phone: 'Phone number', has_website: 'Website', keyword_match: 'Niche keyword match',
    title_match: 'Decision-maker title', has_social: 'Social profile', rating_ok: 'Rating meets minimum', no_email: 'No usable email',
    third_party_email_only: 'Only third-party email', pattern_email_only: 'Only a guessed email', rating_below_min: 'Rating below minimum',
    reviews_below_min: 'Too few reviews'
  };
  const AV = [['#8b5cf6', '#6366f1'], ['#06b6d4', '#3b82f6'], ['#10b981', '#0891b2'], ['#f59e0b', '#ef4444'],
              ['#ec4899', '#8b5cf6'], ['#3b82f6', '#8b5cf6'], ['#14b8a6', '#22c55e'], ['#f97316', '#ec4899']];

  function hash(s) { let h = 2166136261; for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return h >>> 0; }
  let LETTER;
  try { LETTER = new RegExp('[\\p{L}\\p{N}]', 'u'); } catch (e) { LETTER = /[A-Za-z0-9\u00C0-\u024F]/; }
  const firstLetter = w => Array.from(w).find(ch => LETTER.test(ch)) || '';
  function initials(name) {
    const w = String(name || '').split(/\s+/).filter(x => firstLetter(x) && !/^(the|and|of|llc|inc\.?|co\.?|ltd\.?)$/i.test(x));
    return ((w[0] ? firstLetter(w[0]) : '') + (w[1] ? firstLetter(w[1]) : '')).toUpperCase() || '?';
  }
  function avatar(l, cls) {
    const pair = AV[hash(l.name || '') % AV.length];
    return `<span class="av ${cls || ''}" style="--a:${pair[0]};--b:${pair[1]}" aria-hidden="true">${esc(initials(l.name))}</span>`;
  }
  function tier(l) {
    if (l.score == null) return { k: 'low', label: 'Not scored yet', c: 'var(--neutral)' };
    if (!l.q) return l.disq ? { k: 'disq', label: 'Disqualified', c: 'var(--bad)' } : { k: 'low', label: 'Below threshold', c: 'var(--neutral)' };
    if (l.score >= THR + 40) return { k: 'hot', label: 'Hot lead', c: 'var(--accent)' };
    if (l.score >= THR + 20) return { k: 'warm', label: 'Warm lead', c: 'var(--accent-mid)' };
    return { k: 'fit', label: 'Good fit', c: 'var(--accent-2)' };
  }
  function sring(l, size, sw, cls) {
    size = size || 40; sw = sw || 4;
    const r = (size - sw) / 2, C = 2 * Math.PI * r, p = clamp((l.score || 0) / 100, 0, 1), t = tier(l);
    return `<span class="sring ${cls || ''}" style="--c:${t.c}" data-tip="${esc(t.label)}: score ${l.score == null ? 'n/a' : Math.round(l.score)}">` +
      `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" aria-hidden="true"><circle class="trk" cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke-width="${sw}"/>` +
      `<circle class="val" cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke-width="${sw}" stroke-linecap="round" stroke-dasharray="${(C * p).toFixed(1)} ${C.toFixed(1)}"/></svg>` +
      `<b>${l.score == null ? '–' : Math.round(l.score)}</b></span>`;
  }
  function primary(l) {
    const ps = l.people || [];
    return ps.find(p => p.primary && p.email && !p.blocked) || ps.find(p => p.email && !p.blocked) || ps[0] || null;
  }
  function vbadge(p) {
    if (!p || !p.email) return '';
    if (p.blocked) return `<span class="badge b-blocked">Won't export: ${esc(p.blocked)}</span>`;
    const v = VERIFY[p.verify] || VERIFY.unverified;
    return `<span class="badge b-${esc(p.verify || 'unverified')}">${v[0]}</span>`;
  }
  function stars(l) {
    if (l.rating == null) return '';
    return `<span class="stars" data-tip="${esc(l.rating)} stars from ${fmt(l.reviews || 0)} reviews"><span class="s">★★★★★<i style="--w:${clamp(l.rating / 5, 0, 1) * 100}%">★★★★★</i></span>${esc(l.rating)}${l.reviews != null ? ` <small>(${fmt(l.reviews)})</small>` : ''}</span>`;
  }
  // Signals that moved the score come first and are highlighted: they are the reasons to call.
  function leadChips(l) {
    const out = [], has = new Set(l.signals || []), bonus = D.bonus || {};
    Object.keys(bonus).forEach(k => {
      const pts = bonus[k];
      if (!(pts > 0)) return;
      if (k.indexOf('no_') === 0) {
        const s = k.slice(3);
        if (l.crawl === 'ok' && !has.has(s)) out.push({ t: 'No ' + lc(sigLabel(s)), hot: 1, tip: `+${pts} points: the site shows no ${lc(sigLabel(s))}` });
      } else if (has.has(k)) out.push({ t: sigLabel(k), hot: 1, tip: `+${pts} points in the fit score` });
    });
    (l.signals || []).forEach(s => {
      if (!(s in bonus) && ['https', 'mobile_viewport', 'has_form'].indexOf(s) < 0) out.push({ t: sigLabel(s) });
    });
    if (l.cms) out.push({ t: PLATFORM[l.cms] || cap(l.cms), tip: 'Website platform' });
    return out;
  }
  function chipsHtml(chips, max) {
    const shown = max ? chips.slice(0, max) : chips;
    const more = chips.length - shown.length;
    return shown.map(c => `<span class="chip${c.hot ? ' hot' : ''}"${c.tip ? ` data-tip="${esc(c.tip)}"` : ''}>${c.hot ? icon('sparkle') : ''}${esc(c.t)}</span>`).join('') +
      (more > 0 ? `<span class="chip" data-tip="${esc(chips.slice(max).map(c => c.t).join(', '))}">+${more}</span>` : '');
  }

  // ------------------------------------------------------------------ tooltip, toast, copy
  const tip = $('#tip');
  let mapTip = false;
  function showTip(html, x, y) {
    tip.innerHTML = html;
    tip.classList.add('on');
    const r = tip.getBoundingClientRect();
    let L = x + 14, T = y + 16;
    if (L + r.width > window.innerWidth - 8) L = x - r.width - 14;
    if (T + r.height > window.innerHeight - 8) T = y - r.height - 14;
    tip.style.left = Math.max(8, L) + 'px';
    tip.style.top = Math.max(8, T) + 'px';
  }
  function hideTip() { tip.classList.remove('on'); }
  document.addEventListener('mousemove', e => {
    if (mapTip) return;
    const el = e.target.closest ? e.target.closest('[data-tip]') : null;
    if (el) showTip(esc(el.getAttribute('data-tip')), e.clientX, e.clientY); else hideTip();
  });
  document.addEventListener('scroll', hideTip, { passive: true });

  let toastTimer;
  function toast(msg) {
    const t = $('#toast');
    t.innerHTML = icon('check') + '<span>' + esc(msg) + '</span>';
    t.classList.add('on');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.remove('on'), 1900);
  }
  function copy(text) {
    const done = () => toast('Copied ' + text);
    const fallback = () => {
      const ta = document.createElement('textarea');
      ta.value = text; ta.setAttribute('readonly', ''); ta.style.position = 'fixed'; ta.style.opacity = '0';
      document.body.appendChild(ta); ta.select();
      try { document.execCommand('copy'); done(); } catch (e) { toast('Copy failed: select the text instead'); }
      ta.remove();
    };
    if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(text).then(done, fallback); else fallback();
  }
  document.addEventListener('click', e => {
    const c = e.target.closest('[data-copy]');
    if (c) { e.preventDefault(); e.stopPropagation(); copy(c.getAttribute('data-copy')); }
  });

  // ------------------------------------------------------------------ theme
  const darkMQ = window.matchMedia('(prefers-color-scheme: dark)');
  const isDark = () => (root.getAttribute('data-theme') || (darkMQ.matches ? 'dark' : 'light')) === 'dark';
  const MAPS = [];
  function paintThemeBtn() { $('#theme').innerHTML = icon(isDark() ? 'sun' : 'moon'); }
  function themeChanged() { paintThemeBtn(); MAPS.forEach(m => m.draw()); }
  $('#theme').addEventListener('click', () => {
    const next = isDark() ? 'light' : 'dark';
    root.setAttribute('data-theme', next);
    try { localStorage.setItem('leadgen-theme', next); } catch (e) { /* storage blocked: theme still applies for this visit */ }
    themeChanged();
  });
  if (darkMQ.addEventListener) darkMQ.addEventListener('change', themeChanged);
  paintThemeBtn();

  // ------------------------------------------------------------------ animation on first reveal
  function countUp(el) {
    const to = Number(el.getAttribute('data-count')) || 0;
    if (REDUCED || to === 0) { el.textContent = fmt(to); return; }
    el.textContent = '0';
    const d = 1300, t0 = performance.now();
    let ticked = false;
    const f = t => {
      ticked = true;
      const p = Math.min(1, (t - t0) / d), e = 1 - Math.pow(1 - p, 4);
      el.textContent = fmt(Math.round(to * e));
      if (p < 1) requestAnimationFrame(f);
    };
    requestAnimationFrame(f);
    setTimeout(() => { if (!ticked) el.textContent = fmt(to); }, d + 200); // frames paused (background tab): show the number anyway
  }
  // Two frames so the hidden-to-visible switch paints before transitions start; the timer covers paused frames.
  function afterPaint(fn) {
    let done = false;
    const run = () => { if (!done) { done = true; fn(); } };
    requestAnimationFrame(() => requestAnimationFrame(run));
    setTimeout(run, 150);
  }
  function reveal(sec) {
    if (sec.getAttribute('data-rev')) return;
    sec.setAttribute('data-rev', '1');
    $$('[data-count]', sec).forEach(countUp);
    afterPaint(() => {
      sec.classList.add('revealed');
      $$('[data-off]', sec).forEach(c => { c.style.strokeDashoffset = c.getAttribute('data-off'); });
      $$('[data-da]', sec).forEach(c => { c.style.strokeDasharray = c.getAttribute('data-da'); });
    });
  }

  // ------------------------------------------------------------------ small chart builders
  function hbars(rows, opts) {
    opts = opts || {};
    if (!rows.length) return `<p class="sub">${opts.empty || 'No data yet.'}</p>`;
    const mx = opts.max || Math.max(1, ...rows.map(r => r.v));
    return '<div class="hb">' + rows.map((r, i) =>
      `<div class="hb-row${r.go ? ' click' : ''}"${r.go ? ` data-go="${esc(r.go)}"` : ''} data-tip="${esc(r.tip || `${r.label}: ${fmt(r.v)}`)}">` +
      `<span class="hb-l">${esc(r.label)}${r.chip || ''}</span><span class="hb-t"><i style="--w:${Math.max(r.v ? 1.5 : 0, (100 * r.v) / mx).toFixed(1)}%;--c:${r.c || opts.c || 'var(--grad)'};transition-delay:${i * 45}ms"></i></span>` +
      `<span class="hb-v">${r.text != null ? r.text : fmt(r.v)}${r.small ? `<small>${r.small}</small>` : ''}</span></div>`).join('') + '</div>';
  }
  function legend(rows, total) {
    return '<div class="legend">' + rows.map(r =>
      `<div class="lg-row" style="--c:${r.c}" data-tip="${esc(r.tip || r.label)}"><i></i><span>${esc(r.label)}</span><b>${fmt(r.v)}</b><small>${pct(r.v, total)}%</small></div>`).join('') + '</div>';
  }
  function stack(rows, total) {
    return '<div class="stack">' + rows.filter(r => r.v).map(r =>
      `<i style="--w:${((100 * r.v) / (total || 1)).toFixed(2)}%;--c:${r.c}" data-tip="${esc(`${r.label}: ${fmt(r.v)} (${pct(r.v, total)}%)`)}"></i>`).join('') + '</div>';
  }
  function donut(rows, centerTop, centerSub) {
    const total = sum(rows.map(r => r.v)) || 1, R = 58, C = 2 * Math.PI * R, gap = rows.filter(r => r.v).length > 1 ? 3 : 0;
    let off = 0;
    const segs = rows.filter(r => r.v).map(r => {
      const len = (C * r.v) / total, da = `${Math.max(0.5, len - gap).toFixed(2)} ${(C - Math.max(0.5, len - gap)).toFixed(2)}`;
      const s = `<circle r="${R}" fill="none" stroke="${r.c}" stroke-width="18" stroke-dashoffset="${(-off).toFixed(2)}" style="stroke-dasharray:0 ${C.toFixed(2)}" data-da="${da}" data-tip="${esc(`${r.label}: ${fmt(r.v)} (${pct(r.v, total)}%)`)}"/>`;
      off += len;
      return s;
    }).join('');
    return `<div class="donut"><svg viewBox="-75 -75 150 150" aria-hidden="true"><circle r="${R}" fill="none" stroke="var(--surface-3)" stroke-width="18"/>${segs}</svg>` +
      `<div class="c"><b>${centerTop}</b><span>${centerSub}</span></div></div>`;
  }
  function histogram(bins) {
    const W = 640, H = 240, pl = 36, pr = 10, pt = 22, pb = 30, n = bins.length;
    const mx = Math.max(1, ...bins.map(b => b[1])), bw = (W - pl - pr) / n, ih = H - pt - pb;
    let s = `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Fit score distribution"><defs>` +
      `<linearGradient id="hg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" style="stop-color:var(--accent)"/><stop offset="1" style="stop-color:var(--accent-2)"/></linearGradient></defs>`;
    for (let g = 0; g <= 4; g++) {
      const y = pt + ih * (1 - g / 4);
      s += `<line class="gl" x1="${pl}" x2="${W - pr}" y1="${y.toFixed(1)}" y2="${y.toFixed(1)}"/>`;
      if (g) s += `<text x="${pl - 8}" y="${(y + 4).toFixed(1)}" text-anchor="end">${fmt(Math.round((mx * g) / 4))}</text>`;
    }
    bins.forEach((b, i) => {
      const lo = b[0], c = b[1], h = (ih * c) / mx, x = pl + i * bw + 5, w = bw - 10, y = H - pb - h;
      const above = lo >= THR, partial = !above && lo + 10 > THR;
      const range = i === 0 ? 'below 10' : i === n - 1 ? '90 and up' : `${lo} to ${lo + 9}`;
      s += `<rect class="bar" x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${w.toFixed(1)}" height="${Math.max(0, h).toFixed(1)}" rx="6" fill="${above || partial ? 'url(#hg)' : 'var(--neutral)'}"${partial ? ' opacity=".6"' : ''} style="transition-delay:${i * 40}ms" data-tip="${esc(`Score ${range}: ${fmt(c)} ${c === 1 ? 'company' : 'companies'}`)}"/>`;
      if (c) s += `<text class="vl" x="${(x + w / 2).toFixed(1)}" y="${(y - 7).toFixed(1)}" text-anchor="middle">${fmt(c)}</text>`;
      s += `<text x="${(x + w / 2).toFixed(1)}" y="${H - 10}" text-anchor="middle">${i === n - 1 ? '90+' : lo}</text>`;
    });
    const tx = pl + clamp(THR / 10, 0, n) * bw;
    s += `<line x1="${tx.toFixed(1)}" x2="${tx.toFixed(1)}" y1="${pt - 6}" y2="${H - pb}" stroke="var(--ink)" stroke-width="1.5" stroke-dasharray="4 4" opacity=".55"/>` +
      `<text x="${(tx + 7).toFixed(1)}" y="${pt + 4}" style="fill:var(--ink);font-weight:650">qualifies at ${THR}</text></svg>`;
    return s;
  }

  // ------------------------------------------------------------------ map (canvas, no tiles, works offline)
  function makeMap(box, opts) {
    const pts = LEADS.filter(l => typeof l.lat === 'number' && typeof l.lng === 'number');
    if (!pts.length) {
      box.insertAdjacentHTML('beforeend', '<div class="map-empty">No coordinates yet. OpenStreetMap and Google Places sources provide them.</div>');
      return null;
    }
    const lats = pts.map(p => p.lat).sort((a, b) => a - b), lngs = pts.map(p => p.lng).sort((a, b) => a - b);
    const trim = Math.floor(pts.length * 0.02); // one far-away point should not shrink the whole map
    let lat0 = lats[trim], lat1 = lats[lats.length - 1 - trim], lng0 = lngs[trim], lng1 = lngs[lngs.length - 1 - trim];
    if (lat1 - lat0 < 0.02) { lat0 -= 0.01; lat1 += 0.01; }
    if (lng1 - lng0 < 0.02) { lng0 -= 0.01; lng1 += 0.01; }
    const cosl = Math.cos(((lat0 + lat1) / 2) * Math.PI / 180), W = (lng1 - lng0) * cosl, H = lat1 - lat0;
    const P = pts.map(l => ({ l, wx: (l.lng - lng0) * cosl, wy: lat1 - l.lat, c: l.ready ? 'ready' : l.q ? 'qual' : 'other' }));
    const canvas = document.createElement('canvas');
    canvas.setAttribute('aria-label', 'Map of companies');
    canvas.setAttribute('role', 'img');
    box.prepend(canvas);
    const ctx = canvas.getContext('2d');
    const layers = { ready: true, qual: true, other: true };
    let cw = 0, ch = 0, dpr = 1, s0 = 1, ox = 0, oy = 0, k = 1, tx = 0, ty = 0, hover = null, drag = null, moved = false, raf = 0;
    let sprites = {}, spriteKey = '';

    // City labels at the centroid of each city's dots.
    const cityAgg = {};
    P.forEach(p => {
      if (!p.l.city) return;
      const a = cityAgg[p.l.city] || (cityAgg[p.l.city] = { n: 0, x: 0, y: 0, name: p.l.city });
      a.n++; a.x += p.wx; a.y += p.wy;
    });
    const cityLabels = Object.values(cityAgg).filter(a => a.n >= 3).sort((a, b) => b.n - a.n).slice(0, 10)
      .map(a => ({ name: a.name, n: a.n, wx: a.x / a.n, wy: a.y / a.n }));

    function fit() {
      const r = box.getBoundingClientRect();
      if (!r.width || !r.height) return false;
      cw = r.width; ch = r.height; dpr = Math.min(2, window.devicePixelRatio || 1);
      canvas.width = Math.round(cw * dpr); canvas.height = Math.round(ch * dpr);
      const pad = opts.interactive ? 44 : 26;
      s0 = Math.min((cw - 2 * pad) / W, (ch - 2 * pad) / H);
      ox = (cw - W * s0) / 2; oy = (ch - H * s0) / 2;
      return true;
    }
    const sx = p => (ox + p.wx * s0) * k + tx;
    const sy = p => (oy + p.wy * s0) * k + ty;
    function glow(color) {
      const c = document.createElement('canvas'); c.width = c.height = 64;
      const g = c.getContext('2d'), gr = g.createRadialGradient(32, 32, 0, 32, 32, 32);
      gr.addColorStop(0, color); gr.addColorStop(1, 'rgba(0,0,0,0)');
      g.fillStyle = gr; g.fillRect(0, 0, 64, 64);
      return c;
    }
    function draw() {
      raf = 0;
      if (!cw && !fit()) return;
      const css = getComputedStyle(root), v = n => css.getPropertyValue(n).trim();
      const col = { ready: v('--map-ready'), qual: v('--map-qual'), other: v('--map-other'), halo: v('--map-halo'), ink: v('--ink'), ink2: v('--ink-2') };
      const dark = isDark();
      if (spriteKey !== col.ready + col.qual) { sprites = { ready: glow(col.ready), qual: glow(col.qual) }; spriteKey = col.ready + col.qual; }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, cw, ch);
      // soft density glow under the dots
      const gs = (opts.interactive ? 46 : 36) * Math.sqrt(k);
      ctx.globalCompositeOperation = dark ? 'lighter' : 'source-over';
      ctx.globalAlpha = dark ? 0.13 : 0.08;
      P.forEach(p => {
        if (p.c === 'other' || !layers[p.c]) return;
        const x = sx(p), y = sy(p);
        if (x < -gs || y < -gs || x > cw + gs || y > ch + gs) return;
        ctx.drawImage(sprites[p.c], x - gs / 2, y - gs / 2, gs, gs);
      });
      ctx.globalCompositeOperation = 'source-over';
      ctx.globalAlpha = 1;
      const rk = Math.min(2.2, 1 + (k - 1) * 0.16);
      ['other', 'qual', 'ready'].forEach(c => {
        if (!layers[c]) return;
        const r = (c === 'ready' ? 3.7 : c === 'qual' ? 3.1 : 2.3) * rk * (opts.interactive ? 1.1 : 1);
        ctx.beginPath();
        P.forEach(p => {
          if (p.c !== c) return;
          const x = sx(p), y = sy(p);
          if (x < -6 || y < -6 || x > cw + 6 || y > ch + 6) return;
          ctx.moveTo(x + r, y); ctx.arc(x, y, r, 0, Math.PI * 2);
        });
        if (c !== 'other') { ctx.strokeStyle = col.halo; ctx.lineWidth = 2; ctx.stroke(); }
        ctx.fillStyle = col[c]; ctx.fill();
      });
      if (opts.interactive && cityLabels.length) {
        ctx.font = `600 12px ${getComputedStyle(document.body).fontFamily}`;
        ctx.textAlign = 'center'; ctx.lineJoin = 'round';
        const boxes = [];
        cityLabels.forEach(c => {
          const x = sx(c), y = sy(c) - 14, label = `${c.name} · ${c.n}`, w = ctx.measureText(label).width + 10;
          if (x < 0 || x > cw || y < 10 || y > ch) return;
          const b = [x - w / 2, y - 10, x + w / 2, y + 6];
          if (boxes.some(o => !(b[2] < o[0] || b[0] > o[2] || b[3] < o[1] || b[1] > o[3]))) return;
          boxes.push(b);
          ctx.strokeStyle = col.halo; ctx.lineWidth = 4; ctx.strokeText(label, x, y);
          ctx.fillStyle = col.ink2; ctx.fillText(label, x, y);
        });
      }
      if (hover) {
        const x = sx(hover), y = sy(hover);
        ctx.beginPath(); ctx.arc(x, y, 9 * rk, 0, Math.PI * 2);
        ctx.strokeStyle = col.ink; ctx.lineWidth = 1.6; ctx.stroke();
      }
    }
    const request = () => { if (!raf) raf = requestAnimationFrame(draw); };
    function nearest(mx, my, rad) {
      let best = null, bd = rad * rad;
      P.forEach(p => {
        if (!layers[p.c]) return;
        const dx = sx(p) - mx, dy = sy(p) - my, d = dx * dx + dy * dy;
        if (d < bd || (d === bd && best && p.c === 'ready')) { bd = d; best = p; }
      });
      return best;
    }
    function visibleList() {
      return P.filter(p => layers[p.c]).map(p => p.l).sort((a, b) => (b.score || 0) - (a.score || 0));
    }
    function zoomAt(mx, my, f) {
      const nk = clamp(k * f, 1, 18); f = nk / k;
      tx = mx - (mx - tx) * f; ty = my - (my - ty) * f; k = nk;
      if (k === 1) { tx = 0; ty = 0; }
      request();
    }
    const local = e => { const r = canvas.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
    canvas.addEventListener('mousemove', e => {
      if (drag) return;
      const [mx, my] = local(e), p = nearest(mx, my, 12);
      if (p !== hover) { hover = p; box.classList.toggle('hovering', !!p); request(); }
      if (p) {
        mapTip = true;
        const l = p.l, t = tier(l);
        showTip(`<b>${esc(l.name)}</b><span>${esc([loc(l), l.score != null ? 'score ' + Math.round(l.score) : '', l.ready ? 'ready to contact' : t.label.toLowerCase()].filter(Boolean).join(' · '))}</span>`, e.clientX, e.clientY);
      } else { mapTip = false; hideTip(); }
    });
    canvas.addEventListener('mouseleave', () => { hover = null; mapTip = false; hideTip(); box.classList.remove('hovering'); request(); });
    canvas.addEventListener('click', e => {
      if (moved) return;
      const [mx, my] = local(e), p = nearest(mx, my, 16);
      if (p) { mapTip = false; hideTip(); openLead(p.l.id, visibleList()); } else if (opts.onBackground) opts.onBackground();
    });
    if (opts.interactive) {
      box.classList.add('pannable');
      canvas.addEventListener('wheel', e => { e.preventDefault(); const [mx, my] = local(e); zoomAt(mx, my, Math.exp(-e.deltaY * 0.0016)); }, { passive: false });
      canvas.addEventListener('dblclick', e => { const [mx, my] = local(e); zoomAt(mx, my, 2); });
      canvas.addEventListener('pointerdown', e => {
        if (e.button !== 0) return;
        drag = { x: e.clientX, y: e.clientY, tx, ty }; moved = false;
        canvas.setPointerCapture(e.pointerId);
      });
      canvas.addEventListener('pointermove', e => {
        if (!drag) return;
        const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
        if (Math.abs(dx) + Math.abs(dy) > 3) { moved = true; box.classList.add('drag'); hover = null; mapTip = false; hideTip(); }
        if (moved) { tx = drag.tx + dx; ty = drag.ty + dy; request(); }
      });
      const end = () => { drag = null; box.classList.remove('drag'); setTimeout(() => { moved = false; }, 0); };
      canvas.addEventListener('pointerup', end);
      canvas.addEventListener('pointercancel', end);
    }
    if (window.ResizeObserver) new ResizeObserver(() => { if (fit()) request(); }).observe(box);
    else window.addEventListener('resize', () => { if (fit()) request(); });
    const api = {
      draw: request,
      zoom: f => zoomAt(cw / 2, ch / 2, f),
      reset: () => { k = 1; tx = 0; ty = 0; request(); },
      toggle: (name, on) => { layers[name] = on; hover = null; request(); },
      counts: () => ({ ready: P.filter(p => p.c === 'ready').length, qual: P.filter(p => p.c === 'qual').length, other: P.filter(p => p.c === 'other').length, total: P.length })
    };
    MAPS.push(api);
    request();
    return api;
  }

  // ------------------------------------------------------------------ OVERVIEW
  const STAGES = [
    { k: 'all', short: 'All', label: 'Companies found', v: K.total, tip: 'Every business found by any source' },
    { k: 'website', short: 'Website', label: 'With a website', v: K.website, tip: `Crawlable for emails and signals; ${fmt(K.crawled)} crawled so far` },
    { k: 'email', short: 'Email', label: 'Email found', v: K.email, tip: 'At least one usable address (not invalid, not do-not-contact)' },
    { k: 'qualified', short: 'Qualified', label: 'Qualified', v: K.qualified, tip: `Fit score at or above ${THR} with no disqualifier` },
    { k: 'ready', short: 'Ready', label: 'Ready to contact', v: K.ready, tip: 'Qualified and has a usable email' }
  ];

  function bigRing() {
    const R = 100, C = 2 * Math.PI * R, target = M.target, p = target ? clamp(K.ready / target, 0, 1) : (K.ready ? 1 : 0);
    let ticks = '';
    for (let i = 0; i < 60; i++) {
      const a = (i / 60) * Math.PI * 2, r1 = 114, r2 = i % 5 === 0 ? 120 : 117;
      ticks += `<line class="tick" x1="${(Math.cos(a) * r1).toFixed(1)}" y1="${(Math.sin(a) * r1).toFixed(1)}" x2="${(Math.cos(a) * r2).toFixed(1)}" y2="${(Math.sin(a) * r2).toFixed(1)}" stroke-width="${i % 5 === 0 ? 1.6 : 1}"/>`;
    }
    return `<div class="bigring"><svg viewBox="-124 -124 248 248" aria-hidden="true"><defs><linearGradient id="rg" x1="0" y1="0" x2="1" y2="1">` +
      `<stop offset="0" style="stop-color:var(--accent)"/><stop offset=".55" style="stop-color:var(--accent-mid)"/><stop offset="1" style="stop-color:var(--accent-2)"/></linearGradient></defs>` +
      `${ticks}<circle class="trk" r="${R}" fill="none" stroke-width="15"/>` +
      `<circle class="val" r="${R}" fill="none" stroke="url(#rg)" stroke-width="15" stroke-linecap="round" stroke-dasharray="${C.toFixed(2)}" style="stroke-dashoffset:${C.toFixed(2)}" data-off="${(C * (1 - p)).toFixed(2)}"/></svg>` +
      `<div class="ring-c"><span class="k">Ready now</span><span class="v" data-count="${K.ready}">${fmt(K.ready)}</span><span class="of">${target ? `of ${fmt(target)} target` : 'no target set'}</span></div></div>`;
  }
  function funnel() {
    const mx = Math.max(1, ...STAGES.map(s => s.v)), n = STAGES.length, cwid = 1000 / n, bwid = cwid * 0.4, Hh = 132, mid = Hh / 2;
    const geo = STAGES.map((s, i) => { const h = Math.max(6, ((Hh - 10) * s.v) / mx), x = i * cwid + 10; return { x, x2: x + bwid, y: mid - h / 2, y2: mid + h / 2 }; });
    let svg = `<svg class="fn-svg" viewBox="0 0 1000 ${Hh}" preserveAspectRatio="none" aria-hidden="true"><defs>` +
      `<linearGradient id="fg" x1="0" y1="0" x2="1000" y2="0" gradientUnits="userSpaceOnUse"><stop offset="0" style="stop-color:var(--accent)"/><stop offset=".6" style="stop-color:var(--accent-mid)"/><stop offset="1" style="stop-color:var(--accent-2)"/></linearGradient></defs>`;
    for (let i = 0; i < n - 1; i++) {
      const a = geo[i], b = geo[i + 1], xm = (a.x2 + b.x) / 2;
      svg += `<path class="band" d="M${a.x2} ${a.y}C${xm} ${a.y} ${xm} ${b.y} ${b.x} ${b.y}L${b.x} ${b.y2}C${xm} ${b.y2} ${xm} ${a.y2} ${a.x2} ${a.y2}Z" fill="url(#fg)" opacity=".16"/>`;
    }
    geo.forEach((g, i) => { svg += `<rect x="${g.x}" y="${g.y.toFixed(1)}" width="${bwid}" height="${(g.y2 - g.y).toFixed(1)}" rx="5" fill="url(#fg)" opacity="${i === n - 1 ? 1 : 0.85}"/>`; });
    svg += '</svg>';
    const cols = STAGES.map((s, i) =>
      `<button class="fn-col" type="button" data-stage="${s.k}" data-tip="${esc(s.tip)}"><div class="v" data-count="${s.v}">${fmt(s.v)}</div><div class="l">${s.label}</div>` +
      `<span class="cv">${i === 0 ? 'every source' : `<b>${pct(s.v, K.total)}%</b> of found`}</span></button>`).join('');
    return `<div class="funnel"><div class="fn-cols">${cols}</div>${svg}</div>`;
  }
  function kpis() {
    const t = [
      ['building', 'Companies found', K.total, 0, 'var(--accent)', 'Every business any source returned'],
      ['globe', 'With a website', K.website, K.total, 'var(--accent-mid)', 'Needed for crawling emails and signals'],
      ['phone', 'With a phone', K.phone, K.total, 'var(--accent-2)', 'Listed phone number'],
      ['scan', 'Sites crawled', K.crawled, K.website, 'var(--info)', `${fmt(K.crawl_errors)} failed, ${fmt(K.crawl_pending)} still pending`],
      ['mail', 'With an email', K.email, K.total, 'var(--accent)', 'At least one usable address'],
      ['shield', 'Verified email', K.verified, K.email, 'var(--good)', 'Confirmed by a provider (valid or catch-all)']
    ];
    return t.map(x => {
      const p = x[3] ? pct(x[2], x[3]) : 100;
      return `<div class="kpi" style="--tc:${x[4]}" data-tip="${esc(x[5])}"><div class="ic">${icon(x[0])}</div>${x[3] ? `<span class="p">${p}%</span>` : ''}` +
        `<div class="n" data-count="${x[2]}">${fmt(x[2])}</div><div class="l">${x[1]}</div><div class="mini"><i style="--w:${p}%"></i></div></div>`;
    }).join('');
  }
  function titleHtml(t) {
    const w = String(t).split(' ');
    if (w.length < 2) return `<span class="grad">${esc(t)}</span>`;
    return esc(w.slice(0, -1).join(' ')) + ' <span class="grad">' + esc(w[w.length - 1]) + '</span>';
  }

  function buildOverview(el) {
    const places = M.places || [];
    const where = places.length ? ` across ${places.length === 1 ? esc(places[0]) : places.length + ' places'}` : '';
    const lede = K.total
      ? `<b>${fmt(K.total)}</b> ${M.niche ? esc(M.niche) : 'companies'} found${where}. <b>${fmt(K.qualified)}</b> fit your profile and <b>${fmt(K.ready)}</b> are ready to contact today.`
      : 'No companies in the lead store yet. Run the pipeline, then generate this report again.';
    const ready = LEADS.filter(l => l.ready);
    const top = (ready.length ? ready : LEADS.filter(l => l.q)).slice(0, 7);
    const hero = `<div class="hero"><div class="hero-main">
      <span class="eyebrow"><span class="pulse"></span>Lead report · ${esc(M.generated_label)}</span>
      <h1>${titleHtml(M.title)}</h1><p class="lede">${lede}</p>
      ${places.length ? `<div class="chips">${places.slice(0, 8).map(p => `<span class="chip">${icon('pin')}${esc(p)}</span>`).join('')}${places.length > 8 ? `<span class="chip">+${places.length - 8} more</span>` : ''}</div>` : ''}
      ${M.offer ? `<p class="offer"><span>Your offer</span>${esc(M.offer)}</p>` : ''}
      ${K.total ? `<div class="cta"><a class="btn primary" href="#leads">${icon('users')}Explore ${fmt(K.ready)} ready leads${icon('arrow')}</a><a class="btn" href="#map">${icon('map')}Open the map</a></div>` : ''}
    </div><div class="card ring-card">${bigRing()}<p class="ring-foot">${M.target ? `<b>${pct(K.ready, M.target)}%</b> of target. ` : ''}Ready means qualified with a usable email.</p></div></div>`;
    if (!K.total) {
      el.innerHTML = hero + `<div class="card empty"><div class="glyph">${icon('search')}</div><b>Nothing to show yet</b>` +
        `Run <code>python3 scripts/leadgen.py run</code> to source, crawl and score, then <code>python3 scripts/leadgen.py report --open</code>.</div>`;
      return;
    }
    const et = D.email_types.map(r => ({ label: (ETYPE[r[0]] || ETYPE.unknown)[0], v: r[1], c: (ETYPE[r[0]] || ETYPE.unknown)[1], tip: (ETYPE[r[0]] || ETYPE.unknown)[2] }));
    const vr = D.verify.map(r => ({ label: (VERIFY[r[0]] || [r[0]])[0], v: r[1], c: (VERIFY[r[0]] || [0, 'var(--neutral)'])[1] }));
    const etTotal = sum(et.map(r => r.v)), vrTotal = sum(vr.map(r => r.v));
    el.innerHTML = hero + `<div class="kpis">${kpis()}</div>
    <div class="grid"><div class="card c12"><div class="card-h"><div><h3>Pipeline</h3><p>From every business found to a lead you can email. Click a stage to open those companies.</p></div></div>${funnel()}</div></div>
    <div class="grid">
      <div class="card c7"><div class="card-h"><div><h3>Top leads</h3><p>Highest fit score among companies ready to contact</p></div><a class="link" href="#leads">See all ${icon('arrow')}</a></div>
        <div class="tl">${top.map((l, i) => {
          const p = primary(l);
          return `<button class="tl-row" type="button" data-id="${l.id}"><span class="rank">${i + 1}</span>${avatar(l)}<span class="t"><b>${esc(l.name)}</b><span>${esc([loc(l), cap(l.category)].filter(Boolean).join(' · '))}</span></span>` +
            `<span class="e mono">${esc(p && p.email ? p.email : '')}</span>${sring(l)}</button>`;
        }).join('') || '<p class="sub">No qualified leads yet.</p>'}</div></div>
      <div class="card c5"><div class="card-h"><div><h3>Where the leads are</h3><p>Hover a dot for the company, click to open it</p></div><a class="link" href="#map">Full map ${icon('arrow')}</a></div>
        <div class="map-box map-mini" id="mini-map"></div>
        <div class="chips" style="margin-top:12px"><span class="chip"><i style="width:8px;height:8px;border-radius:50%;background:var(--map-ready)"></i>Ready</span><span class="chip"><i style="width:8px;height:8px;border-radius:50%;background:var(--map-qual)"></i>Qualified, no email</span><span class="chip"><i style="width:8px;height:8px;border-radius:50%;background:var(--map-other)"></i>Not qualified</span></div></div>
    </div>
    <div class="grid">
      <div class="card c6"><div class="card-h"><div><h3>Fit score distribution</h3><p>How every company scored against your profile. Colored bars clear the bar.</p></div></div>${histogram(D.bins)}</div>
      <div class="card c6"><div class="card-h"><div><h3>Contact quality</h3><p>What kind of addresses were found and how well they check out</p></div></div>
        ${etTotal ? `<div class="donut-wrap">${donut(et, fmt(etTotal), 'emails found')}${legend(et, etTotal)}</div>` : '<p class="sub">No emails found yet. Run crawl or the contact providers.</p>'}
        ${vrTotal ? `<div class="split"><h4>Verification</h4>${stack(vr, vrTotal)}<div style="margin-top:14px">${legend(vr, vrTotal)}</div></div>` : ''}</div>
    </div>`;
    el.addEventListener('click', e => {
      const row = e.target.closest('.tl-row');
      if (row) return openLead(Number(row.getAttribute('data-id')), top);
      const st = e.target.closest('[data-stage]');
      if (st) goLeads({ stage: st.getAttribute('data-stage'), city: '', cat: '', verify: '', min: 0, q: '' });
    });
    makeMap($('#mini-map', el), { interactive: false, onBackground: () => { location.hash = '#map'; } });
  }

  // ------------------------------------------------------------------ LEAD EXPLORER
  const S = { q: '', stage: K.ready ? 'ready' : 'all', city: '', cat: '', verify: '', min: 0, sort: 'score', view: 'table', page: 1 };
  try { const v = localStorage.getItem('leadgen-view'); if (v === 'cards' || v === 'table') S.view = v; } catch (e) { /* default view */ }
  const PER = 40;
  const effView = () => (window.innerWidth < 640 ? 'cards' : S.view); // phones always get cards
  let lastView = null;
  let CURRENT = [];
  let HAY = null;
  const byName = (a, b) => String(a.name || '').localeCompare(String(b.name || ''));
  const byScore = (a, b) => (b.score == null ? -1e9 : b.score) - (a.score == null ? -1e9 : a.score) || byName(a, b);
  const SORTS = {
    score: byScore,
    name: byName,
    city: (a, b) => (a.city || '~').localeCompare(b.city || '~') || byScore(a, b),
    rating: (a, b) => (b.rating || 0) - (a.rating || 0) || (b.reviews || 0) - (a.reviews || 0),
    reviews: (a, b) => (b.reviews || 0) - (a.reviews || 0)
  };
  function hay(l) {
    if (!HAY) {
      HAY = new Map();
      LEADS.forEach(x => HAY.set(x.id, [x.name, x.category, x.industry, x.city, x.state, x.postal, x.address, x.domain, x.phone,
        (x.signals || []).map(sigLabel).join(' '), (x.people || []).map(p => [p.name, p.title, p.email].join(' ')).join(' ')].join(' ')));
      HAY.forEach((v, k) => HAY.set(k, fold(v)));
    }
    return HAY.get(l.id);
  }
  function matches(l) {
    if (S.stage === 'website' && !l.website) return false;
    if (S.stage === 'email' && !l.email) return false;
    if (S.stage === 'qualified' && !l.q) return false;
    if (S.stage === 'ready' && !l.ready) return false;
    if (S.city && cityKey(l) !== S.city) return false;
    if (S.cat && (l.category || '') !== S.cat) return false;
    if (S.verify) {
      if (S.verify === 'verified') { if (l.verify !== 'valid' && l.verify !== 'catch_all') return false; }
      else if (S.verify === 'none') { if (l.verify) return false; }
      else if (l.verify !== S.verify) return false;
    }
    if (S.min && (l.score || 0) < S.min) return false;
    if (S.q) {
      const h = hay(l);
      if (!fold(S.q).split(/\s+/).filter(Boolean).every(t => h.indexOf(t) >= 0)) return false;
    }
    return true;
  }
  function countBy(fn) {
    const m = new Map();
    LEADS.forEach(l => { const k = fn(l); if (k) m.set(k, (m.get(k) || 0) + 1); });
    return Array.from(m.entries()).sort((a, b) => b[1] - a[1]);
  }
  function select(id, label, options) {
    return `<label class="sel">${label}<select id="${id}">${options.map(o => `<option value="${esc(o[0])}">${esc(o[1])}</option>`).join('')}</select></label>`;
  }
  function filtersActive() {
    return !!(S.q || S.city || S.cat || S.verify || S.min || S.stage !== (K.ready ? 'ready' : 'all'));
  }

  function buildLeads(el) {
    const cities = countBy(cityKey), cats = countBy(l => l.category), vcount = new Map(countBy(l => l.verify || 'none'));
    const maxScore = Math.max(100, Math.ceil(LEADS.reduce((m, l) => Math.max(m, l.score || 0), 0) / 5) * 5);
    const vopts = [['', 'Any status'], ['verified', `Verified or catch-all (${fmt((vcount.get('valid') || 0) + (vcount.get('catch_all') || 0))})`]]
      .concat(['valid', 'catch_all', 'unknown', 'risky', 'unverified'].filter(k => vcount.get(k)).map(k => [k, `${VERIFY[k][0]} (${fmt(vcount.get(k))})`]))
      .concat(vcount.get('none') ? [['none', `No usable email (${fmt(vcount.get('none'))})`]] : []);
    el.innerHTML = `<div class="lx-head"><div><h2 class="h2">Lead explorer</h2><p class="sub">Search and filter every company, then open one for contacts, score breakdown and source.</p></div>
      <div class="seg" id="lx-view" role="group" aria-label="Layout"><button type="button" data-v="table">${icon('table')}Table</button><button type="button" data-v="cards">${icon('grid')}Cards</button></div></div>
    <div class="card toolbar">
      <div class="tb-row"><label class="search">${icon('search')}<input id="lx-q" type="search" placeholder="Search companies, people, emails, cities" autocomplete="off" spellcheck="false" aria-label="Search leads"><kbd>/</kbd></label>
        <div class="seg" id="lx-stage" role="group" aria-label="Pipeline stage">${STAGES.map(s => `<button type="button" data-s="${s.k}" data-tip="${esc(s.tip)}">${s.short}<small>${fmt(s.v)}</small></button>`).join('')}</div></div>
      <div class="tb-row">
        ${cities.length > 1 ? select('lx-city', 'City', [['', 'All cities']].concat(cities.map(c => [c[0], `${cityLabel(c[0])} (${fmt(c[1])})`]))) : ''}
        ${cats.length > 1 ? select('lx-cat', 'Category', [['', 'All categories']].concat(cats.map(c => [c[0], `${cap(c[0])} (${fmt(c[1])})`]))) : ''}
        ${select('lx-verify', 'Email', vopts)}
        <label class="rng">Min score<input type="range" id="lx-min" min="0" max="${maxScore}" step="5" value="0" aria-label="Minimum score"><b id="lx-min-v">0</b></label>
        ${select('lx-sort', 'Sort', [['score', 'Best score'], ['name', 'Name A to Z'], ['city', 'City'], ['rating', 'Highest rating'], ['reviews', 'Most reviews']])}
        <span class="spacer"></span><button type="button" class="btn sm" id="lx-reset" hidden>${icon('reset')}Reset filters</button>
      </div>
    </div>
    <div id="lx-body"></div>
    <div class="pager"><span class="lx-meta" id="lx-meta"></span><div class="pages" id="lx-pages"></div></div>`;

    let qt;
    $('#lx-q', el).addEventListener('input', e => { clearTimeout(qt); qt = setTimeout(() => { S.q = e.target.value.trim(); S.page = 1; renderLeads(); }, 110); });
    $('#lx-stage', el).addEventListener('click', e => { const b = e.target.closest('[data-s]'); if (b) { S.stage = b.getAttribute('data-s'); S.page = 1; renderLeads(); } });
    $('#lx-view', el).addEventListener('click', e => {
      const b = e.target.closest('[data-v]'); if (!b) return;
      S.view = b.getAttribute('data-v');
      try { localStorage.setItem('leadgen-view', S.view); } catch (err) { /* per-visit only */ }
      renderLeads();
    });
    [['lx-city', 'city'], ['lx-cat', 'cat'], ['lx-verify', 'verify'], ['lx-sort', 'sort']].forEach(p => {
      const s = $('#' + p[0], el);
      if (s) s.addEventListener('change', () => { S[p[1]] = s.value; S.page = 1; renderLeads(); });
    });
    let minFrame = 0;
    $('#lx-min', el).addEventListener('input', e => {
      S.min = Number(e.target.value); $('#lx-min-v').textContent = S.min; S.page = 1;
      if (!minFrame) minFrame = requestAnimationFrame(() => { minFrame = 0; renderLeads(); });
    });
    $('#lx-reset', el).addEventListener('click', () => { Object.assign(S, { q: '', stage: K.ready ? 'ready' : 'all', city: '', cat: '', verify: '', min: 0, page: 1 }); syncControls(); renderLeads(); });
    const body = $('#lx-body', el);
    body.addEventListener('click', e => {
      const th = e.target.closest('th[data-sort]');
      if (th) { S.sort = th.getAttribute('data-sort'); S.page = 1; syncControls(); renderLeads(); return; }
      if (e.target.closest('a,[data-copy]')) return;
      const r = e.target.closest('[data-id]');
      if (r) openLead(Number(r.getAttribute('data-id')), CURRENT);
    });
    body.addEventListener('keydown', e => {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      const r = e.target.closest('[data-id]');
      if (r) { e.preventDefault(); openLead(Number(r.getAttribute('data-id')), CURRENT); }
    });
    $('#lx-pages', el).addEventListener('click', e => {
      const b = e.target.closest('[data-p]'); if (!b) return;
      S.page = Number(b.getAttribute('data-p'));
      renderLeads();
      $('#leads').scrollIntoView({ behavior: REDUCED ? 'auto' : 'smooth', block: 'start' });
    });
    syncControls();
    renderLeads();
  }
  function syncControls() {
    if (!$('#lx-q')) return;
    $('#lx-q').value = S.q;
    [['lx-city', 'city'], ['lx-cat', 'cat'], ['lx-verify', 'verify'], ['lx-sort', 'sort']].forEach(p => { const s = $('#' + p[0]); if (s) s.value = S[p[1]]; });
    $('#lx-min').value = S.min; $('#lx-min-v').textContent = S.min;
  }
  function rowHtml(l) {
    const p = primary(l), t = tier(l);
    return `<tr tabindex="0" data-id="${l.id}">
      <td><div class="co">${avatar(l)}<div class="t"><b>${esc(l.name)}</b><span>${esc([cap(l.category), l.rating != null ? '★ ' + l.rating + (l.reviews != null ? ' (' + fmt(l.reviews) + ')' : '') : ''].filter(Boolean).join(' · '))}</span></div></div></td>
      <td class="col-loc">${loc(l) ? esc(loc(l)) : '<span class="muted">–</span>'}</td>
      <td class="col-contact cell2">${p && p.name ? `<div>${esc(p.name)}</div><span>${esc(p.title || '')}</span>` : '<span class="muted">–</span>'}</td>
      <td class="cell2">${p && p.email ? `<div class="mono">${esc(p.email)}</div>${vbadge(p)}` : '<span class="muted">No email yet</span>'}</td>
      <td><div class="scell" style="--c:${t.c}" data-tip="${esc(t.label)}"><span class="sbar"><i style="width:${clamp(l.score || 0, 0, 100)}%"></i></span><b>${l.score == null ? '–' : Math.round(l.score)}</b></div></td>
      <td class="col-sig"><div class="chips">${chipsHtml(leadChips(l), 1)}</div></td>
      <td class="go">${icon('right')}</td></tr>`;
  }
  function cardHtml(l) {
    const p = primary(l);
    return `<article class="lcard" tabindex="0" data-id="${l.id}">
      <header>${avatar(l)}<div class="t"><b>${esc(l.name)}</b><span>${esc(loc(l) || 'Location unknown')}${l.category ? ' · ' + esc(cap(l.category)) : ''}</span></div>${sring(l)}</header>
      <div class="lc-contact">${p ? `<div class="who">${esc(p.name || (p.email ? 'Shared inbox' : 'Contact'))}${p.title ? ` <small>· ${esc(p.title)}</small>` : ''}</div>` +
        `<div class="em"><span class="mono">${esc(p.email || 'No email yet')}</span>${vbadge(p)}</div>` : '<div class="who muted">No contact found yet</div>'}</div>
      <footer>${stars(l)}${chipsHtml(leadChips(l), 2)}</footer></article>`;
  }
  function pagesHtml(page, pages) {
    if (pages <= 1) return '';
    const nums = Array.from(new Set([1, 2, pages - 1, pages, page - 1, page, page + 1].filter(n => n >= 1 && n <= pages))).sort((a, b) => a - b);
    let out = `<button type="button" data-p="${page - 1}" ${page === 1 ? 'disabled' : ''} aria-label="Previous page">${icon('left')}</button>`, prev = 0;
    nums.forEach(n => { if (n - prev > 1) out += '<span class="gap">…</span>'; out += `<button type="button" data-p="${n}"${n === page ? ' aria-current="page"' : ''}>${n}</button>`; prev = n; });
    return out + `<button type="button" data-p="${page + 1}" ${page === pages ? 'disabled' : ''} aria-label="Next page">${icon('right')}</button>`;
  }
  function renderLeads() {
    const body = $('#lx-body');
    if (!body) return;
    lastView = effView();
    CURRENT = LEADS.filter(matches).sort(SORTS[S.sort] || byScore);
    const pages = Math.max(1, Math.ceil(CURRENT.length / PER));
    S.page = clamp(S.page, 1, pages);
    const from = (S.page - 1) * PER, slice = CURRENT.slice(from, from + PER);
    $$('#lx-stage [data-s]').forEach(b => b.setAttribute('aria-pressed', String(b.getAttribute('data-s') === S.stage)));
    const seg = $('#lx-stage'), on = $('#lx-stage [aria-pressed="true"]');
    if (seg && on && seg.scrollWidth > seg.clientWidth) { // narrow screens: keep the active stage in view
      const d = on.getBoundingClientRect(), r = seg.getBoundingClientRect();
      if (d.right > r.right || d.left < r.left) seg.scrollLeft += d.left - r.left - 8;
    }
    $$('#lx-view [data-v]').forEach(b => b.setAttribute('aria-pressed', String(b.getAttribute('data-v') === S.view)));
    $('#lx-reset').hidden = !filtersActive();
    if (!CURRENT.length) {
      body.innerHTML = `<div class="card empty"><div class="glyph">${icon('search')}</div><b>No companies match</b>Try a broader stage, clear the search, or reset the filters.</div>`;
    } else if (effView() === 'cards') {
      body.innerHTML = `<div class="cards">${slice.map(cardHtml).join('')}</div>`;
    } else {
      const th = (key, label, cls, arrow) => `<th class="sortable ${cls || ''}${S.sort === key ? ' sorted' : ''}" data-sort="${key}"${key === 'score' ? ' style="text-align:right"' : ''}>${label}<span class="arr">${arrow}</span></th>`;
      body.innerHTML = `<div class="tbl-wrap"><table class="leads"><thead><tr>${th('name', 'Company', '', '↑')}${th('city', 'Location', 'col-loc', '↑')}` +
        `<th class="col-contact">Contact</th><th>Email</th>${th('score', 'Score', '', '↓')}<th class="col-sig">Signals</th><th aria-hidden="true"></th></tr></thead>` +
        `<tbody>${slice.map(rowHtml).join('')}</tbody></table></div>`;
    }
    $('#lx-meta').innerHTML = CURRENT.length
      ? `Showing <b>${fmt(from + 1)}–${fmt(from + slice.length)}</b> of <b>${fmt(CURRENT.length)}</b> ${CURRENT.length === 1 ? 'company' : 'companies'}`
      : '';
    $('#lx-pages').innerHTML = pagesHtml(S.page, pages);
  }
  function goLeads(patch) {
    Object.assign(S, patch, { page: 1 });
    if ($('#lx-body')) { syncControls(); renderLeads(); }
    if (location.hash !== '#leads') location.hash = '#leads';
  }

  // ------------------------------------------------------------------ DRAWER
  const drawer = $('#drawer'), scrim = $('#scrim');
  const DR = { list: [], i: 0, back: null };
  const isOpen = () => drawer.getAttribute('aria-hidden') === 'false';
  function openLead(id, list) {
    list = list && list.length ? list : LEADS;
    let i = list.findIndex(l => l.id === id);
    if (i < 0) { list = LEADS; i = LEADS.findIndex(l => l.id === id); }
    if (i < 0) return;
    const prev = [DR.list, DR.i];
    DR.list = list; DR.i = i;
    try { renderDrawer(false); } catch (err) { DR.list = prev[0]; DR.i = prev[1]; console.error(err); return; } // never open onto a half-drawn panel
    if (!isOpen()) {
      DR.back = document.activeElement;
      scrim.hidden = false;
      drawer.setAttribute('aria-hidden', 'false');
      document.body.style.overflow = 'hidden';
      afterPaint(() => { if (isOpen()) { scrim.classList.add('on'); drawer.classList.add('open'); } });
    }
    hideTip();
    drawer.focus({ preventScroll: true });
  }
  function closeDrawer() {
    drawer.classList.remove('open');
    scrim.classList.remove('on');
    drawer.setAttribute('aria-hidden', 'true');
    document.body.style.overflow = '';
    setTimeout(() => { if (!isOpen()) scrim.hidden = true; }, 320);
    if (DR.back && DR.back.focus) DR.back.focus({ preventScroll: true });
  }
  function step(d) {
    const n = DR.i + d;
    if (n < 0 || n >= DR.list.length) return;
    const was = DR.i;
    DR.i = n;
    try { renderDrawer(true); } catch (err) { DR.i = was; console.error(err); }
  }
  function reasonRow(r, mx) {
    const m = r.match(/^([+-]?\d+(?:\.\d+)?)\s+(.+)$/);
    if (!m) return `<div class="rs" style="--c:var(--muted)"><span>${esc(r)}</span><span></span><b></b></div>`;
    const v = Number(m[1]), c = v >= 0 ? 'var(--good)' : 'var(--bad)';
    return `<div class="rs" style="--c:${c}"><span>${esc(reasonLabel(m[2]))}</span><span class="rb"><i style="--w:${((100 * Math.abs(v)) / mx).toFixed(1)}%"></i></span><b>${v > 0 ? '+' : ''}${v}</b></div>`;
  }
  function reasonLabel(s) {
    let m;
    if ((m = s.match(/^keyword '(.+)'$/))) return `Niche keyword “${m[1]}”`;
    if ((m = s.match(/^title '(.+)'$/))) return `Decision-maker title “${m[1]}”`;
    if ((m = s.match(/^email \((.+)\)$/))) return `Usable email (${((ETYPE[m[1]] || [m[1]])[0] || '').toLowerCase()})`;
    if ((m = s.match(/^no_(\w+)$/))) return 'No ' + lc(sigLabel(m[1]));
    const map = {
      website: 'Has a website', phone: 'Has a phone number', social: 'Social profiles', 'rating ok': 'Rating meets your minimum',
      'personal email': 'Personal email', verified: 'Email verified', 'catch-all': 'Catch-all domain', 'mx ok': 'Mail server responds',
      'no usable email': 'No usable email', 'only third-party email': 'Only a third-party email', 'only pattern-guessed email': 'Only a guessed email'
    };
    if (map[s]) return map[s];
    if (SIG[s]) return SIG[s];
    return cap(s);
  }
  function personHtml(p) {
    const nm = p.name || (p.email ? 'Shared inbox' : 'Contact');
    const chips = [];
    if (p.primary && !p.blocked) chips.push('<span class="badge b-primary plain">Primary contact</span>');
    if (p.email) chips.push(vbadge(p));
    if (p.type) chips.push(`<span class="chip" data-tip="${esc((ETYPE[p.type] || ETYPE.unknown)[2])}">${esc((ETYPE[p.type] || [cap(p.type)])[0])}</span>`);
    if (p.via) chips.push(p.via === 'pattern' ? '<span class="badge b-pattern plain" data-tip="Guessed from the company email pattern; verify before sending">Pattern guess</span>' : `<span class="chip">${esc(VIA[p.via] || cap(p.via))}</span>`);
    if (p.conf) chips.push(`<span class="chip">${esc(p.conf)}% confidence</span>`);
    if (p.pushed) chips.push('<span class="chip">Pushed</span>');
    const li = safeUrl(p.linkedin);
    return `<div class="person${p.primary && !p.blocked ? ' primary' : ''}${p.blocked ? ' dim' : ''}"><span class="pa">${esc(p.name ? initials(p.name) : '@')}</span>
      <div class="t"><div class="nm">${esc(nm)}${p.title ? ` <small>· ${esc(p.title)}</small>` : ''}</div>
      ${p.email ? `<div class="em mono">${esc(p.email)}</div>` : ''}${p.phone ? `<div class="em">${esc(p.phone)}</div>` : ''}
      <div class="chips">${chips.join('')}${li ? `<a class="chip" href="${esc(li)}" target="_blank" rel="noopener noreferrer">${icon('linkedin')}LinkedIn</a>` : ''}</div></div>
      ${p.email && !p.blocked ? `<button type="button" class="copy" data-copy="${esc(p.email)}" aria-label="Copy ${esc(p.email)}" data-tip="Copy email">${icon('copy')}</button>` : ''}</div>`;
  }
  function act(ic, label, href, external) {
    if (!href) return `<span class="act off" aria-disabled="true">${icon(ic)}${label}</span>`;
    return `<a class="act" href="${esc(href)}"${external ? ' target="_blank" rel="noopener noreferrer"' : ''}>${icon(ic)}${label}</a>`;
  }
  function renderDrawer(anim) {
    const l = DR.list[DR.i], t = tier(l), p = primary(l), live = p && p.email && !p.blocked ? p : null;
    const reasons = l.reasons || [];
    const mx = Math.max(1, ...reasons.map(r => { const m = r.match(/^([+-]?\d+(?:\.\d+)?)/); return m ? Math.abs(Number(m[1])) : 0; }));
    const badges = [];
    if (l.ready) badges.push('<span class="badge b-ready">Ready to contact</span>');
    else if (l.q) badges.push('<span class="badge b-qual">Qualified, needs an email</span>');
    else if (l.disq) badges.push('<span class="badge b-disq">Disqualified</span>');
    else badges.push('<span class="badge b-low">Below threshold</span>');
    if (t.k === 'hot') badges.push(`<span class="badge b-primary plain">${icon('flame')}Hot lead</span>`);
    if (l.verify === 'valid') badges.push('<span class="badge b-valid">Verified email</span>');
    const site = safeUrl(l.website), maps = safeUrl(l.maps), ref = safeUrl(l.ref);
    const address = [l.address, l.city, [l.state, l.postal].filter(Boolean).join(' '), l.country].filter(Boolean).join(', ');
    const chips = leadChips(l);
    const socials = Object.keys(l.social || {}).map(k => { const u = safeUrl(l.social[k]); return u ? `<a class="social" href="${esc(u)}" target="_blank" rel="noopener noreferrer">${icon(ICONS[k] ? k : 'link')}${esc(cap(k))}</a>` : ''; }).join('');
    const people = l.people || [];
    const hiddenPeople = people.filter(x => x.blocked).length;
    const facts = [
      address && ['Address', esc(address)],
      l.phone && ['Phone', telOf(l.phone) ? `<a href="${esc(telOf(l.phone))}">${esc(l.phone)}</a>` : esc(l.phone)],
      site && ['Website', `<a href="${esc(site)}" target="_blank" rel="noopener noreferrer">${esc(l.domain || site)}</a>`],
      l.rating != null && ['Rating', stars(l)],
      l.employees && ['Employees', esc(l.employees)],
      l.industry && l.industry !== l.category && ['Industry', esc(cap(l.industry))],
      maps && ['Map', `<a href="${esc(maps)}" target="_blank" rel="noopener noreferrer">Open listing</a>`]
    ].filter(Boolean);
    drawer.innerHTML = `<div class="dr-top"><span class="pos">Lead ${fmt(DR.i + 1)} of ${fmt(DR.list.length)}</span>
        <span class="hint"><kbd>←</kbd><kbd>→</kbd> browse <kbd>esc</kbd> close</span>
        <button type="button" class="icon-btn" data-dr="prev" aria-label="Previous lead"${DR.i === 0 ? ' disabled' : ''}>${icon('left')}</button>
        <button type="button" class="icon-btn" data-dr="next" aria-label="Next lead"${DR.i >= DR.list.length - 1 ? ' disabled' : ''}>${icon('right')}</button>
        <button type="button" class="icon-btn" data-dr="close" aria-label="Close">${icon('x')}</button></div>
      <div class="dr-body${anim ? ' swap' : ''}">
        <div class="dr-id">${avatar(l, 'lg')}<div class="t"><h2>${esc(l.name)}</h2><p>${esc([cap(l.category), loc(l)].filter(Boolean).join(' · '))}</p></div></div>
        <div class="dr-badges">${badges.join('')}</div>
        <div class="dr-actions">${act('globe', 'Website', site, true)}${act('phone', 'Call', telOf(l.phone))}` +
          `${act('mail', 'Email', live ? 'mailto:' + live.email : '')}` +
          `${live ? `<button type="button" class="act" data-copy="${esc(live.email)}">${icon('copy')}Copy email</button>` : act('copy', 'Copy email', '')}</div>
        <section class="dr-sec"><h4>Fit score</h4>
          <div class="score-box">${sring(l, 76, 7, 'lg')}<div class="t"><b>${esc(t.label)}</b><span>${l.score == null ? 'Run leadgen score to rank this company.' : `Scored ${Math.round(l.score)}; qualifies at ${THR}.`}${l.ready ? ' Ready to contact.' : ''}</span></div></div>
          ${l.disq ? `<div class="disq">${icon('alert')}<span>Disqualified: ${esc(l.disq)}</span></div>` : ''}
          ${reasons.length ? `<div class="reasons">${reasons.map(r => reasonRow(r, mx)).join('')}</div>` : ''}
        </section>
        <section class="dr-sec"><h4>Contacts<span>${fmt(people.length)}${hiddenPeople ? ` · ${hiddenPeople} won't export` : ''}</span></h4>
          ${people.length ? people.map(personHtml).join('') : '<p class="sub">No contacts yet. Run crawl or the contact providers to find one.</p>'}</section>
        <section class="dr-sec"><h4>Company</h4>${facts.length ? `<dl class="facts">${facts.map(f => `<dt>${f[0]}</dt><dd>${f[1]}</dd>`).join('')}</dl>` : '<p class="sub">No company details on file.</p>'}
          ${l.about ? `<p class="about">${esc(l.about)}</p>` : ''}</section>
        <section class="dr-sec"><h4>Website signals${l.year ? `<span>© ${esc(l.year)}</span>` : ''}</h4>
          ${l.crawl === 'ok' ? (chips.length ? `<div class="chips">${chipsHtml(chips)}</div>` : '<p class="sub">Crawled; nothing notable detected.</p>')
            : `<p class="sub">${l.crawl ? 'The crawl could not read this site.' : site ? 'Website not crawled yet.' : 'No website to crawl.'}</p>`}</section>
        ${socials ? `<section class="dr-sec"><h4>Profiles</h4><div class="socials">${socials}</div></section>` : ''}
        <section class="dr-sec"><h4>Source</h4><div class="prov">Found via <b>${esc(SOURCE[l.source] || cap(l.source) || 'unknown')}</b>` +
          `${(l.sources || []).length > 1 ? ` · also in ${esc(l.sources.filter(s => s !== l.source).map(s => SOURCE[s] || s).join(', '))}` : ''}` +
          `${ref ? `<br><a href="${esc(ref)}" target="_blank" rel="noopener noreferrer">${esc(ref.length > 70 ? ref.slice(0, 70) + '…' : ref)}</a>` : l.ref ? `<br>${esc(l.ref)}` : ''}<br>Lead ID ${l.id}</div></section>
      </div>`;
  }
  drawer.addEventListener('click', e => {
    const b = e.target.closest('[data-dr]');
    if (!b) return;
    const a = b.getAttribute('data-dr');
    if (a === 'close') closeDrawer(); else step(a === 'next' ? 1 : -1);
  });
  scrim.addEventListener('click', closeDrawer);
  let touchX = null;
  drawer.addEventListener('touchstart', e => { touchX = e.touches[0].clientX; }, { passive: true });
  drawer.addEventListener('touchend', e => {
    if (touchX == null) return;
    const dx = e.changedTouches[0].clientX - touchX;
    if (Math.abs(dx) > 70) step(dx < 0 ? 1 : -1);
    touchX = null;
  });

  // ------------------------------------------------------------------ MAP VIEW
  let fullMap = null;
  function buildMap(el) {
    const plotted = LEADS.filter(l => typeof l.lat === 'number' && typeof l.lng === 'number').length;
    const mxReady = Math.max(1, ...D.cities.map(c => c.ready));
    el.innerHTML = `<div class="lx-head"><div><h2 class="h2">Where the leads are</h2><p class="sub">Each dot is a company. Scroll to zoom, drag to pan, click a dot to open the lead.${plotted < LEADS.length ? ` ${fmt(LEADS.length - plotted)} companies have no coordinates and are not plotted.` : ''}</p></div></div>
      <div class="grid">
        <div class="card c8" style="padding:10px"><div class="map-box map-full" id="full-map"><div class="map-ctrl">
          <button type="button" class="icon-btn" data-z="in" aria-label="Zoom in">${icon('plus')}</button><button type="button" class="icon-btn" data-z="out" aria-label="Zoom out">${icon('minus')}</button><button type="button" class="icon-btn" data-z="reset" aria-label="Reset view">${icon('reset')}</button></div></div></div>
        <div class="c4" style="display:flex;flex-direction:column;gap:16px;min-width:0">
          <div class="card"><div class="card-h"><div><h3>Layers</h3><p>Show or hide each group on the map</p></div></div>
            <button type="button" class="layer" data-layer="ready" aria-pressed="true" style="--c:var(--map-ready)"><span class="dot"></span><span class="lbl">Ready to contact</span><b data-lc="ready">0</b></button>
            <button type="button" class="layer" data-layer="qual" aria-pressed="true" style="--c:var(--map-qual)"><span class="dot"></span><span class="lbl">Qualified, no email yet</span><b data-lc="qual">0</b></button>
            <button type="button" class="layer" data-layer="other" aria-pressed="true" style="--c:var(--map-other)"><span class="dot"></span><span class="lbl">Not qualified</span><b data-lc="other">0</b></button></div>
          <div class="card"><div class="card-h"><div><h3>Top cities</h3><p>Ready leads per city. Click one to list them.</p></div></div>
            <div class="city-list">${D.cities.map(c => `<button type="button" class="city" data-city="${esc(c.city + '|' + c.state)}" data-tip="${esc(`${fmt(c.ready)} ready, ${fmt(c.qualified)} qualified, ${fmt(c.total)} found`)}">` +
              `<span>${esc([c.city, c.state].filter(Boolean).join(', '))}</span><span class="hb-t"><i style="--w:${((100 * c.ready) / mxReady).toFixed(1)}%"></i></span><b>${fmt(c.ready)}</b></button>`).join('') || '<p class="sub">No city data yet.</p>'}</div></div>
        </div>
      </div>`;
    fullMap = makeMap($('#full-map', el), { interactive: true });
    if (fullMap) {
      const c = fullMap.counts();
      $$('[data-lc]', el).forEach(b => { b.textContent = fmt(c[b.getAttribute('data-lc')]); });
    }
    el.addEventListener('click', e => {
      const z = e.target.closest('[data-z]');
      if (z && fullMap) { const a = z.getAttribute('data-z'); if (a === 'reset') fullMap.reset(); else fullMap.zoom(a === 'in' ? 1.6 : 1 / 1.6); return; }
      const lay = e.target.closest('[data-layer]');
      if (lay && fullMap) { const on = lay.getAttribute('aria-pressed') !== 'true'; lay.setAttribute('aria-pressed', String(on)); fullMap.toggle(lay.getAttribute('data-layer'), on); return; }
      const city = e.target.closest('[data-city]');
      if (city) {
        const key = city.getAttribute('data-city'), row = D.cities.find(c => c.city + '|' + c.state === key);
        goLeads({ city: key, stage: row && row.ready ? 'ready' : 'all', q: '', cat: '', verify: '', min: 0 });
      }
    });
  }

  // ------------------------------------------------------------------ INSIGHTS
  function buildInsights(el) {
    const bonus = D.bonus || {};
    const bonusFor = s => {
      if (bonus['no_' + s] != null) return { txt: `${bonus['no_' + s] > 0 ? '+' : ''}${bonus['no_' + s]} if missing`, pts: bonus['no_' + s] };
      if (bonus[s] != null) return { txt: `${bonus[s] > 0 ? '+' : ''}${bonus[s]} if present`, pts: bonus[s] };
      return null;
    };
    const sigRows = D.signals.map(r => {
      const b = bonusFor(r[0]);
      return {
        label: sigLabel(r[0]), v: r[1], text: pct(r[1], K.crawled) + '%', small: fmt(r[1]),
        chip: b ? ` <span class="chip hot" style="height:20px;font-size:11px">${esc(b.txt)}</span>` : '',
        tip: `${fmt(r[1])} of ${fmt(K.crawled)} crawled sites show ${lc(sigLabel(r[0]))}; ${fmt(K.crawled - r[1])} do not`,
        c: b ? 'var(--grad)' : 'var(--accent-2)'
      };
    }).sort((a, b) => (b.chip ? 1 : 0) - (a.chip ? 1 : 0) || b.v - a.v);
    const plat = D.platforms.map(r => ({ label: PLATFORM[r[0]] || cap(r[0]), v: r[1], small: pct(r[1], K.crawled) + '%', c: r[0] === 'other' ? 'var(--neutral)' : 'var(--accent-mid)' }));
    const tiers = { hot: 0, warm: 0, fit: 0, low: 0, disq: 0 };
    LEADS.forEach(l => { tiers[tier(l).k]++; });
    const tierRows = [
      { label: `Hot (${THR + 40}+)`, v: tiers.hot, c: 'var(--accent)' }, { label: `Warm (${THR + 20}+)`, v: tiers.warm, c: 'var(--accent-mid)' },
      { label: `Good fit (${THR}+)`, v: tiers.fit, c: 'var(--accent-2)' }, { label: 'Below threshold', v: tiers.low, c: 'var(--neutral)' },
      { label: 'Disqualified', v: tiers.disq, c: 'var(--bad)' }];
    const src = D.sources.map(r => ({ label: SOURCE[r[0]] || cap(r[0]), v: r[1], small: pct(r[1], K.total) + '%' }));
    const cats = D.categories.length > 1 ? D.categories.map(r => ({ label: cap(r[0]), v: r[1], c: 'var(--accent-mid)' })) : [];
    const noSite = K.total - K.website;
    const crawl = [
      { label: 'Crawled', v: K.crawled, c: 'var(--good)' }, { label: 'Crawl failed', v: K.crawl_errors, c: 'var(--bad)' },
      { label: 'Waiting to crawl', v: K.crawl_pending, c: 'var(--warn)' }, { label: 'No website', v: noSite, c: 'var(--neutral)' }].filter(r => r.v);
    const wrows = D.weights.map(w => ({ label: WLABEL[w[0]] || cap(w[0].replace(/_/g, ' ')), v: w[1] }))
      .concat(Object.keys(bonus).map(k => ({ label: (k.indexOf('no_') === 0 ? 'No ' + lc(sigLabel(k.slice(3))) : sigLabel(k)) + ' (signal)', v: bonus[k] })));
    const pmx = Math.max(1, ...wrows.filter(w => w.v > 0).map(w => w.v)), nmx = Math.max(1, ...wrows.filter(w => w.v < 0).map(w => -w.v));
    const wHtml = wrows.map(w => {
      const c = w.v >= 0 ? 'var(--good)' : 'var(--bad)';
      const style = w.v >= 0 ? `left:33.33%;width:${((66.67 * w.v) / pmx).toFixed(2)}%` : `right:66.67%;width:${((33.33 * -w.v) / nmx).toFixed(2)}%`;
      return `<div class="w-row" style="--c:${c}"><span>${esc(w.label)}</span><span class="w-track"><i style="${style}"></i></span><b>${w.v > 0 ? '+' : ''}${w.v}</b></div>`;
    }).join('');
    const usage = D.usage.length
      ? `<table class="table-s"><thead><tr><th>Provider</th><th>Endpoint</th><th>Units</th></tr></thead><tbody>${D.usage.map(u => `<tr><td>${esc(PROVIDER[u.provider] || cap(u.provider))}</td><td class="muted">${esc(u.endpoint)}</td><td>${fmt(u.units)}</td></tr>`).join('')}</tbody></table>`
      : '<p class="sub">No paid API calls. Everything came from the free path.</p>';
    const files = D.exports.length
      ? `<div class="files">${D.exports.map(f => `<div class="file">${icon('file')}<span class="mono">${esc(f)}</span></div>`).join('')}</div>`
      : '<p class="sub">No CSV exports yet. Run <span class="mono">leadgen export</span> when the list looks right.</p>';

    el.innerHTML = `<div class="lx-head"><div><h2 class="h2">Insights</h2><p class="sub">What the crawl found, where leads came from, and how the fit score is built.</p></div></div>
      <div class="grid">
        <div class="card c7"><div class="card-h"><div><h3>Website signals</h3><p>Share of the ${fmt(K.crawled)} crawled sites showing each signal. Highlighted signals move the fit score.</p></div></div>
          ${hbars(sigRows, { max: Math.max(1, K.crawled), empty: 'Run the crawl to see website signals.' })}</div>
        <div class="card c5"><div class="card-h"><div><h3>Site platforms</h3><p>What the crawled websites are built on</p></div></div>
          ${hbars(plat, { empty: 'Run the crawl to see site platforms.' })}</div>
      </div>
      <div class="grid">
        <div class="card c4"><div class="card-h"><div><h3>Lead tiers</h3><p>Every company by fit score band</p></div></div>${hbars(tierRows)}</div>
        <div class="card c4"><div class="card-h"><div><h3>Sources</h3><p>Where each company was first found</p></div></div>${hbars(src)}
          ${cats.length ? `<div class="split"><h4>Categories</h4>${hbars(cats)}</div>` : ''}</div>
        <div class="card c4"><div class="card-h"><div><h3>Crawl coverage</h3><p>How much of the list the crawler has read</p></div></div>
          ${crawl.length ? stack(crawl, K.total) + `<div style="margin-top:16px">${legend(crawl, K.total)}</div>` : '<p class="sub">No companies yet.</p>'}</div>
      </div>
      <div class="grid">
        <div class="card c6"><div class="card-h"><div><h3>How the fit score works</h3><p>Points per factor from your profile. A company qualifies at <b>${THR}</b>.</p></div></div><div class="weights">${wHtml}</div></div>
        <div class="card c6"><div class="card-h"><div><h3>Spend, files and guardrails</h3><p>API usage so far and what has been exported</p></div></div>
          ${usage}<div class="split"><h4>Exports</h4>${files}</div>
          <div class="split"><h4>Guardrails</h4><ul class="rules">
            <li>${icon('check')}<span>Every company carries a source reference you can open.</span></li>
            <li>${icon('check')}<span>Pattern-guessed emails stay flagged until a provider verifies them.</span></li>
            <li>${icon('check')}<span>Invalid, suppressed and do-not-contact addresses never export or push.</span></li>
            <li>${icon('check')}<span>No scraping of Google Maps, LinkedIn, Yelp or Facebook pages; the crawler honors robots.txt.</span></li></ul></div></div>
      </div>`;
  }

  // ------------------------------------------------------------------ router
  const VIEWS = ['overview', 'leads', 'map', 'insights'];
  const BUILD = { overview: buildOverview, leads: buildLeads, map: buildMap, insights: buildInsights };
  const built = {};
  function moveInd() {
    const a = $('.tab[aria-selected="true"]'), ind = $('.tab-ind');
    if (!a || !ind) return;
    ind.style.width = a.offsetWidth + 'px';
    ind.style.transform = `translateX(${a.offsetLeft}px)`;
  }
  function route() {
    let v = (location.hash || '').slice(1);
    if (VIEWS.indexOf(v) < 0) v = 'overview';
    if (isOpen()) closeDrawer();
    VIEWS.forEach(x => $('#' + x).classList.toggle('active', x === v));
    $$('.tab').forEach(t => t.setAttribute('aria-selected', String(t.getAttribute('data-view') === v)));
    moveInd();
    const sec = $('#' + v);
    if (!built[v]) { BUILD[v](sec); built[v] = true; }
    reveal(sec);
    window.scrollTo({ top: 0, behavior: 'instant' });
    hideTip();
  }
  $$('.tab').forEach(t => t.addEventListener('click', () => {
    const v = t.getAttribute('data-view');
    if (location.hash === '#' + v) window.scrollTo({ top: 0, behavior: REDUCED ? 'auto' : 'smooth' }); else location.hash = '#' + v;
  }));
  window.addEventListener('hashchange', route);
  window.addEventListener('resize', () => { moveInd(); if (lastView && lastView !== effView()) renderLeads(); });

  // ------------------------------------------------------------------ keyboard
  function trapFocus(e) {
    const f = $$('a[href],button:not([disabled]),[tabindex]:not([tabindex="-1"])', drawer).filter(x => x.offsetParent !== null);
    if (!f.length) return;
    const first = f[0], last = f[f.length - 1];
    if (e.shiftKey && (document.activeElement === first || document.activeElement === drawer)) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  }
  document.addEventListener('keydown', e => {
    const tag = document.activeElement && document.activeElement.tagName;
    const typing = tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA';
    if (isOpen()) {
      if (e.key === 'Escape') { e.preventDefault(); closeDrawer(); }
      else if (e.key === 'Tab') trapFocus(e);
      else if (!typing && (e.key === 'ArrowRight' || e.key === 'j')) { e.preventDefault(); step(1); }
      else if (!typing && (e.key === 'ArrowLeft' || e.key === 'k')) { e.preventDefault(); step(-1); }
      return;
    }
    if (typing) { if (e.key === 'Escape') document.activeElement.blur(); return; }
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key === '/') { e.preventDefault(); goLeads({}); setTimeout(() => { const q = $('#lx-q'); if (q) q.focus(); }, 40); }
    else if (/^[1-4]$/.test(e.key)) location.hash = '#' + VIEWS[Number(e.key) - 1];
  });

  route();
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(moveInd);
})();
