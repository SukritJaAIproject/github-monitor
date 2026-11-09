'use strict';
// หน้าจอของ GitHub Monitor: อ่านข้อมูลจากโปรแกรมในเครื่อง (127.0.0.1) แล้ววาดกราฟด้วย SVG เอง
// ไม่โหลดไลบรารีจากอินเทอร์เน็ต จึงเปิดดูได้แม้ออฟไลน์
// ข้อความบนหน้าจออยู่ใน i18n.js สลับไทย/อังกฤษได้ที่ปุ่มมุมขวาบน
(() => {
  const PARAMS = new URLSearchParams(location.search);
  const KEY = PARAMS.get('k') || '';
  const DICT = window.GM_I18N || { th: {}, en: {} };
  const LANGS = ['th', 'en'];
  const LOCALES = { th: 'th-TH-u-ca-gregory', en: 'en-GB' };
  const $ = (id) => document.getElementById(id);
  const NF = new Intl.NumberFormat('en-US');
  const num = (x) => NF.format(Math.round(x || 0));
  const CF = new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 });
  const tickFmt = (top) => (v) => (top >= 10000 ? CF.format(v) : num(v));
  const PF = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 });
  const pct = (x) => (x > 0 ? '+' : '') + PF.format(x * 100) + '%';
  let dShort;
  let dLong;
  let stamp;
  const utc = (d) => new Date(d + 'T00:00:00Z');
  const addDays = (d, n) => new Date(utc(d).getTime() + n * 86400000).toISOString().slice(0, 10);
  const todayUTC = () => new Date().toISOString().slice(0, 10);
  const r1 = (v) => Math.round(v * 10) / 10;
  const SVG = 'http://www.w3.org/2000/svg';
  const TOKEN_URL = 'https://github.com/settings/personal-access-tokens/new';
  // ข้อผิดพลาดที่แก้ได้ด้วยการใส่ token ใหม่
  const TOKEN_ERRORS = new Set(['unauthorized', 'no_traffic', 'token']);
  const RANGES = ['14', '30', '90', 'all'];
  const RELEASES_SHOWN = 12;
  const SECTIONS = ['overview', 'daily', 'downloads', 'by-repo', 'sources'];
  const reduceMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // ค่าที่จำไว้ในเบราว์เซอร์นี้ (ไม่สำคัญ ถ้าอ่านไม่ได้ก็ใช้ค่าเริ่มต้น)
  function prefGet(k, def) {
    try {
      const v = localStorage.getItem('gm.' + k);
      return v === null ? def : v;
    } catch (_) { return def; }
  }
  function prefSet(k, v) {
    try { localStorage.setItem('gm.' + k, v); } catch (_) { /* ไม่จำเป็น */ }
  }

  const savedRange = prefGet('range', '30');
  const S = {
    lang: 'th', langKnown: false, st: null, hist: null, loadedAt: null, repo: '',
    range: RANGES.includes(savedRange) ? savedRange : '30',
    view: { views: 'chart', clones: 'chart', releases: 'chart', cumulative: 'chart' },
    sort: { key: 'visitors_14d', dir: -1 }, q: '', fails: 0, forceSetup: false, names: new Set(),
    allReleases: false, ended: false, uninstalled: null,
  };

  // ---------- ภาษา ----------
  // t('key', a, b) แทน {0} {1} ด้วยค่าที่ให้มา
  function t(key, ...args) {
    let s = (DICT[S.lang] || {})[key];
    if (s === undefined) s = (DICT.th || {})[key];
    if (s === undefined) return key;
    if (!args.length) return s;
    return s.replace(/\{b?(\d+)\}/g, (m, i) => (args[+i] === undefined ? m : String(args[+i])));
  }

  function makeFormatters() {
    const loc = LOCALES[S.lang] || LOCALES.th;
    dShort = new Intl.DateTimeFormat(loc, { day: 'numeric', month: 'short', timeZone: 'UTC' });
    dLong = new Intl.DateTimeFormat(loc, { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });
    stamp = new Intl.DateTimeFormat(loc, { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });
  }

  // ข้อความคงที่ในหน้า: data-i18n = ข้อความ, data-i18n-html = ข้อความที่มี <b>/<code>, data-i18n-attr = "attr:key;attr:key"
  function applyStatic() {
    document.querySelectorAll('[data-i18n]').forEach((e) => { e.textContent = t(e.dataset.i18n); });
    // ใช้กับข้อความคงที่ใน i18n.js เท่านั้น ไม่เคยใส่ข้อมูลที่ได้จาก GitHub
    document.querySelectorAll('[data-i18n-html]').forEach((e) => { e.innerHTML = t(e.dataset.i18nHtml); });
    document.querySelectorAll('[data-i18n-attr]').forEach((e) => {
      for (const pair of e.dataset.i18nAttr.split(';')) {
        const [attr, key] = pair.split(':');
        if (attr && key) e.setAttribute(attr.trim(), t(key.trim()));
      }
    });
    document.querySelectorAll('.lang-btn').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.lang === S.lang)));
  }

  function setLang(lang, save) {
    S.lang = LANGS.includes(lang) ? lang : 'th';
    document.documentElement.lang = S.lang;
    makeFormatters();
    applyStatic();
    renderOffline();
    // จำภาษาไว้ใน URL ด้วย กดรีโหลดแล้วยังเป็นภาษาเดิม
    try {
      const u = new URL(location.href);
      u.searchParams.set('l', S.lang);
      history.replaceState(history.state, '', u.href);
    } catch (_) { /* ไม่จำเป็น */ }
    if (S.st) renderChrome();
    if (S.hist) renderData();
    if (save) {
      api('/api/settings', 'POST', { lang: S.lang }).catch(() => {});
      poll(); // ขอข้อความจากโปรแกรม (สถานะ ข้อผิดพลาด) เป็นภาษาใหม่
    }
  }

  // ---------- เครื่องมือเล็ก ๆ ----------
  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }

  function icon(name, cls) {
    const s = document.createElementNS(SVG, 'svg');
    s.setAttribute('class', 'ic' + (cls ? ' ' + cls : ''));
    s.setAttribute('aria-hidden', 'true');
    const u = document.createElementNS(SVG, 'use');
    u.setAttribute('href', '#' + name);
    s.append(u);
    return s;
  }

  async function api(path, method = 'GET', body) {
    const res = await fetch(path, {
      method,
      headers: { 'X-GM-Key': KEY, 'X-GM-Lang': S.lang, 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    let data = {};
    try { data = await res.json(); } catch (_) { /* ไม่มีเนื้อหา */ }
    if (!res.ok) throw new Error(data.error || 'HTTP ' + res.status);
    return data;
  }

  // ---------- วนถามสถานะ (ทำหน้าที่เป็นสัญญาณว่าหน้าต่างยังเปิดอยู่ด้วย) ----------
  let timer = null;
  function later(ms) { clearTimeout(timer); timer = setTimeout(poll, ms); }

  async function poll() {
    if (S.ended) return;
    try {
      const st = await api('/api/state');
      S.fails = 0;
      $('offline').hidden = true;
      S.st = st;
      if (!S.langKnown) {
        // เปิดจากลิงก์ที่ไม่ได้บอกภาษา: ใช้ภาษาที่เลือกไว้ครั้งก่อน
        S.langKnown = true;
        if (LANGS.includes(st.lang) && st.lang !== S.lang) {
          setLang(st.lang, false);
          return poll();
        }
      }
      renderChrome();
      if (st.configured && (S.hist === null || st.collected_at !== S.loadedAt)) {
        S.hist = await api('/api/history');
        S.loadedAt = st.collected_at;
        renderData();
        renderChrome();
      }
      later(st.progress && st.progress.running ? 1500 : 15000);
    } catch (e) {
      if (S.ended) return;
      S.fails += 1;
      if (S.fails >= 2) showOffline();
      later(5000);
    }
  }

  function showOffline() {
    $('offline').hidden = false;
    $('dash').hidden = true;
    $('setup').hidden = true;
    $('banner').hidden = true;
    $('tabs').hidden = true;
    $('btn-refresh').hidden = true;
  }

  function renderOffline() {
    const u = S.uninstalled;
    $('offline-title').textContent = t(u ? 'uninstalled_title' : 'offline_title');
    if (!u) $('offline-text').textContent = t('offline_text');
    else $('offline-text').textContent = u.length ? t('uninstalled_notes', u.join(' / ')) : t('uninstalled_text');
  }

  // ---------- แถบบน แถบแจ้งเตือน และหน้าตั้งค่า ----------
  function setBanner(kind, text, action, progress) {
    const b = $('banner');
    if (!kind) {
      b.hidden = true;
      return;
    }
    b.hidden = false;
    b.className = 'alert ' + kind;
    b.setAttribute('role', kind === 'error' ? 'alert' : 'status');
    $('banner-icon').setAttribute('href', kind === 'error' ? '#i-error' : kind === 'warn' ? '#i-alert' : '#i-info');
    $('banner-text').textContent = text;
    $('banner-progress').hidden = progress === undefined;
    if (progress !== undefined) $('banner-bar').style.width = progress + '%';
    const a = $('banner-action');
    a.hidden = !action;
    if (action) {
      a.textContent = action.text;
      a.onclick = action.run;
    }
  }

  function renderChrome() {
    const st = S.st;
    const setup = !st.configured || S.forceSetup;
    $('sub-account').textContent = st.login ? '@' + st.login : t('not_connected');
    $('sub-updated').textContent = st.collected_at ? t('updated_at', stamp.format(new Date(st.collected_at))) : t('never_updated');
    $('setup').hidden = !setup;
    $('dash').hidden = setup || !st.configured;
    $('tabs').hidden = setup || !st.configured;
    $('btn-cancel-token').hidden = !(st.configured && S.forceSetup);
    const p = st.progress || {};
    const rb = $('btn-refresh');
    rb.hidden = !st.configured;
    rb.disabled = !!p.running;
    rb.classList.toggle('busy', !!p.running);
    $('btn-refresh-text').textContent = t(p.running ? 'refreshing' : 'refresh');
    $('dash').classList.toggle('refreshing', !!p.running);

    if (p.running) {
      const share = p.total ? Math.round((100 * p.done) / p.total) : 6;
      setBanner('info', (p.message || t('progress_default')) + (p.total ? t('progress_count', p.done, p.total) : ''), null, share);
    } else if (p.last_error) {
      const fix = TOKEN_ERRORS.has(p.last_error_code);
      setBanner('error', t('collect_failed', p.last_error), { text: t(fix ? 'new_token_btn' : 'retry'), run: fix ? changeToken : refreshNow });
    } else if (S.hist && S.hist.errors && Object.keys(S.hist.errors).length) {
      const names = Object.keys(S.hist.errors).sort();
      setBanner('warn', t('repo_errors', names.length, names.slice(0, 3).join(', ') + (names.length > 3 ? ' …' : '')));
    } else {
      setBanner(null);
    }

    $('set-account').textContent = st.login ? '@' + st.login : t('not_connected_short');
    $('set-avatar').textContent = st.login ? st.login.charAt(0).toUpperCase() : '?';
    $('set-private').checked = !!st.show_private;
    const sch = st.schedule || {};
    $('set-schedule').textContent = sch.text || '—';
    $('btn-schedule').hidden = !sch.available;
    $('btn-schedule').textContent = t(sch.enabled ? 'schedule_off_btn' : 'schedule_on_btn');
    const ins = st.install || {};
    $('install-note').hidden = !(ins.available && !ins.installed && !ins.has_copy);
    if (!ins.available) $('set-install').textContent = t('install_win_only');
    else if (ins.installed) $('set-install').textContent = t('installed_at', ins.dir);
    else if (ins.has_copy) $('set-install').textContent = t('installed_at_portable', ins.dir);
    else $('set-install').textContent = t('not_installed');
    $('btn-install').hidden = !ins.available || ins.installed;
    $('btn-install').textContent = t(ins.has_copy ? 'reinstall_btn' : 'install_btn');
    $('btn-uninstall').hidden = !(ins.available && (ins.installed || ins.has_copy));
    $('set-datadir').textContent = st.data_dir || '—';
    $('set-version').textContent = 'GitHub Monitor ' + (st.version || '');
    updateNav();
  }

  // ---------- ข้อมูลและการกรอง ----------
  function visibleRepos() {
    const all = (S.hist && S.hist.repos) || [];
    return all.filter((r) => (S.st && S.st.show_private) || !r.private);
  }

  function renderData() {
    if (!S.hist || !S.st) return;
    const repos = visibleRepos();
    S.names = new Set(repos.map((r) => r.repo));
    if (S.repo && !S.names.has(S.repo)) S.repo = '';
    const sel = $('repo-select');
    const sorted = [...S.names].sort((a, b) => a.localeCompare(b));
    sel.replaceChildren(new Option(t('all_repos'), ''), ...sorted.map((n) => new Option(n, n)));
    sel.value = S.repo;
    renderOverview(repos);
    renderCharts();
    renderRepoTable();
    renderSources();
  }

  // 14 วันล่าสุดที่เก็บได้ (ทุก repo ที่แสดง) สำหรับแผงด้านบนและการ์ด clone
  function lastWindow(a, b) {
    const rows = (S.hist.daily || []).filter((d) => S.names.has(d.repo));
    let anchor = '';
    for (const d of rows) if (d.date > anchor) anchor = d.date;
    if (!anchor) anchor = (S.hist.collected_at || '').slice(0, 10) || todayUTC();
    const by = new Map();
    for (const d of rows) {
      const o = by.get(d.date) || { a: 0, b: 0 };
      o.a += d[a] || 0;
      o.b += d[b] || 0;
      by.set(d.date, o);
    }
    const today = todayUTC();
    const out = [];
    for (let i = 13; i >= 0; i--) {
      const date = addDays(anchor, -i);
      const v = by.get(date) || { a: 0, b: 0 };
      out.push({ date, a: v.a, b: v.b, partial: date === today });
    }
    return out;
  }

  // ยอดรายวันตามช่วงเวลาที่เลือก วันที่โปรแกรมไม่ได้เก็บข้อมูลจะเป็นช่องว่าง (missing) ไม่ใช่ 0
  function dailySeries(a, b) {
    const rows = (S.hist.daily || []).filter((d) => S.names.has(d.repo));
    if (!rows.length) return [];
    const known = new Set();
    let first = rows[0].date;
    let last = rows[0].date;
    for (const d of rows) {
      known.add(d.date);
      if (d.date < first) first = d.date;
      if (d.date > last) last = d.date;
    }
    let start = first;
    if (S.range !== 'all') {
      const s = addDays(last, -(Number(S.range) - 1));
      if (s > start) start = s;
    }
    const m = new Map();
    for (const d of rows) {
      if (d.date < start || (S.repo && d.repo !== S.repo)) continue;
      const o = m.get(d.date) || { a: 0, b: 0 };
      o.a += d[a] || 0;
      o.b += d[b] || 0;
      m.set(d.date, o);
    }
    const recent = addDays(last, -13); // GitHub ส่งครบ 14 วันล่าสุดเสมอ
    const today = todayUTC();
    const out = [];
    for (let d = start; d <= last; d = addDays(d, 1)) {
      const v = m.get(d);
      out.push({ date: d, a: v ? v.a : 0, b: v ? v.b : 0, missing: !known.has(d) && d < recent, partial: d === today });
    }
    return out;
  }

  function snapshotSeries(onlySelected) {
    const by = new Map();
    for (const s of (S.hist.snapshots || [])) {
      if (!S.names.has(s.repo) || (onlySelected && S.repo && s.repo !== S.repo)) continue;
      const o = by.get(s.date) || { date: s.date, inst: 0, all: 0, stars: 0 };
      o.inst += s.downloads_installer || 0;
      o.all += s.downloads_all || 0;
      o.stars += s.stars || 0;
      by.set(s.date, o);
    }
    let pts = [...by.values()].sort((x, y) => x.date.localeCompare(y.date));
    if (onlySelected && S.range !== 'all' && pts.length) {
      const from = addDays(pts[pts.length - 1].date, -(Number(S.range) - 1));
      pts = pts.filter((p) => p.date >= from);
    }
    return pts;
  }

  // 7 วันเต็มล่าสุดเทียบ 7 วันก่อนหน้า (ไม่นับวันนี้ตามเวลา UTC เพราะยังนับไม่ครบวัน)
  function trend() {
    const today = todayUTC();
    const daily = (S.hist.daily || []).filter((d) => S.names.has(d.repo));
    const days = [...new Set(daily.map((d) => d.date))].filter((d) => d < today).sort();
    if (days.length < 14) return null;
    const last = new Set(days.slice(-7));
    const prev = new Set(days.slice(-14, -7));
    let a = 0;
    let b = 0;
    for (const d of daily) {
      if (last.has(d.date)) a += d.views;
      else if (prev.has(d.date)) b += d.views;
    }
    return b ? (a - b) / b : null;
  }

  const dayHead = (p) => dLong.format(utc(p.date)) + (p.partial ? ' (' + t('tip_partial') + ')' : '');

  // ---------- ภาพรวม ----------
  function renderOverview(repos) {
    const collected = !!S.hist.collected_at;
    $('k-own').hidden = !collected;
    if (!collected) {
      // ยังไม่เคยดึงข้อมูลสำเร็จ: แสดงขีดแทนเลข 0 ที่อาจทำให้เข้าใจผิด
      for (const id of ['k-views', 'k-install', 'k-clones', 'k-stars', 'k-forks', 'k-repos']) $(id).textContent = '—';
      $('k-visitors-line').textContent = t('first_collect');
      $('k-all-line').textContent = '';
      $('k-cloners-line').textContent = '';
      $('k-trend').hidden = true;
      for (const id of ['hero-strip', 'top-repos', 'spark-install', 'spark-clones', 'spark-stars']) $(id).replaceChildren();
      $('top-empty').hidden = true;
      return;
    }
    const sum = (k) => repos.reduce((n, r) => n + (r[k] || 0), 0);
    $('k-views').textContent = num(sum('views_14d'));
    $('k-visitors-line').textContent = t('hero_visitors', num(sum('visitors_14d')));
    const tr = trend();
    $('k-trend').hidden = tr === null;
    if (tr !== null) {
      $('k-trend').className = 'delta ' + (tr > 0 ? 'up' : tr < 0 ? 'down' : '');
      $('k-trend-icon').setAttribute('href', tr < 0 ? '#i-down' : '#i-up');
      $('k-trend-value').textContent = pct(tr);
    }
    renderTopRepos(repos); // ก่อนวาดแถบ เพราะความสูงของแถบขึ้นกับรายการด้านขวา
    drawStrip($('hero-strip'), lastWindow('views', 'visitors'));

    $('k-install').textContent = num(sum('downloads_installer'));
    $('k-all-line').textContent = t('kpi_all_line', num(sum('downloads_all')));
    $('k-clones').textContent = num(sum('clones_14d'));
    $('k-cloners-line').textContent = t('kpi_cloners_line', num(sum('cloners_14d')));
    $('k-stars').textContent = num(sum('stars'));
    $('k-forks').textContent = num(sum('forks'));
    $('k-repos').textContent = num(repos.length);
    const snaps = snapshotSeries(false);
    drawSparkLine($('spark-install'), snaps.map((s) => s.inst), t('spark_install_aria'));
    drawSparkCols($('spark-clones'), lastWindow('clones', 'cloners'), t('spark_clones_aria'));
    drawSparkLine($('spark-stars'), snaps.map((s) => s.stars), t('spark_stars_aria'));
  }

  function renderTopRepos(repos) {
    const list = $('top-repos');
    list.replaceChildren();
    const top = repos.filter((r) => r.views_14d > 0)
      .sort((a, b) => b.views_14d - a.views_14d || b.visitors_14d - a.visitors_14d || a.repo.localeCompare(b.repo))
      .slice(0, 5);
    $('top-empty').hidden = top.length > 0;
    const max = Math.max(1, ...top.map((r) => r.views_14d));
    for (const r of top) {
      const li = el('li');
      const btn = el('button', 'top-row');
      btn.type = 'button';
      btn.title = t('focus_repo');
      const bar = el('span', 'top-bar');
      const fill = el('span', 'top-fill');
      fill.style.width = Math.max(2, (100 * r.views_14d) / max) + '%';
      bar.append(fill);
      btn.append(el('span', 'top-name', r.repo), el('span', 'top-val', num(r.views_14d)), bar, el('span', 'top-uq', t('top_unique', num(r.visitors_14d))));
      btn.addEventListener('click', () => focusRepo(r.repo));
      li.append(btn);
      list.append(li);
    }
  }

  function focusRepo(name) {
    S.repo = name;
    $('repo-select').value = name;
    renderCharts();
    renderSources();
    renderRepoTable();
    $('daily').scrollIntoView({ behavior: reduceMotion() ? 'auto' : 'smooth', block: 'start' });
  }

  // ---------- เครื่องมือวาด SVG ----------
  function svgEl(tag, attrs, parent) {
    const e = document.createElementNS(SVG, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    if (parent) parent.append(e);
    return e;
  }

  function svgText(parent, s, attrs) {
    const e = svgEl('text', attrs, parent);
    e.textContent = s;
    return e;
  }

  function measure(svg, strings, cls = 'tick') {
    const e = svgEl('text', { class: cls, x: -9999, y: -9999 }, svg);
    let w = 0;
    for (const s of strings) {
      e.textContent = s;
      w = Math.max(w, e.getComputedTextLength());
    }
    e.remove();
    return Math.ceil(w);
  }

  // แท่งแนวตั้ง: มุมมน 4px เฉพาะปลายข้อมูล ฐานเป็นมุมเหลี่ยม
  function colPath(x, y0, w, h, r) {
    if (!(h > 0) || !(w > 0)) return '';
    const rr = Math.min(r, w / 2, h);
    const y = y0 - h;
    return `M${r1(x)},${r1(y0)}V${r1(y + rr)}A${r1(rr)},${r1(rr)} 0 0 1 ${r1(x + rr)},${r1(y)}H${r1(x + w - rr)}A${r1(rr)},${r1(rr)} 0 0 1 ${r1(x + w)},${r1(y + rr)}V${r1(y0)}Z`;
  }

  // แท่งแนวนอน: ปลายขวามน เฉพาะชิ้นสุดท้ายของแท่งซ้อน
  function rowPath(x, y, w, h, r) {
    if (!(w > 0)) return '';
    const rr = Math.min(r, h / 2, w);
    return `M${r1(x)},${r1(y)}H${r1(x + w - rr)}A${r1(rr)},${r1(rr)} 0 0 1 ${r1(x + w)},${r1(y + rr)}V${r1(y + h - rr)}A${r1(rr)},${r1(rr)} 0 0 1 ${r1(x + w - rr)},${r1(y + h)}H${r1(x)}Z`;
  }

  const rectPath = (x, y, w, h) => (w > 0 ? `M${r1(x)},${r1(y)}h${r1(w)}v${r1(h)}h${r1(-w)}Z` : '');

  // ขีดบนแกนเป็นจำนวนเต็มที่อ่านง่าย (1, 2, 5, 10, 20 ...)
  function niceTicks(max, count = 4) {
    if (!(max > 0)) return [0, 1];
    const raw = max / count;
    const pow = Math.pow(10, Math.floor(Math.log10(raw)));
    let step = [1, 2, 5, 10].map((m) => m * pow).find((s) => s >= raw) || 10 * pow;
    step = Math.max(1, Math.round(step));
    const top = Math.ceil(max / step) * step;
    const out = [];
    for (let v = 0; v <= top; v += step) out.push(v);
    return out;
  }

  function empty(box, msg) {
    box.append(el('p', 'empty', msg));
  }

  const tipEl = $('tip');
  // rows: [รูปสัญลักษณ์ 'bar'|'line'|null, สี 's1'|'s2'|'so', ค่า, ชื่อ] ค่ามาก่อนชื่อ
  function showTip(evt, head, rows) {
    tipEl.replaceChildren(el('div', 'tip-head', head));
    for (const [shape, cls, value, label] of rows) {
      const r = el('div', 'tip-row');
      if (shape) r.append(el('i', 'tip-key ' + shape + ' ' + cls));
      if (value !== '') r.append(el('b', '', value));
      r.append(el('span', '', label));
      tipEl.append(r);
    }
    tipEl.hidden = false;
    const w = tipEl.offsetWidth;
    const hh = tipEl.offsetHeight;
    let x = evt.clientX + 14;
    let y = evt.clientY - hh - 12;
    if (x + w > window.innerWidth - 8) x = evt.clientX - w - 14;
    if (y < 8) y = evt.clientY + 16;
    tipEl.style.left = Math.max(8, x) + 'px';
    tipEl.style.top = y + 'px';
  }
  function hideTip() { tipEl.hidden = true; }

  // แถบ 14 วันในแผงด้านบน
  function drawStrip(box, pts) {
    box.replaceChildren();
    const W = Math.max(240, box.clientWidth);
    const H = Math.max(132, box.clientHeight);
    const mt = 22;
    const mb = 24;
    const y0 = H - mb;
    const max = Math.max(1, ...pts.map((p) => p.a));
    const svg = svgEl('svg', { viewBox: `0 0 ${W} ${H}`, width: '100%', height: H, role: 'img', 'aria-label': t('aria_hero_strip') }, box);
    const step = W / pts.length;
    const bw = Math.max(4, Math.min(24, step * 0.6));
    const xl = (i) => step * i + (step - bw) / 2;
    const hgt = (v) => (v > 0 ? Math.max(3, (y0 - mt) * (v / max)) : 0);
    svgEl('line', { x1: 0, x2: W, y1: y0 + 0.5, y2: y0 + 0.5, class: 'base' }, svg);
    const cols = pts.map((p, i) => svgEl('path', { d: colPath(xl(i), y0, bw, hgt(p.a), 4), class: 'col' + (p.partial ? ' partial' : '') }, svg));
    let mi = 0;
    pts.forEach((p, i) => { if (p.a > pts[mi].a) mi = i; });
    if (pts[mi].a > 0) svgText(svg, num(pts[mi].a), { x: xl(mi) + bw / 2, y: y0 - hgt(pts[mi].a) - 8, 'text-anchor': 'middle', class: 'v' });
    const last = pts[pts.length - 1];
    svgText(svg, dShort.format(utc(pts[0].date)), { x: xl(0), y: H - 4, 'text-anchor': 'start', class: 't' });
    if (W >= 360) svgText(svg, dShort.format(utc(pts[7].date)), { x: xl(7) + bw / 2, y: H - 4, 'text-anchor': 'middle', class: 't' });
    svgText(svg, last.partial ? t('today') : dShort.format(utc(last.date)), { x: xl(pts.length - 1) + bw, y: H - 4, 'text-anchor': 'end', class: 't' });
    pts.forEach((p, i) => {
      const h = svgEl('rect', { x: step * i, y: 0, width: step, height: H, class: 'hit' }, svg);
      h.addEventListener('pointermove', (e) => {
        cols.forEach((c, j) => c.classList.toggle('dim', j !== i));
        showTip(e, dayHead(p), [['bar', 'nb', num(p.a), t('legend_views')], [null, '', num(p.b), t('legend_visitors')]]);
      });
      h.addEventListener('pointerleave', () => {
        cols.forEach((c) => c.classList.remove('dim'));
        hideTip();
      });
    });
  }

  // เส้นเล็กในการ์ด (ต้องมีอย่างน้อย 2 จุด)
  function drawSparkLine(box, vals, aria) {
    box.replaceChildren();
    if (vals.length < 2) {
      box.hidden = true;
      return;
    }
    box.hidden = false;
    const W = Math.max(120, box.clientWidth);
    const H = 40;
    const lo = Math.min(...vals);
    const hi = Math.max(...vals);
    const x = (i) => 4 + ((W - 8) * i) / (vals.length - 1);
    const y = (v) => (hi === lo ? H / 2 : 4 + (H - 8) * (1 - (v - lo) / (hi - lo)));
    const svg = svgEl('svg', { viewBox: `0 0 ${W} ${H}`, width: '100%', height: H, role: 'img', 'aria-label': aria }, box);
    svgEl('path', { d: vals.map((v, i) => `${i ? 'L' : 'M'}${r1(x(i))},${r1(y(v))}`).join(''), class: 'sl' }, svg);
    svgEl('circle', { cx: x(vals.length - 1), cy: y(vals[vals.length - 1]), r: 4, class: 'sd' }, svg);
  }

  // แท่งเล็ก 14 วันในการ์ด clone
  function drawSparkCols(box, pts, aria) {
    box.replaceChildren();
    if (!pts.some((p) => p.a > 0)) {
      box.hidden = true;
      return;
    }
    box.hidden = false;
    const W = Math.max(120, box.clientWidth);
    const H = 40;
    const max = Math.max(1, ...pts.map((p) => p.a));
    const step = W / pts.length;
    const bw = Math.max(3, Math.min(14, step * 0.6));
    let now = pts.length - 1;
    while (now > 0 && pts[now].partial) now -= 1;
    const svg = svgEl('svg', { viewBox: `0 0 ${W} ${H}`, width: '100%', height: H, role: 'img', 'aria-label': aria }, box);
    pts.forEach((p, i) => {
      const h = p.a > 0 ? Math.max(2, (H - 2) * (p.a / max)) : 0;
      svgEl('path', { d: colPath(step * i + (step - bw) / 2, H, bw, h, 3), class: 'sc' + (i === now ? ' now' : '') + (p.partial ? ' partial' : '') }, svg);
    });
  }

  // ---------- กราฟในส่วนรายวันและยอดดาวน์โหลด ----------
  function renderCharts() {
    if (!S.hist) return;
    const v = dailySeries('views', 'visitors');
    const c = dailySeries('clones', 'cloners');
    if (S.view.views === 'table') dailyTable($('chart-views'), v, t('legend_views'), t('legend_visitors'));
    else drawDaily($('chart-views'), v, { a: t('legend_views'), b: t('legend_visitors'), aria: t('views_chart_title') });
    if (S.view.clones === 'table') dailyTable($('chart-clones'), c, t('legend_clones'), t('legend_cloners'));
    else drawDaily($('chart-clones'), c, { a: t('legend_clones'), b: t('legend_cloners'), aria: t('clones_chart_title') });

    const pick = (r) => S.names.has(r.repo) && (!S.repo || r.repo === S.repo);
    const rel = (S.hist.releases || []).filter((r) => pick(r) && r.downloads_all > 0)
      .sort((a, b) => b.published.localeCompare(a.published) || a.tag.localeCompare(b.tag));
    const more = $('btn-more-releases');
    more.hidden = rel.length <= RELEASES_SHOWN || S.view.releases === 'table';
    more.textContent = S.allReleases ? t('more_less', RELEASES_SHOWN) : t('more_all', rel.length);
    if (S.view.releases === 'table') releasesTable($('chart-releases'), rel);
    else drawReleases($('chart-releases'), S.allReleases ? rel : rel.slice(0, RELEASES_SHOWN));

    const pts = snapshotSeries(true);
    $('dl-few').hidden = pts.length >= 2 || S.view.cumulative === 'table';
    if (S.view.cumulative === 'table') {
      tableView($('chart-cumulative'), [t('th_date'), t('legend_installer'), t('legend_all_files')],
        pts.slice().reverse().map((p) => [dLong.format(utc(p.date)), num(p.inst), num(p.all)]));
    } else {
      drawCumulative($('chart-cumulative'), pts);
    }

    document.querySelectorAll('.view-toggle').forEach((g) => {
      g.querySelectorAll('button').forEach((b) => b.setAttribute('aria-pressed', String(S.view[g.dataset.chart] === b.dataset.view)));
    });
    document.querySelectorAll('#range button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.range === S.range)));
  }

  // กราฟรายวัน: แท่ง = จำนวนครั้ง, เส้น = จำนวนคนไม่ซ้ำ
  function drawDaily(box, pts, o) {
    box.replaceChildren();
    if (!pts.length) return empty(box, t('no_data'));
    const W = Math.max(300, box.clientWidth);
    const H = 250;
    const mt = 18;
    const mb = 26;
    const mr = 6;
    const max = Math.max(1, ...pts.map((p) => (p.missing ? 0 : Math.max(p.a, p.b))));
    const ticks = niceTicks(max);
    const top = ticks[ticks.length - 1];
    const fmt = tickFmt(top);
    const svg = svgEl('svg', { viewBox: `0 0 ${W} ${H}`, width: '100%', height: H, role: 'img', 'aria-label': o.aria }, box);
    const ml = measure(svg, ticks.map(fmt)) + 12;
    const y = (v) => mt + (H - mt - mb) * (1 - v / top);
    const y0 = y(0);
    const n = pts.length;
    const step = (W - ml - mr) / n;
    const bw = Math.max(1, Math.min(24, step * 0.62, step - 2));
    const cx = (i) => ml + step * (i + 0.5);
    for (const tk of ticks) {
      svgEl('line', { x1: ml, x2: W - mr, y1: y(tk), y2: y(tk), class: tk ? 'grid-line' : 'axis-line' }, svg);
      svgText(svg, fmt(tk), { x: ml - 10, y: y(tk), dy: '0.32em', 'text-anchor': 'end', class: 'tick' });
    }
    // วันที่ไม่ได้เก็บข้อมูลติดกันรวมเป็นแถบเดียว
    let gs = -1;
    pts.forEach((p, i) => {
      if (p.missing && gs < 0) gs = i;
      if (gs >= 0 && (!p.missing || i === n - 1)) {
        const end = p.missing ? i + 1 : i;
        svgEl('rect', { x: ml + step * gs, y: mt, width: step * (end - gs), height: y0 - mt, class: 'gap-mark' }, svg);
        gs = -1;
      }
    });
    const bars = pts.map((p, i) => (p.missing ? null : svgEl('path', {
      d: colPath(cx(i) - bw / 2, y0, bw, y0 - y(p.a), 4), class: 'bar f1' + (p.partial ? ' partial' : ''),
    }, svg)));
    let d = '';
    let pen = false;
    pts.forEach((p, i) => {
      if (p.missing) {
        pen = false;
        return;
      }
      d += `${pen ? 'L' : 'M'}${r1(cx(i))},${r1(y(p.b))}`;
      pen = true;
    });
    svgEl('path', { d, class: 'line l2' }, svg);
    if (n <= 45 && step >= 10) pts.forEach((p, i) => { if (!p.missing) svgEl('circle', { cx: cx(i), cy: y(p.b), r: 4, class: 'dot f2' }, svg); });
    // ป้ายค่าเฉพาะวันที่สูงสุด
    let mi = -1;
    pts.forEach((p, i) => { if (!p.missing && p.a > 0 && (mi < 0 || p.a > pts[mi].a)) mi = i; });
    if (mi >= 0) svgText(svg, num(pts[mi].a), { x: cx(mi), y: y(pts[mi].a) - 8, 'text-anchor': 'middle', class: 'value' });
    const labels = pts.map((p) => dShort.format(utc(p.date)));
    const lw = measure(svg, labels) + 16;
    const every = Math.max(1, Math.ceil(lw / step));
    pts.forEach((p, i) => {
      if ((n - 1 - i) % every) return;
      const x = cx(i);
      let anchor = 'middle';
      let tx = x;
      if (x + lw / 2 > W) { anchor = 'end'; tx = W - mr; } else if (x - lw / 2 < ml - 8) { anchor = 'start'; tx = Math.max(ml - 8, x - 6); }
      svgText(svg, labels[i], { x: tx, y: H - 6, 'text-anchor': anchor, class: 'tick' });
    });
    const cross = svgEl('line', { x1: 0, x2: 0, y1: mt, y2: y0, class: 'cross', visibility: 'hidden' }, svg);
    pts.forEach((p, i) => {
      const h = svgEl('rect', { x: ml + step * i, y: 0, width: step, height: H - mb, class: 'hit' }, svg);
      h.addEventListener('pointermove', (e) => {
        cross.setAttribute('x1', cx(i));
        cross.setAttribute('x2', cx(i));
        cross.setAttribute('visibility', 'visible');
        bars.forEach((b, j) => { if (b) b.classList.toggle('dim', !p.missing && j !== i); });
        const rows = p.missing ? [[null, '', '', t('tip_missing')]] : [['bar', 's1', num(p.a), o.a], ['line', 's2', num(p.b), o.b]];
        showTip(e, dayHead(p), rows);
      });
      h.addEventListener('pointerleave', () => {
        cross.setAttribute('visibility', 'hidden');
        bars.forEach((b) => { if (b) b.classList.remove('dim'); });
        hideTip();
      });
    });
  }

  function tableView(box, cols, rows) {
    box.replaceChildren();
    if (!rows.length) return empty(box, t('no_data'));
    const wrap = el('div', 'table-box chart-table');
    const table = el('table', 'table');
    const head = el('thead');
    const hr = el('tr');
    cols.forEach((c, i) => hr.append(el('th', i === 0 ? 'left' : '', c)));
    head.append(hr);
    const body = el('tbody');
    for (const r of rows) {
      const tr = el('tr');
      r.forEach((v, i) => tr.append(el('td', i === 0 ? 'left' : '', v)));
      body.append(tr);
    }
    table.append(head, body);
    wrap.append(table);
    box.append(wrap);
  }

  function dailyTable(box, pts, labA, labB) {
    tableView(box, [t('th_date'), labA, labB], pts.slice().reverse().map((p) => [
      dayHead(p), p.missing ? '—' : num(p.a), p.missing ? '—' : num(p.b),
    ]));
  }

  // ป้ายชื่อ release: ถ้าทุก release ขึ้นต้นเหมือนกัน ตัดส่วนนั้นออก ชื่อเต็มยังอยู่ใน tooltip และตาราง
  function releaseLabels(rows) {
    const multi = new Set(rows.map((r) => r.repo)).size > 1;
    let cut = 0;
    if (!multi && rows.length > 1) {
      const f = rows[0].tag;
      let n = f.length;
      for (const r of rows) {
        let i = 0;
        while (i < n && r.tag[i] === f[i]) i++;
        n = i;
      }
      const at = Math.max(f.lastIndexOf('-', n - 1), f.lastIndexOf('_', n - 1));
      if (at >= 3 && rows.every((r) => r.tag.length > at + 1)) cut = at + 1;
    }
    return rows.map((r) => (multi ? r.repo + ' / ' + r.tag : r.tag.slice(cut)));
  }

  function releasesTable(box, rows) {
    const multi = new Set(rows.map((r) => r.repo)).size > 1;
    tableView(box, [t('th_release'), t('th_published'), t('legend_installer'), t('kind_package'), t('legend_other'), t('total')],
      rows.map((r) => [multi ? r.repo + ' / ' + r.tag : r.tag, r.published ? dLong.format(utc(r.published)) : '—',
        num(r.downloads_installer), num(r.downloads_package), num(r.downloads_other), num(r.downloads_all)]));
  }

  // ยอดดาวน์โหลดแยก release: แท่งแนวนอนซ้อนตามชนิดไฟล์ เว้นช่อง 2px ระหว่างชนิด
  function drawReleases(box, rows) {
    box.replaceChildren();
    if (!rows.length) return empty(box, t('no_release_downloads'));
    const labels = releaseLabels(rows);
    const W = Math.max(300, box.clientWidth);
    const rowH = 30;
    const bh = 14;
    const mb = 24;
    const H = rows.length * rowH + mb;
    const svg = svgEl('svg', { viewBox: `0 0 ${W} ${H}`, width: '100%', height: H, role: 'img', 'aria-label': t('aria_releases') }, box);
    const labelW = Math.min(measure(svg, labels, 'label'), Math.floor(W * 0.4));
    const ml = labelW + 16;
    const xmax = Math.max(1, ...rows.map((r) => r.downloads_all));
    const ticks = niceTicks(xmax, Math.max(2, Math.floor((W - ml) / 90)));
    const top = ticks[ticks.length - 1];
    const fmt = tickFmt(top);
    const endW = measure(svg, [num(xmax)], 'value') + 12;
    const x = (v) => ml + (W - ml - endW) * (v / top);
    const yb = (i) => i * rowH;
    const hl = svgEl('rect', { x: 0, y: 0, width: W, height: rowH, rx: 6, class: 'row-hl', visibility: 'hidden' }, svg);
    for (const tk of ticks) {
      svgEl('line', { x1: x(tk), x2: x(tk), y1: 0, y2: H - mb, class: tk ? 'grid-line' : 'axis-line' }, svg);
      svgText(svg, fmt(tk), { x: x(tk), y: H - 6, 'text-anchor': 'middle', class: 'tick' });
    }
    const kinds = [['downloads_installer', 'f1', 's1', t('legend_installer')], ['downloads_package', 'f2', 's2', t('kind_package')], ['downloads_other', 'fo', 'so', t('legend_other')]];
    const groups = rows.map((r, i) => {
      const g = svgEl('g', { class: 'bar' }, svg);
      const lab = svgText(svg, labels[i], { x: ml - 14, y: yb(i) + rowH / 2, dy: '0.32em', 'text-anchor': 'end', class: 'label' });
      let s = labels[i];
      while (s.length > 3 && lab.getComputedTextLength() > labelW + 0.5) {
        s = s.slice(0, -2);
        lab.textContent = s + '…';
      }
      const segs = kinds.filter(([k]) => (r[k] || 0) > 0);
      const yy = yb(i) + (rowH - bh) / 2;
      let acc = 0;
      segs.forEach(([k, cls], si) => {
        const v = r[k];
        const x0 = x(acc);
        const lastSeg = si === segs.length - 1;
        const w = Math.max(1, x(acc + v) - x0 - (lastSeg ? 0 : 2));
        svgEl('path', { d: lastSeg ? rowPath(x0, yy, w, bh, 4) : rectPath(x0, yy, w, bh), class: cls }, g);
        acc += v;
      });
      svgText(svg, num(r.downloads_all), { x: x(r.downloads_all) + 6, y: yb(i) + rowH / 2, dy: '0.32em', class: 'value' });
      return g;
    });
    rows.forEach((r, i) => {
      const h = svgEl('rect', { x: 0, y: yb(i), width: W, height: rowH, class: 'hit' }, svg);
      h.addEventListener('pointermove', (e) => {
        hl.setAttribute('y', yb(i));
        hl.setAttribute('visibility', 'visible');
        groups.forEach((g, j) => g.classList.toggle('dim', j !== i));
        const lines = kinds.map(([k, , sw, label]) => ['bar', sw, num(r[k]), label]);
        lines.push([null, '', num(r.downloads_all), t('total')]);
        showTip(e, r.tag + (r.published ? ' (' + dLong.format(utc(r.published)) + ')' : ''), lines);
      });
      h.addEventListener('pointerleave', () => {
        hl.setAttribute('visibility', 'hidden');
        groups.forEach((g) => g.classList.remove('dim'));
        hideTip();
      });
    });
  }

  // ยอดดาวน์โหลดสะสมตามวันที่เก็บข้อมูล
  function drawCumulative(box, pts) {
    box.replaceChildren();
    if (!pts.length || !Math.max(...pts.map((p) => p.all))) return empty(box, t('no_downloads'));
    const W = Math.max(300, box.clientWidth);
    const H = 230;
    const mt = 14;
    const mb = 26;
    const max = Math.max(...pts.map((p) => p.all));
    const ticks = niceTicks(max);
    const top = ticks[ticks.length - 1];
    const fmt = tickFmt(top);
    const svg = svgEl('svg', { viewBox: `0 0 ${W} ${H}`, width: '100%', height: H, role: 'img', 'aria-label': t('aria_cumulative') }, box);
    const ml = measure(svg, ticks.map(fmt)) + 12;
    const endW = measure(svg, [num(max)], 'value') + 16;
    const t0 = utc(pts[0].date).getTime();
    const t1 = utc(pts[pts.length - 1].date).getTime();
    const x = (p) => (pts.length > 1 && t1 > t0 ? ml + 8 + (W - endW - ml - 8) * ((utc(p.date).getTime() - t0) / (t1 - t0)) : (ml + W - endW) / 2);
    const y = (v) => mt + (H - mt - mb) * (1 - v / top);
    for (const tk of ticks) {
      svgEl('line', { x1: ml, x2: W - 4, y1: y(tk), y2: y(tk), class: tk ? 'grid-line' : 'axis-line' }, svg);
      svgText(svg, fmt(tk), { x: ml - 10, y: y(tk), dy: '0.32em', 'text-anchor': 'end', class: 'tick' });
    }
    const last = pts[pts.length - 1];
    const series = [['all', 'o', t('legend_all_files')], ['inst', '1', t('legend_installer')]];
    for (const [k, c] of series) {
      if (pts.length > 1) svgEl('path', { d: pts.map((p, i) => `${i ? 'L' : 'M'}${r1(x(p))},${r1(y(p[k]))}`).join(''), class: 'line l' + c }, svg);
      if (pts.length <= 45) pts.forEach((p) => svgEl('circle', { cx: x(p), cy: y(p[k]), r: p === last ? 4.5 : 3, class: 'dot f' + c }, svg));
    }
    let yi = y(last.inst);
    let ya = y(last.all);
    if (Math.abs(yi - ya) < 16) { if (yi >= ya) yi = ya + 16; else ya = yi + 16; }
    svgText(svg, num(last.inst), { x: x(last) + 10, y: yi, dy: '0.32em', class: 'value' });
    svgText(svg, num(last.all), { x: x(last) + 10, y: ya, dy: '0.32em', class: 'value' });
    const ends = pts.length > 1 ? [pts[0], last] : [last];
    ends.forEach((p, i) => svgText(svg, dShort.format(utc(p.date)), {
      x: x(p), y: H - 6, 'text-anchor': pts.length > 1 ? (i === 0 ? 'start' : 'end') : 'middle', class: 'tick',
    }));
    const cross = svgEl('line', { x1: 0, x2: 0, y1: mt, y2: H - mb, class: 'cross', visibility: 'hidden' }, svg);
    const hit = svgEl('rect', { x: ml, y: 0, width: W - ml, height: H - mb, class: 'hit' }, svg);
    hit.addEventListener('pointermove', (e) => {
      const rect = svg.getBoundingClientRect();
      const mx = ((e.clientX - rect.left) / rect.width) * W;
      const p = pts.reduce((best, q) => (Math.abs(x(q) - mx) < Math.abs(x(best) - mx) ? q : best), pts[0]);
      cross.setAttribute('x1', x(p));
      cross.setAttribute('x2', x(p));
      cross.setAttribute('visibility', 'visible');
      showTip(e, dLong.format(utc(p.date)), [['line', 's1', num(p.inst), t('legend_installer')], ['line', 'so', num(p.all), t('legend_all_files')]]);
    });
    hit.addEventListener('pointerleave', () => {
      cross.setAttribute('visibility', 'hidden');
      hideTip();
    });
  }

  // ---------- ตาราง ----------
  function renderRepoTable() {
    if (!S.hist) return;
    const tb = $('repo-rows');
    tb.replaceChildren();
    const all = visibleRepos();
    const q = S.q.trim().toLowerCase();
    const { key, dir } = S.sort;
    const rows = all
      .filter((r) => !q || r.repo.toLowerCase().includes(q) || (r.description || '').toLowerCase().includes(q))
      .sort((a, b) => {
        const va = a[key];
        const vb = b[key];
        const c = typeof va === 'number' ? va - vb : String(va || '').localeCompare(String(vb || ''));
        return dir * c || a.repo.localeCompare(b.repo);
      });
    const max = Math.max(1, ...all.map((r) => r.views_14d));
    for (const r of rows) {
      const tr = el('tr', S.repo && r.repo === S.repo ? 'selected' : '');
      const name = el('td', 'left');
      const head = el('div', 'repo-name');
      const link = el('button', 'link');
      link.type = 'button';
      link.title = t('open_on_github');
      link.append(document.createTextNode(r.repo), icon('i-external'));
      link.addEventListener('click', () => openTarget(`https://github.com/${S.hist.owner}/${r.repo}`));
      head.append(link);
      if (r.private) head.append(el('span', 'pill', t('badge_private')));
      if (r.fork) head.append(el('span', 'pill', t('badge_fork')));
      name.append(head);
      if (r.description) {
        const d = el('span', 'desc', r.description);
        d.title = r.description;
        name.append(d);
      }
      const views = el('td');
      const wrap = el('span', 'cellbar');
      if (r.views_14d) {
        const b = el('span', 'bar-in');
        b.style.width = Math.max(3, (52 * r.views_14d) / max) + 'px';
        wrap.append(b);
      }
      wrap.append(num(r.views_14d));
      views.append(wrap);
      tr.append(name, views);
      for (const [k, opt] of [['visitors_14d'], ['clones_14d', 1], ['cloners_14d', 1], ['downloads_installer'], ['stars'], ['forks', 1]]) {
        tr.append(el('td', opt ? 'opt' : '', num(r[k])));
      }
      tr.append(el('td', 'opt', r.pushed || '—'));
      tb.append(tr);
    }
    if (!rows.length) {
      const tr = el('tr', 'no-match');
      const td = el('td', '', t('no_match'));
      td.colSpan = 9;
      tr.append(td);
      tb.append(tr);
    }
    document.querySelectorAll('#repo-table th').forEach((th) => {
      th.setAttribute('aria-sort', th.dataset.key === key ? (dir > 0 ? 'ascending' : 'descending') : 'none');
    });
  }

  function fillSources(id, list, kind) {
    const tb = $(id);
    tb.replaceChildren();
    for (const r of list) {
      const tr = el('tr');
      const td = el('td', 'left');
      const box = el('div', 'src');
      const mark = el('span', 'src-icon');
      if (kind === 'ref') mark.textContent = String(r.referrer || '?').replace(/^www\./i, '').charAt(0).toUpperCase();
      else mark.append(icon('i-file'));
      const main = el('span', 'src-main', kind === 'ref' ? r.referrer : r.path);
      if (kind === 'path' && r.title) main.title = r.title;
      box.append(mark, main, el('span', 'src-repo', r.repo));
      td.append(box);
      tr.append(td, el('td', '', num(r.views)), el('td', '', num(r.visitors)));
      tb.append(tr);
    }
  }

  function renderSources() {
    if (!S.hist) return;
    const pick = (list) => list
      .filter((r) => S.names.has(r.repo) && (!S.repo || r.repo === S.repo))
      .sort((a, b) => b.views - a.views || b.visitors - a.visitors)
      .slice(0, 100);
    const refs = pick(S.hist.referrers || []);
    const paths = pick(S.hist.paths || []);
    fillSources('ref-rows', refs, 'ref');
    fillSources('path-rows', paths, 'path');
    $('ref-empty').hidden = refs.length > 0;
    $('path-empty').hidden = paths.length > 0;
    $('ref-rows').closest('.table-box').hidden = !refs.length;
    $('path-rows').closest('.table-box').hidden = !paths.length;
  }

  function renderVisuals() {
    if (!S.hist || !S.st || $('dash').hidden) return;
    renderOverview(visibleRepos());
    renderCharts();
  }

  // ---------- เมนูส่วนต่าง ๆ ของหน้า ----------
  let navRaf = 0;
  function updateNav() {
    navRaf = 0;
    if ($('dash').hidden) return;
    let cur = SECTIONS[0];
    for (const id of SECTIONS) {
      if ($(id).getBoundingClientRect().top <= 170) cur = id;
    }
    if (window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 4) cur = SECTIONS[SECTIONS.length - 1];
    document.querySelectorAll('#tabs a').forEach((a) => a.setAttribute('aria-current', String(a.getAttribute('href') === '#' + cur)));
  }
  window.addEventListener('scroll', () => { if (!navRaf) navRaf = requestAnimationFrame(updateNav); }, { passive: true });

  // ---------- หน้าต่างยืนยันและข้อความแจ้งผล ----------
  function ask(o) {
    return new Promise((resolve) => {
      const dlg = $('confirm');
      $('confirm-title').textContent = o.title;
      $('confirm-text').textContent = o.body;
      $('confirm-ok').textContent = o.ok;
      $('confirm-check-row').hidden = !o.check;
      $('confirm-check').checked = false;
      $('confirm-check-label').textContent = o.check || '';
      $('confirm-check-note').textContent = o.checkNote || '';
      let ok = false;
      $('confirm-ok').onclick = () => {
        ok = true;
        dlg.close();
      };
      $('confirm-cancel').onclick = () => dlg.close();
      dlg.onclose = () => resolve({ ok, checked: $('confirm-check').checked });
      dlg.showModal();
      $('confirm-cancel').focus();
    });
  }

  function showToasts() {
    const box = $('toasts');
    try {
      // ให้ข้อความลอยอยู่เหนือหน้าต่างตั้งค่าที่เปิดอยู่
      if (box.matches(':popover-open')) box.hidePopover();
      box.showPopover();
    } catch (_) {
      box.classList.add('open');
    }
  }

  function hideToasts() {
    const box = $('toasts');
    try { if (box.matches(':popover-open')) box.hidePopover(); } catch (_) { /* ไม่รองรับ popover */ }
    box.classList.remove('open');
  }

  function toast(text, kind = 'ok') {
    const box = $('toasts');
    const item = el('div', 'toast ' + kind);
    item.setAttribute('role', kind === 'error' ? 'alert' : 'status');
    const close = el('button', 'btn icon');
    close.type = 'button';
    close.title = t('dismiss');
    close.setAttribute('aria-label', t('dismiss'));
    close.append(icon('i-x'));
    item.append(icon(kind === 'error' ? 'i-error' : 'i-check'), el('div', 'toast-text', text), close);
    const remove = () => {
      if (!item.isConnected) return;
      item.remove();
      if (!box.children.length) hideToasts();
    };
    close.addEventListener('click', remove);
    box.append(item);
    showToasts();
    setTimeout(remove, kind === 'error' ? 12000 : 6000);
  }

  // ---------- คำสั่งจากปุ่ม ----------
  async function refreshNow() {
    try {
      await api('/api/collect', 'POST', {});
    } catch (e) { /* แถบแจ้งเตือนจะแสดงข้อผิดพลาดเอง */ }
    poll();
  }

  function openTarget(target) {
    api('/api/open', 'POST', { target }).catch(() => {});
  }

  function changeToken() {
    const dlg = $('settings');
    if (dlg.open) dlg.close();
    S.forceSetup = true;
    $('token-error').hidden = true;
    renderChrome();
    window.scrollTo({ top: 0 });
    $('token-input').focus();
  }

  async function saveToken() {
    const input = $('token-input');
    const btn = $('btn-save-token');
    const err = $('token-error');
    err.hidden = true;
    const token = input.value.trim();
    if (!token) {
      err.textContent = t('paste_first');
      err.hidden = false;
      return;
    }
    btn.disabled = true;
    btn.textContent = t('checking_token');
    try {
      await api('/api/token', 'POST', { token });
      input.value = '';
      S.forceSetup = false;
      S.hist = null;
      toast(t('token_saved'));
      poll();
    } catch (e) {
      err.textContent = e.message;
      err.hidden = false;
    } finally {
      btn.disabled = false;
      btn.textContent = t('save_token');
    }
  }

  async function removeToken() {
    const r = await ask({ title: t('remove_token_title'), body: t('remove_token_body'), ok: t('remove_token_ok') });
    if (!r.ok) return;
    try {
      await api('/api/token', 'DELETE');
      toast(t('token_removed'));
    } catch (e) {
      toast(e.message, 'error');
    }
    $('settings').close();
    poll();
  }

  async function doInstall() {
    const btns = [$('btn-install'), $('btn-install-top')];
    btns.forEach((b) => { b.disabled = true; });
    try {
      const r = await api('/api/install', 'POST', {});
      const notes = (r.warnings || []).map((w) => t('install_notes', w));
      toast([t('install_done')].concat(notes).join('\n'));
    } catch (e) {
      toast(t('install_failed', e.message), 'error');
    } finally {
      btns.forEach((b) => { b.disabled = false; });
      poll();
    }
  }

  async function doUninstall() {
    const a = await ask({
      title: t('uninstall_title'), body: t('uninstall_body'), ok: t('uninstall_btn'),
      check: t('uninstall_delete_data'), checkNote: t('uninstall_keep_note'),
    });
    if (!a.ok) return;
    try {
      const r = await api('/api/uninstall', 'POST', { delete_data: a.checked });
      S.ended = true;
      clearTimeout(timer);
      $('settings').close();
      S.uninstalled = r.warnings || [];
      renderOffline();
      $('install-note').hidden = true;
      showOffline();
    } catch (e) {
      toast(t('uninstall_failed', e.message), 'error');
    }
  }

  async function toggleSchedule() {
    const want = !(S.st && S.st.schedule && S.st.schedule.enabled);
    const b = $('btn-schedule');
    b.disabled = true;
    try {
      await api('/api/schedule', 'POST', { enabled: want });
      toast(t(want ? 'schedule_on_done' : 'schedule_off_done'));
    } catch (e) {
      toast(e.message, 'error');
    } finally {
      b.disabled = false;
      poll();
    }
  }

  $('btn-refresh').addEventListener('click', refreshNow);
  $('btn-settings').addEventListener('click', () => $('settings').showModal());
  $('btn-open-token').addEventListener('click', () => openTarget(TOKEN_URL));
  $('btn-save-token').addEventListener('click', saveToken);
  $('token-input').addEventListener('keydown', (e) => { if (e.key === 'Enter') saveToken(); });
  $('btn-cancel-token').addEventListener('click', () => {
    S.forceSetup = false;
    renderChrome();
    renderVisuals();
  });
  $('btn-change-token').addEventListener('click', changeToken);
  $('btn-remove-token').addEventListener('click', removeToken);
  $('btn-open-data').addEventListener('click', () => openTarget('datadir'));
  $('btn-install').addEventListener('click', doInstall);
  $('btn-install-top').addEventListener('click', doInstall);
  $('btn-uninstall').addEventListener('click', doUninstall);
  $('btn-schedule').addEventListener('click', toggleSchedule);
  document.querySelectorAll('[data-close]').forEach((b) => b.addEventListener('click', () => b.closest('dialog').close()));
  // กดพื้นที่นอกหน้าต่างตั้งค่าเพื่อปิด
  $('settings').addEventListener('click', (e) => { if (e.target === e.currentTarget) e.currentTarget.close(); });
  document.querySelectorAll('.lang-btn').forEach((b) => b.addEventListener('click', () => {
    if (b.dataset.lang !== S.lang) setLang(b.dataset.lang, true);
  }));
  $('set-private').addEventListener('change', async (e) => {
    const on = e.target.checked;
    try {
      await api('/api/settings', 'POST', { show_private: on });
      S.st.show_private = on;
      renderData();
    } catch (err) {
      e.target.checked = !on;
    }
  });
  $('btn-more-releases').addEventListener('click', () => {
    S.allReleases = !S.allReleases;
    renderCharts();
  });
  $('repo-select').addEventListener('change', (e) => {
    S.repo = e.target.value;
    renderCharts();
    renderSources();
    renderRepoTable();
  });
  document.querySelectorAll('#range button').forEach((b) => b.addEventListener('click', () => {
    S.range = b.dataset.range;
    prefSet('range', S.range);
    renderCharts();
  }));
  document.querySelectorAll('.view-toggle button').forEach((b) => b.addEventListener('click', () => {
    S.view[b.parentElement.dataset.chart] = b.dataset.view;
    renderCharts();
  }));
  $('repo-search').addEventListener('input', (e) => {
    S.q = e.target.value;
    renderRepoTable();
  });
  document.querySelectorAll('#repo-table th button').forEach((b) => {
    b.addEventListener('click', () => {
      const key = b.parentElement.dataset.key;
      S.sort = { key, dir: S.sort.key === key ? -S.sort.dir : key === 'repo' ? 1 : -1 };
      renderRepoTable();
    });
  });

  // วาดกราฟใหม่เมื่อขนาดหน้าต่างเปลี่ยน
  let resizeTimer = null;
  let lastWidth = 0;
  new ResizeObserver((entries) => {
    const w = Math.round(entries[0].contentRect.width);
    if (w === lastWidth) return;
    lastWidth = w;
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(renderVisuals, 120);
  }).observe($('dash'));

  // บอกโปรแกรมเมื่อหน้าต่างกำลังปิด
  // sendBeacon ถูกออกแบบมาให้ส่งได้แม้แท็บกำลังปิด (ใส่รหัสใน URL เพราะ sendBeacon ตั้ง header เองไม่ได้)
  window.addEventListener('pagehide', () => {
    try {
      if (navigator.sendBeacon && navigator.sendBeacon('/api/bye?k=' + encodeURIComponent(KEY))) return;
      fetch('/api/bye', { method: 'POST', keepalive: true, headers: { 'X-GM-Key': KEY } });
    } catch (_) { /* ปิดอยู่แล้ว */ }
  });

  // ภาษาเริ่มต้น: จากลิงก์ที่โปรแกรมเปิด (?l=th หรือ ?l=en) ถ้าไม่มีจะใช้ค่าที่โปรแกรมจำไว้เมื่อถามสถานะครั้งแรก
  const urlLang = PARAMS.get('l');
  S.langKnown = LANGS.includes(urlLang);
  setLang(S.langKnown ? urlLang : 'th', false);
  poll();
})();
