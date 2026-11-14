'use strict';

/* 本地版：分类维度、选项、计数全部由 /api/facets 下发（taxonomy.py 单一事实源）。
   前端不硬编码任何分类选项，也不保留 Commons 采集/署名相关功能。 */

const $ = (s) => document.querySelector(s);
const esc = (s) => String(s == null ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;');

const state = {
  q: '', tax: {}, saved: false,
  page: 1, per: 24, total: 0, items: [], loading: false, idx: -1,
  mode: 'browse', folded: false,
};

let TAXONOMY = [];   // [{key,label,scope,options:[{v,label,scope}]}]
let TAX_KEYS = [];
let TAX_COUNTS = {};
let TAX_TOTAL = 0;

const proxyUrl = (u) => '/img?u=' + encodeURIComponent(u || '');

document.addEventListener('error', (e) => {
  const img = e.target;
  if (!img || img.tagName !== 'IMG') return;
  const fb = img.dataset.fb;
  if (fb && img.src !== fb && !img.dataset.t1) { img.dataset.t1 = '1'; img.src = fb; }
}, true);

function debounce(fn, ms) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

async function api(path, params) {
  const u = new URL(path, location.origin);
  Object.entries(params || {}).forEach(([k, v]) => {
    if (v !== '' && v != null) u.searchParams.set(k, v);
  });
  const r = await fetch(u.toString());
  return r.json();
}

const setMeta = (html) => { $('#resultMeta').innerHTML = html; };

/* ---------------- 分类筛选面板（数据驱动） ---------------- */

function taxLabel(key, val) {
  const d = TAXONOMY.find(x => x.key === key);
  if (!d) return val;
  const o = d.options.find(x => x.v === val);
  return (o && o.label) || val;
}

function renderGroups() {
  $('#taxGroups').innerHTML = TAXONOMY.map(d => {
    const counts = TAX_COUNTS[d.key] || {};
    const chips = [{ v: '', label: '全部', n: TAX_TOTAL, all: true }]
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
        const key = g.dataset.key;
        const v = b.dataset.v;
        if (v && state.tax[key] === v) delete state.tax[key];  // 再点一次取消
        else if (v) state.tax[key] = v;
        else delete state.tax[key];
        renderGroups();
        syncUrl();
        search(true);
      });
    });
  });
  renderSummary();
}

function renderSummary() {
  const active = TAX_KEYS.filter(k => state.tax[k]);
  const bits = active.map(k => `${taxLabel(k, state.tax[k])}`);
  if (state.q) bits.unshift(`“${state.q}”`);
  if (state.saved) bits.push('仅收藏');
  $('#filterSummary').textContent = bits.length ? bits.join(' · ') : '全部素材';
  $('#filterSummary').classList.toggle('active', bits.length > 0);
}

