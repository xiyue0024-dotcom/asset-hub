'use strict';

/* 静态版：索引一次性加载，分类维度与每条的分类值都由 library.js 下发
   （taxonomy.py 是单一事实源）。前端只做筛选与渲染，不重写分类规则、不联 Commons。 */

const $ = (s) => document.querySelector(s);
const esc = (s) => String(s == null ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;');

const STOP = new Set(['the', 'a', 'an', 'of', 'and', 'or', 'in', 'on', 'at', 'to', 'by',
  'for', 'with', 'tg', 'jpg', 'jpeg', 'png', 'webp', '素材', '图片']);

const SAVED_KEY = 'assethub_saved_v1';
const HIDDEN_KEY = 'assethub_hidden_v1';

const state = {
  q: '', tax: {}, saved: false, page: 1, per: 24,
  mode: 'browse', list: [], shown: 0, idx: -1, folded: false,
};

let ALL = [];
let SAVED = new Set();
let HIDDEN = new Set();
let TAXONOMY = [];
let TAX_KEYS = [];
let TAX_COUNTS = {};

/* ---------------- 工具 ---------------- */

function tokenize(q) {
  return String(q || '').toLowerCase().split(/[\s,，、/|]+/)
    .map(t => t.replace(/^[()\[\]"'.@#\-_]+/, '').replace(/[()\[\]"'.\-_]+$/, ''))
    .filter(t => t && !STOP.has(t));
}

const cdn = (u) => u || '';   // TG 图是相对路径，不走任何远程图片代理
const bigUrl = (p) => p.thumb || p.preview || '';

document.addEventListener('error', (e) => {
  const img = e.target;
  if (!img || img.tagName !== 'IMG' || !img.dataset.fb) return;
  if (img.src !== img.dataset.fb) img.src = img.dataset.fb;
}, true);

function loadLocal() {
  try { SAVED = new Set(JSON.parse(localStorage.getItem(SAVED_KEY) || '[]')); }
  catch (e) { SAVED = new Set(); }
  try { HIDDEN = new Set(JSON.parse(localStorage.getItem(HIDDEN_KEY) || '[]')); }
  catch (e) { HIDDEN = new Set(); }
  $('#statSaved').textContent = SAVED.size;
}
const persistSaved = () => {
  try { localStorage.setItem(SAVED_KEY, JSON.stringify([...SAVED])); } catch (e) {}
  $('#statSaved').textContent = SAVED.size;
};
const persistHidden = () => {
  try { localStorage.setItem(HIDDEN_KEY, JSON.stringify([...HIDDEN])); } catch (e) {}
};

const taxOf = (p, key) => {
  const i = TAX_KEYS.indexOf(key);
  return (i >= 0 && p.x && p.x[i]) ? p.x[i] : '';
};

function taxLabel(key, val) {
  const d = TAXONOMY.find(x => x.key === key);
  if (!d) return val;
  const o = d.options.find(x => x.v === val);
  return (o && o.label) || val;
}

/* ---------------- 分类筛选面板（数据驱动） ---------------- */

function renderGroups() {
  $('#taxGroups').innerHTML = TAXONOMY.map(d => {
    const counts = TAX_COUNTS[d.key] || {};
    const visible = ALL.filter(p => !HIDDEN.has(p.id));
    const chips = [{ v: '', label: '全部', n: visible.length, all: true }]
      .concat(d.options.map(o => ({ v: o.v, label: o.label, n: counts[o.v] || 0,
                                    scope: o.scope || '' })))
      .filter(o => o.v === '' || o.n > 0 || state.tax[d.key] === o.v);
    return `<div class="taxgroup" data-key="${esc(d.key)}">
      <span class="taxlabel" title="${esc(d.scope || '')}">${esc(d.label)}</span>
      <div class="chips">${chips.map(o => {
        const on = (state.tax[d.key] || '') === o.v;
        // 「全部」每行都重复同一个总数，视觉噪声大，只在悬浮提示里给数字
        return `<button class="chip${on ? ' on' : ''}${o.all ? ' chip-all' : ''}" data-v="${esc(o.v)}"
          title="${esc(o.all ? '清空' + d.label + '筛选 · 共 ' + o.n + ' 张' : (o.scope || d.scope || ''))}">${esc(o.label)}${o.all ? '' : `<i>${o.n}</i>`}</button>`;
      }).join('')}</div>
    </div>`;
  }).join('');

  $('#taxGroups').querySelectorAll('.taxgroup').forEach(g => {
    g.querySelectorAll('.chip').forEach(b => {
      b.addEventListener('click', () => {
        const key = g.dataset.key, v = b.dataset.v;
        if (!v || state.tax[key] === v) delete state.tax[key];
        else state.tax[key] = v;
        renderGroups();
        syncUrl();
        render();
      });
    });
  });
  renderSummary();
}

function renderSummary() {
  const active = TAX_KEYS.filter(k => state.tax[k]);
  const bits = active.map(k => taxLabel(k, state.tax[k]));
  if (state.q) bits.unshift(`“${state.q}”`);
  if (state.saved) bits.push('仅收藏');
  $('#filterSummary').textContent = bits.length ? bits.join(' · ') : '全部素材';
  $('#filterSummary').classList.toggle('active', bits.length > 0);
}

/* ---------------- URL 状态 ---------------- */

function syncUrl() {
  const u = new URL(location.href);
  if (state.q) u.searchParams.set('q', state.q); else u.searchParams.delete('q');
  TAX_KEYS.forEach(k => {
    if (state.tax[k]) u.searchParams.set(k, state.tax[k]);
    else u.searchParams.delete(k);
  });
  if (state.saved) u.searchParams.set('saved', '1'); else u.searchParams.delete('saved');
  history.replaceState(null, '', u.toString());
}

function readUrl() {
  const p = new URL(location.href).searchParams;
  state.q = p.get('q') || '';
  $('#q').value = state.q;
  $('#clearq').hidden = !state.q;
  state.saved = p.get('saved') === '1';
  $('#savedOnly').checked = state.saved;
  TAX_KEYS.forEach(k => { if (p.get(k)) state.tax[k] = p.get(k); });
}

/* ---------------- 检索 ---------------- */

function matchesFilters(p) {
  if (HIDDEN.has(p.id)) return false;
  for (const k of TAX_KEYS) {
    if (state.tax[k] && taxOf(p, k) !== state.tax[k]) return false;
  }
  if (state.saved && !SAVED.has(p.id)) return false;
  return true;
}

function runSearch() {
  const toks = tokenize(state.q);
  const pool = ALL.filter(matchesFilters);

  if (!toks.length) {
    state.mode = 'browse';
    return { ranked: pool.slice().sort((a, b) => b.id - a.id)
      .map(p => ({ p, pct: 100, weak: false })), exact: 0, loose: 0 };
  }

  const exact = [], loose = [];
  for (const p of pool) {
    const hay = p._st;
    const hit = toks.filter(t => hay.includes(t));
    if (!hit.length) continue;
    const pct = Math.round(hit.length / toks.length * 100);
    const rec = { p, pct, weak: hit.length < toks.length };
    if (rec.weak) loose.push(rec); else exact.push(rec);
  }
  if (exact.length) {
    state.mode = 'exact';
    return { ranked: exact, exact: exact.length, loose: loose.length };
  }
  if (loose.length) {
    state.mode = 'loose';
    return { ranked: loose.sort((a, b) => b.pct - a.pct || b.p.id - a.p.id),
             exact: 0, loose: loose.length };
  }
  state.mode = 'none';
  return { ranked: [], exact: 0, loose: 0 };
}

/* ---------------- 渲染 ---------------- */

function cardHTML(r, i) {
  const p = r.p;
  const ch = taxOf(p, 'channel');
  const region = taxOf(p, 'region');
  const frame = taxOf(p, 'frame');
  const grade = taxOf(p, 'grade');
  const on = SAVED.has(p.id);
  const badge = r.weak ? `<span class="wbadge">弱匹配 ${r.pct}%</span>` : '';
  const ar = (p.width && p.height) ? ` style="aspect-ratio:${p.width}/${p.height}"` : '';
  const label = p.title && !/^tg_/.test(p.title) ? p.title : `#${p.id} · ${ch ? '@' + ch : 'TG'}`;
  return `<figure class="card${r.weak ? ' weak' : ''}" data-i="${i}">
    <img src="${esc(p.thumb)}" data-fb="${esc(p.thumb)}"
         alt="${esc(label)}" loading="lazy" decoding="async"${ar}>
    ${badge}
    <button class="fav ${on ? 'on' : ''}" data-id="${p.id}" title="${on ? '取消收藏' : '收藏'}">${on ? '♥' : '♡'}</button>
    <figcaption class="cap">
      <span class="cap-t">${esc(label)}</span>
      <span class="cap-m">${esc([region, frame, grade].filter(Boolean).join(' · '))}${p.width ? ' · ' + p.width + '×' + p.height : ''}</span>
    </figcaption>
  </figure>`;
}

function render() {
  const { ranked } = runSearch();
  state.list = ranked;
  state.shown = Math.min(state.per, ranked.length);
  $('#grid').innerHTML = ranked.slice(0, state.shown).map((r, i) => cardHTML(r, i)).join('');

  const n = ranked.length;
  if (state.mode === 'none' || n === 0) {
    $('#notice').hidden = true;
    $('#empty').hidden = false;
    $('#emptyTitle').textContent = '没有找到匹配的素材';
    $('#emptyText').textContent = '换个频道或清空部分筛选条件试试。纯图素材没有文字描述，按来源频道浏览最有效。';
    $('#moreBtn').hidden = true;
    $('#resultMeta').textContent = '0 张素材';
    return;
  }
  $('#empty').hidden = true;
  if (state.mode === 'loose') {
    $('#notice').hidden = false;
    $('#notice').innerHTML = '<span class="n-ico">⚠</span><div>没有精确匹配，下面是<b>部分命中的弱匹配</b>，请自行判断是否可用。</div>';
  } else $('#notice').hidden = true;

  const bits = [`<b>${n.toLocaleString()}</b> 张素材`];
  if (n > state.shown) bits.push('已显示 ' + state.shown);
  $('#resultMeta').innerHTML = bits.join(' · ');
  $('#moreBtn').hidden = state.shown >= n;
  $('#statTotal').textContent = ALL.filter(p => !HIDDEN.has(p.id)).length.toLocaleString();
}

function loadMore() {
  const next = Math.min(state.shown + state.per, state.list.length);
  const html = state.list.slice(state.shown, next)
    .map((r, i) => cardHTML(r, state.shown + i)).join('');
  $('#grid').insertAdjacentHTML('beforeend', html);
  state.shown = next;
  $('#moreBtn').hidden = state.shown >= state.list.length;
  $('#resultMeta').innerHTML = `<b>${state.list.length.toLocaleString()}</b> 张素材` +
    (state.list.length > state.shown ? ` · 已显示 ${state.shown}` : '');
}

/* ---------------- 灯箱 ---------------- */

function openLB(i) {
  state.idx = i;
  renderLB();
  $('#lb').hidden = false;
  document.body.style.overflow = 'hidden';
}
function closeLB() {
  $('#lb').hidden = true;
  document.body.style.overflow = '';
  $('#lbImg').src = '';
}

function renderLB() {
  const r = state.list[state.idx];
  if (!r) return closeLB();
  const p = r.p;
  const img = $('#lbImg');
  img.onerror = null;
  img.src = cdn(bigUrl(p));
  img.alt = p.title || '';

  const ch = taxOf(p, 'channel');
  $('#lbTitle').textContent = (p.title && !/^tg_/.test(p.title)) ? p.title : `#${p.id} · ${ch ? '@' + ch : 'TG'}`;
  $('#lbBadges').innerHTML = TAXONOMY.map(d => {
    const v = taxOf(p, d.key);
    return v ? `<span class="badge${d.key === 'channel' ? '' : ' gray'}">${esc(d.label)}：${esc(taxLabel(d.key, v))}</span>` : '';
  }).filter(Boolean).join('');

  const rows = [
    ['尺寸', p.width ? `${p.width} × ${p.height}` : '—'],
    ['来源频道', ch ? '@' + ch : '—'],
    ['素材编号', '#' + p.id],
  ];
  if (state.mode === 'exact' || state.mode === 'loose') {
    rows.unshift(['匹配度', (r.weak ? '弱匹配 · ' : '') + r.pct + '%']);
  }
  $('#lbMeta').innerHTML = rows.map(([k, v]) => `<dt>${k}</dt><dd>${esc(v)}</dd>`).join('');
  const dl = $('#lbDl');
  dl.href = p.thumb || p.page || '#';
  // 同源部署（GitHub Pages 同仓库托管图片）时，download 属性可强制浏览器
  // 下载原图而非在新标签打开；跨域链接（如 t.me）则退化为普通打开。
  if (p.thumb && p.thumb.indexOf('http') !== 0) {
    dl.setAttribute('download',
      (p.thumb.split('/').pop() || 'material.jpg').replace(/[\\/:*?"<>|]/g, '_'));
  } else {
    dl.removeAttribute('download');
  }
  $('#lbCount').textContent = `${state.idx + 1} / ${state.list.length}`;

  const btn = $('#lbSave');
  const on = SAVED.has(p.id);
  btn.textContent = on ? '已收藏 ♥' : '收藏';
  btn.classList.toggle('primary', on);
  btn.onclick = () => {
    if (SAVED.has(p.id)) SAVED.delete(p.id); else SAVED.add(p.id);
    persistSaved();
    renderLB();
    const card = $(`.card[data-i="${state.idx}"] .fav`);
    if (card) {
      const now = SAVED.has(p.id);
      card.classList.toggle('on', now);
      card.textContent = now ? '♥' : '♡';
    }
    if (state.saved) render();
  };

  $('#lbHide').onclick = () => {
    HIDDEN.add(p.id);
    persistHidden();
    $('#lbHide').textContent = '已隐藏';
    setTimeout(() => {
      closeLB();
      $('#lbHide').textContent = '隐藏此图';
      renderGroups();
      render();
    }, 400);
  };

  const src = $('#lbSrc');
  if (p.page) { src.href = p.page; src.hidden = false; } else { src.hidden = true; }
}

function step(d) {
  const next = state.idx + d;
  if (next < 0) return;
  if (next >= state.shown) {
    if (state.shown < state.list.length) loadMore();
    return;
  }
  state.idx = next;
  renderLB();
}

/* ---------------- 事件 ---------------- */

function debounce(fn, ms) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

$('#q').addEventListener('input', debounce((e) => {
  state.q = e.target.value.trim();
  $('#clearq').hidden = !state.q;
  syncUrl(); render();
}, 220));

function clearQuery() {
  $('#q').value = ''; state.q = ''; $('#clearq').hidden = true;
  syncUrl(); render();
}
$('#clearq').onclick = clearQuery;

$('#savedOnly').addEventListener('change', (e) => {
  state.saved = e.target.checked;
  syncUrl(); render();
});

function resetAll() {
  state.q = ''; state.tax = {}; state.saved = false;
  $('#q').value = ''; $('#clearq').hidden = true;
  $('#savedOnly').checked = false;
  renderGroups(); syncUrl(); render();
}
$('#resetBtn').onclick = resetAll;
$('#emptyReset').onclick = resetAll;

$('#foldBtn').onclick = () => {
  state.folded = !state.folded;
  $('#taxGroups').classList.toggle('folded', state.folded);
  $('#foldBtn').textContent = state.folded ? '展开选项' : '收起选项';
  $('#foldBtn').setAttribute('aria-expanded', String(!state.folded));
};

$('#moreBtn').addEventListener('click', loadMore);

$('#grid').addEventListener('click', (e) => {
  const fav = e.target.closest('.fav');
  if (fav) {
    e.stopPropagation();
    const id = Number(fav.dataset.id);
    if (SAVED.has(id)) SAVED.delete(id); else SAVED.add(id);
    persistSaved();
    const now = SAVED.has(id);
    fav.classList.toggle('on', now);
    fav.textContent = now ? '♥' : '♡';
    if (state.saved) render();
    return;
  }
  const card = e.target.closest('.card');
  if (card) openLB(Number(card.dataset.i));
});

$('#lbPrev').onclick = () => step(-1);
$('#lbNext').onclick = () => step(1);
document.querySelectorAll('[data-close]').forEach(el => el.addEventListener('click', closeLB));

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && !$('#lb').hidden) return closeLB();
  if ($('#lb').hidden && e.key === '/' && document.activeElement !== $('#q')) {
    e.preventDefault(); $('#q').focus(); return;
  }
  if (!$('#lb').hidden) {
    if (e.key === 'ArrowLeft') step(-1);
    if (e.key === 'ArrowRight') step(1);
  }
});

new IntersectionObserver((entries) => {
  if (entries[0].isIntersecting && state.shown < state.list.length) loadMore();
}, { rootMargin: '600px' }).observe($('#sentinel'));

/* ---------------- 启动 ---------------- */

(function boot() {
  loadLocal();
  document.body.classList.add('is-searching');
  try {
    const data = window.__ASSET_LIB__;
    if (!data || !data.items) throw new Error('素材索引未加载');
    TAXONOMY = data.taxonomy || [];
    TAX_KEYS = data.tax_keys || TAXONOMY.map(d => d.key);
    TAX_COUNTS = data.tax_counts || {};

    ALL = data.items.map(x => {
      const p = {
        id: x.i, title: x.t, descr: x.d, thumb: x.th, page: x.pg,
        width: x.w, height: x.h, artist: x.ar, tags: x.k || '', x: x.x || [],
      };
      // 纯图没有文案，把分类值、频道、编号、原帖链接都纳入检索
      p._st = [p.title, p.descr, p.tags, p.artist, '#' + p.id, p.page]
        .concat(p.x).join(' ').toLowerCase();
      return p;
    });

    $('#statUpdate').textContent = data.updated ? data.updated.slice(5) : '—';
    $('#statTotal').textContent = ALL.length.toLocaleString();
    $('#qinfo').textContent = `已归类 ${ALL.length.toLocaleString()} 张 · ${TAXONOMY.length} 个维度`;
    $('#footInfo').textContent = `素材来自 Telegram 频道，共 ${ALL.length.toLocaleString()} 张`;

    readUrl();
    renderGroups();
    render();
    document.body.classList.remove('is-searching');
  } catch (err) {
    document.body.classList.remove('is-searching');
    $('#resultMeta').textContent = '素材索引加载失败，请刷新重试';
    console.error(err);
  }
})();