async function loadFacets() {
  const f = await api('/api/facets', {});
  TAXONOMY = f.taxonomy || [];
  TAX_KEYS = TAXONOMY.map(d => d.key);
  TAX_COUNTS = f.tax_counts || {};
  TAX_TOTAL = f.tax_total || 0;

  $('#statTotal').textContent = (f.total || 0).toLocaleString();
  $('#statSaved').textContent = (f.saved || 0).toLocaleString();
  $('#statUpdate').textContent = f.last_update_at ? f.last_update_at.slice(5) : '—';
  $('#qinfo').textContent = `已归类 ${TAX_TOTAL.toLocaleString()} 张 · ${TAXONOMY.length} 个维度`;
  renderGroups();
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

function queryParams() {
  const p = {
    q: state.q, page: state.page, per: state.per,
    saved: state.saved ? '1' : '',
  };
  TAX_KEYS.forEach(k => { if (state.tax[k]) p['tax_' + k] = state.tax[k]; });
  return p;
}

async function search(reset) {
  if (state.loading) return;
  state.loading = true;
  document.body.classList.add('is-searching');
  if (reset) {
    state.page = 1;
    state.items = [];
    $('#empty').hidden = true;
    $('#notice').hidden = true;
    $('#grid').innerHTML = '';
    renderSummary();
  }
  if (!state.items.length) setMeta('<span class="busy">检索中…</span>');

  const data = await api('/api/search', queryParams());
  state.mode = data.mode;
  state.total = data.total;
  const start = state.items.length;
  state.items = state.items.concat(data.items);
  $('#grid').insertAdjacentHTML('beforeend',
    data.items.map((p, i) => cardHTML(p, start + i)).join(''));

  document.body.classList.remove('is-searching');
  state.loading = false;
  renderStatus(data);
}

function renderStatus(data) {
  const shown = state.items.length;
  const n = data.total;
  if (data.mode === 'none' || n === 0) {
    $('#grid').innerHTML = '';
    state.items = [];
    $('#moreBtn').hidden = true;
    $('#empty').hidden = false;
    $('#emptyTitle').textContent = '没有找到匹配的素材';
    $('#emptyText').textContent = '换个频道或清空部分筛选条件试试。纯图素材没有文字描述，按来源频道浏览最有效。';
    setMeta('0 张素材');
    return;
  }
  $('#empty').hidden = true;
  if (data.mode === 'loose') {
    $('#notice').hidden = false;
    $('#notice').innerHTML = '<span class="n-ico">⚠</span><div>没有精确匹配，下面是<b>部分命中的弱匹配</b>，请自行判断是否可用。</div>';
  } else $('#notice').hidden = true;

  const bits = [`<b>${n.toLocaleString()}</b> 张素材`];
  if (n > shown) bits.push('已显示 ' + shown);
  setMeta(bits.join(' · '));
  $('#moreBtn').hidden = state.items.length >= state.total;
}

function taxOf(p, key) {
  const i = TAX_KEYS.indexOf(key);
  return (i >= 0 && p.tax && p.tax[i]) ? p.tax[i] : '';
}

function cardHTML(p, i) {
  const thumb = p.thumb || p.full;
  const ch = taxOf(p, 'channel');
  const region = taxOf(p, 'region');
  const frame = taxOf(p, 'frame');
  const grade = taxOf(p, 'grade');
  const badge = p.weak ? `<span class="wbadge">弱匹配 ${p.match}%</span>` : '';
  const ar = (p.width && p.height) ? ` style="aspect-ratio:${p.width}/${p.height}"` : '';
  const label = p.title && !/^tg_/.test(p.title) ? p.title : `#${p.id} · ${ch ? '@' + ch : 'TG'}`;
  return `<figure class="card${p.weak ? ' weak' : ''}" data-i="${i}">
    <img src="${esc(proxyUrl(thumb))}" data-fb="${esc(proxyUrl(thumb))}"
         alt="${esc(label)}" loading="lazy" decoding="async"${ar}>
    ${badge}
    <button class="fav ${p.saved ? 'on' : ''}" data-id="${p.id}" data-saved="${p.saved ? 1 : 0}"
      title="${p.saved ? '取消收藏' : '收藏'}">${p.saved ? '♥' : '♡'}</button>
    <figcaption class="cap">
      <span class="cap-t">${esc(label)}</span>
      <span class="cap-m">${esc([region, frame, grade].filter(Boolean).join(' · '))}${p.width ? ' · ' + p.width + '×' + p.height : ''}</span>
    </figcaption>
  </figure>`;
}

/* ---------------- 网格交互 ---------------- */

$('#grid').addEventListener('click', async (e) => {
  const fav = e.target.closest('.fav');
  if (fav) {
    e.stopPropagation();
    const id = fav.dataset.id;
    const next = fav.dataset.saved === '1' ? 0 : 1;
    fav.dataset.saved = String(next);
    fav.classList.toggle('on', !!next);
    fav.textContent = next ? '♥' : '♡';
    const item = state.items.find(x => String(x.id) === String(id));
    if (item) item.saved = next;
    await fetch(`/api/save?id=${id}&value=${next}`);
    const f = await api('/api/facets', {});
    $('#statSaved').textContent = f.saved.toLocaleString();
    return;
  }
  const card = e.target.closest('.card');
  if (card) openLB(Number(card.dataset.i));
});

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
  const p = state.items[state.idx];
  if (!p) return closeLB();
  const img = $('#lbImg');
  img.onerror = null;
  img.src = proxyUrl(p.full || p.thumb);
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
    rows.unshift(['匹配度', (p.weak ? '弱匹配 · ' : '') + (p.match || 0) + '%']);
  }
  $('#lbMeta').innerHTML = rows.map(([k, v]) => `<dt>${k}</dt><dd>${esc(v)}</dd>`).join('');

  const name = (p.title || 'material').replace(/\.[a-z]+$/i, '').slice(0, 60) + '.jpg';
  $('#lbDl').href = `/download?u=${encodeURIComponent(p.full || p.thumb)}&name=${encodeURIComponent(name)}`;
  $('#lbCount').textContent = `${state.idx + 1} / ${state.total}`;

  const saveBtn = $('#lbSave');
  saveBtn.textContent = p.saved ? '已收藏 ♥' : '收藏';
  saveBtn.classList.toggle('primary', !!p.saved);
  saveBtn.onclick = async () => {
    p.saved = p.saved ? 0 : 1;
    await fetch(`/api/save?id=${p.id}&value=${p.saved}`);
    renderLB();
    const card = $(`.card[data-i="${state.idx}"] .fav`);
    if (card) {
      card.dataset.saved = String(p.saved);
      card.classList.toggle('on', !!p.saved);
      card.textContent = p.saved ? '♥' : '♡';
    }
  };

  $('#lbHide').onclick = async () => {
    $('#lbHide').textContent = '已隐藏';
    try { await fetch(`/api/hide?id=${p.id}&value=1`); } catch (e) {}
    setTimeout(() => {
      closeLB();
      $('#lbHide').textContent = '隐藏此图';
      loadFacets();
      search(true);
    }, 400);
  };

  const src = $('#lbSrc');
  if (p.page) { src.href = p.page; src.hidden = false; } else { src.hidden = true; }
}

function step(d) {
  const next = state.idx + d;
  if (next < 0) return;
  if (next >= state.items.length) {
    if (state.items.length < state.total) search(false);
    return;
  }
  state.idx = next;
  renderLB();
}

$('#lbPrev').onclick = () => step(-1);
$('#lbNext').onclick = () => step(1);
document.querySelectorAll('[data-close]').forEach(el => el.addEventListener('click', closeLB));

/* ---------------- 事件 ---------------- */

$('#q').addEventListener('input', debounce((e) => {
  state.q = e.target.value.trim();
  $('#clearq').hidden = !state.q;
  syncUrl();
  search(true);
}, 200));

function clearQuery() {
  $('#q').value = '';
  state.q = '';
  $('#clearq').hidden = true;
  syncUrl();
  search(true);
}
$('#clearq').onclick = clearQuery;

$('#savedOnly').addEventListener('change', (e) => {
  state.saved = e.target.checked;
  syncUrl();
  search(true);
});

function resetAll() {
  state.q = ''; state.tax = {}; state.saved = false;
  $('#q').value = ''; $('#clearq').hidden = true;
  $('#savedOnly').checked = false;
  renderGroups();
  syncUrl();
  search(true);
}
$('#resetBtn').onclick = resetAll;
$('#emptyReset').onclick = resetAll;

$('#foldBtn').onclick = () => {
  state.folded = !state.folded;
  $('#taxGroups').classList.toggle('folded', state.folded);
  $('#foldBtn').textContent = state.folded ? '展开选项' : '收起选项';
  $('#foldBtn').setAttribute('aria-expanded', String(!state.folded));
};

$('#moreBtn').addEventListener('click', () => { state.page++; search(false); });

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
  if (entries[0].isIntersecting && !state.loading && state.items.length < state.total) {
    state.page++;
    search(false);
  }
}, { rootMargin: '600px' }).observe($('#sentinel'));

/* ---------------- 启动 ---------------- */

(async function boot() {
  await loadFacets();   // 先拿到分类契约，才能解析 URL 里的分类参数
  readUrl();
  renderGroups();
  await search(true);
})();
