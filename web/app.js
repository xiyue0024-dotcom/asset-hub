'use strict';

const $ = (s) => document.querySelector(s);
const state = {
  q: '', country: '', city: '', scene: '', orient: '',
  saved: false, page: 1, per: 24, total: 0, items: [], loading: false, idx: -1,
  mode: 'browse', ingested: 0,
  minpx: 1000000, nowm: true, noselfie: true, noblur: false,
};

const esc = (s) => String(s == null ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;');

// 图片直连 CDN，比走本地代理快一个数量级；代理只作为加载失败时的兜底
const imgUrl = (u) => u || '';
const proxyUrl = (u) => '/img?u=' + encodeURIComponent(u || '');

// 图片加载失败时自动降级到本地代理
document.addEventListener('error', (e) => {
  const img = e.target;
  if (img && img.tagName === 'IMG' && img.dataset.fb && img.src !== img.dataset.fb) {
    img.src = img.dataset.fb;
  }
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

function setMeta(html) { $('#resultMeta').innerHTML = html; }

/* ---------------- 筛选面板 ---------------- */

async function loadFacets() {
  const f = await api('/api/facets', { country: state.country });

  $('#statTotal').textContent = f.total.toLocaleString();
  $('#statSaved').textContent = f.saved.toLocaleString();
  $('#statUpdate').textContent = f.last_update_at ? f.last_update_at.slice(5) : '未更新';

  const q = f.quality || {};
  $('#qinfo').textContent =
    `低清 ${q.lowres || 0} · 疑似水印 ${q.wm || 0} · 人物 ${q.people || 0}` +
    (q.checked ? ` · 已检测 ${q.checked}` : '');

  const sel = $('#citySel');
  sel.innerHTML = '<option value="">全部城市</option>' +
    f.cities.filter(c => c.name && c.name !== '其他')
      .map(c => `<option value="${esc(c.name)}">${esc(c.name)} · ${c.count}</option>`).join('');
  if (state.city) sel.value = state.city;

  const chips = [{ name: '', count: 0, label: '全部场景' }]
    .concat(f.scenes.filter(s => s.name && s.name !== '其他')
      .map(s => ({ name: s.name, count: s.count, label: s.name })));

  $('#sceneChips').innerHTML = chips.map(c =>
    `<button class="chip ${state.scene === c.name ? 'on' : ''}" data-scene="${esc(c.name)}">` +
    `${esc(c.label)}${c.count ? `<i>${c.count}</i>` : ''}</button>`
  ).join('');

  $('#sceneChips').querySelectorAll('.chip').forEach(b => {
    b.addEventListener('click', () => {
      state.scene = b.dataset.scene;
      $('#sceneChips').querySelectorAll('.chip').forEach(x => x.classList.toggle('on', x === b));
      search(true);
    });
  });
}

/* ---------------- 检索 ---------------- */

function queryParams() {
  return {
    q: state.q, country: state.country, city: state.city,
    scene: state.scene, orient: state.orient,
    saved: state.saved ? '1' : '', page: state.page, per: state.per,
    minpx: state.minpx || '',
    nowm: state.nowm ? '1' : '',
    noselfie: state.noselfie ? '1' : '',
    noblur: state.noblur ? '1' : '',
  };
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
  }
  if (!state.items.length) setMeta('<span class="busy">检索中…</span>');

  const data = await api('/api/search', queryParams());

  if (reset) $('#grid').innerHTML = '';

  state.mode = data.mode;
  state.total = data.total;

  const start = state.items.length;
  state.items = state.items.concat(data.items);
  $('#grid').insertAdjacentHTML('beforeend',
    data.items.map((p, i) => cardHTML(p, start + i)).join(''));

  document.body.classList.remove('is-searching');
  state.loading = false;
  renderStatus(data, 0);

  // 补采放到后台跑，不阻塞界面
  if (reset && data.mode === 'none' && state.q.trim()) autoIngest(state.q);
}

const _ingestTried = new Set();

async function autoIngest(q) {
  if (_ingestTried.has(q)) return;
  _ingestTried.add(q);

  const txt = $('#emptyText');
  if (txt) txt.textContent = '本地没有匹配，正在从公开图库补采，约需 20 秒…';

  try {
    const r = await fetch('/api/ingest?q=' + encodeURIComponent(q) +
      '&country=' + encodeURIComponent(state.country));
    const j = await r.json();
    if ((j.added || 0) > 0) {
      await loadFacets();
      search(true);
    } else if (txt) {
      txt.textContent = '已尝试从公开图库补采，但没有找到匹配「' + q + '」的素材。换个说法试试。';
    }
  } catch (e) {
    if (txt) txt.textContent = '补采失败，请检查网络后重试。';
  }
}

function renderStatus(data, ingested) {
  const shown = state.items.length;
  const n = data.total;
  const kw = state.q || '当前筛选';

  if (data.mode === 'none') {
    $('#grid').innerHTML = '';
    state.items = [];
    $('#notice').hidden = true;
    $('#moreBtn').hidden = true;
    $('#empty').hidden = false;
    $('#emptyTitle').textContent = `没有找到「${kw}」`;
    $('#emptyText').textContent = ingested > 0
      ? `已从公开图库补采 ${ingested} 张，但没有一张同时包含这些关键词，所以这里不显示任何结果。`
      : '素材库里没有任何一张图同时包含这些关键词。可以换个说法，或者从公开图库补采。';
    setMeta('0 张素材');
    return;
  }

  $('#empty').hidden = true;

  if (data.mode === 'loose') {
    $('#notice').hidden = false;
    $('#notice').innerHTML =
      '<span class="n-ico">⚠</span><div>没有精确匹配。<b>下面 ' + n +
      ' 张只命中了部分关键词</b>，不保证符合你要的内容，是否可用请自行判断。</div>';
  } else {
    $('#notice').hidden = true;
  }

  const bits = [];
  if (data.mode === 'exact') bits.push('精确匹配 <b>' + n.toLocaleString() + '</b> 张');
  else if (data.mode === 'loose') bits.push('<b>' + n.toLocaleString() + '</b> 张弱匹配');
  else bits.push('共 <b>' + n.toLocaleString() + '</b> 张素材');
  if (n > shown) bits.push('已显示 ' + shown);
  if (state.scene) bits.push('场景：' + state.scene);
  if (state.city) bits.push('城市：' + state.city);
  if (state.orient) bits.push(state.orient === 'landscape' ? '横版' : '竖版');
  if (state.saved) bits.push('仅收藏');
  setMeta(bits.join(' · '));

  $('#moreBtn').hidden = state.items.length >= state.total;
}

function cardHTML(p, i) {
  const thumb = p.thumb || p.full;
  const badge = p.weak
    ? `<span class="wbadge">弱匹配 ${p.match}%</span>`
    : `<span class="lic">${esc(p.license || '')}</span>`;
  const ar = (p.width && p.height) ? ` style="aspect-ratio:${p.width}/${p.height}"` : '';
  return `<figure class="card${p.weak ? ' weak' : ''}" data-i="${i}">
    <img src="${esc(thumb)}" data-fb="${esc(proxyUrl(thumb))}" alt="${esc(p.title)}"
         loading="lazy" decoding="async"${ar}>
    ${badge}
    <button class="fav ${p.saved ? 'on' : ''}" data-id="${p.id}" data-saved="${p.saved ? 1 : 0}"
      title="${p.saved ? '取消收藏' : '收藏'}">${p.saved ? '♥' : '♡'}</button>
    <figcaption class="cap">
      <span class="cap-t">${esc(p.title)}</span>
      <span class="cap-m">${esc(p.city)} · ${esc(p.scene)}${p.width ? ' · ' + p.width + '×' + p.height : ''}</span>
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
  img.onerror = () => { img.onerror = null; img.src = proxyUrl(p.thumb); };
  img.src = imgUrl(p.preview || p.thumb);
  img.alt = p.title || '';

  $('#lbTitle').textContent = p.title || '未命名素材';

  $('#lbBadges').innerHTML = [
    p.country && `<span class="badge">${esc(p.country)}</span>`,
    p.city && p.city !== '其他' && `<span class="badge">${esc(p.city)}</span>`,
    p.scene && `<span class="badge gray">${esc(p.scene)}</span>`,
    p.orientation && `<span class="badge gray">${p.orientation === 'landscape' ? '横版' : p.orientation === 'portrait' ? '竖版' : '方图'}</span>`,
  ].filter(Boolean).join('');

  const metaRows = [
    ['尺寸', p.width ? `${p.width} × ${p.height}` : '—'],
    ['版权', p.license || '见来源页'],
    ['作者', p.artist || '未署名'],
    ['来源', p.source === 'wikimedia' ? 'Wikimedia Commons' : p.source === 'pexels' ? 'Pexels' : p.source],
  ];
  if (state.mode === 'exact' || state.mode === 'loose') {
    metaRows.unshift(['匹配度', (p.weak ? '弱匹配 · ' : '') + (p.match || 0) + '%']);
  }
  metaRows.push(['编号', '#' + p.id]);

  $('#lbMeta').innerHTML = metaRows
    .map(([k, v]) => `<dt>${k}</dt><dd>${esc(v)}</dd>`).join('');

  const name = (p.title || 'material').replace(/\.[a-z]+$/i, '').slice(0, 60) + '.jpg';
  $('#lbDl').href = `/download?u=${encodeURIComponent(p.full || p.thumb)}&name=${encodeURIComponent(name)}`;

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

  $('#lbCopy').onclick = async () => {
    const txt = `${p.title} — ${p.artist || '未署名'} — ${p.license || ''} — ${p.page || ''}`;
    try { await navigator.clipboard.writeText(txt); $('#lbCopy').textContent = '已复制'; }
    catch { $('#lbCopy').textContent = '复制失败'; }
    setTimeout(() => { $('#lbCopy').textContent = '复制署名'; }, 1500);
  };

  $('#lbHide').onclick = async () => {
    $('#lbHide').textContent = '已隐藏';
    try { await fetch(`/api/hide?id=${p.id}&value=1`); } catch (e) {}
    setTimeout(() => {
      closeLB();
      $('#lbHide').textContent = '隐藏此图（水印/人物）';
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
    if (state.items.length < state.total) { search(false); }
    return;
  }
  state.idx = next;
  renderLB();
}

$('#lbPrev').onclick = () => step(-1);
$('#lbNext').onclick = () => step(1);
document.querySelectorAll('[data-close]').forEach(el => el.addEventListener('click', closeLB));

/* ---------------- 筛选事件 ---------------- */

$('#q').addEventListener('input', debounce((e) => {
  state.q = e.target.value.trim();
  $('#clearq').hidden = !state.q;
  search(true);
}, 200));

$('#clearq').onclick = () => {
  $('#q').value = '';
  state.q = '';
  $('#clearq').hidden = true;
  search(true);
};

$('#countrySeg').addEventListener('click', (e) => {
  const b = e.target.closest('button');
  if (!b) return;
  $('#countrySeg').querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b));
  state.country = b.dataset.v;
  state.city = '';
  state.scene = '';
  loadFacets().then(() => search(true));
});

$('#citySel').addEventListener('change', (e) => {
  state.city = e.target.value;
  search(true);
});

$('#orientSeg').addEventListener('click', (e) => {
  const b = e.target.closest('button');
  if (!b) return;
  $('#orientSeg').querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b));
  state.orient = b.dataset.v;
  search(true);
});

$('#savedOnly').addEventListener('change', (e) => {
  state.saved = e.target.checked;
  search(true);
});

$('#optHd').addEventListener('change', (e) => {
  state.minpx = e.target.checked ? 1000000 : 0;
  search(true);
});

$('#optWm').addEventListener('change', (e) => { state.nowm = e.target.checked; search(true); });
$('#optSelfie').addEventListener('change', (e) => { state.noselfie = e.target.checked; search(true); });
$('#optBlur').addEventListener('change', (e) => { state.noblur = e.target.checked; search(true); });

$('#moreBtn').addEventListener('click', () => { state.page++; search(false); });

$('#ingestBtn').onclick = async () => {
  const kw = state.q.trim() || prompt('输入要采集的关键词（英文效果更好，例如 Ubud rice terrace）');
  if (!kw) return;
  const btn = $('#ingestBtn');
  btn.disabled = true;
  btn.textContent = '采集中…';
  await fetch('/api/ingest?q=' + encodeURIComponent(kw) +
    '&country=' + encodeURIComponent(state.country));
  btn.disabled = false;
  btn.textContent = '＋ 补采素材';
  await loadFacets();
  search(true);
};

$('#emptyIngest').onclick = () => $('#ingestBtn').click();

$('#updateBtn').onclick = async () => {
  const btn = $('#updateBtn');
  if (btn.disabled) return;
  const before = $('#statUpdate').textContent;
  btn.disabled = true;
  btn.textContent = '抓取中…';
  await fetch('/api/update');

  // 后台任务，轮询到完成再刷新
  const started = Date.now();
  const timer = setInterval(async () => {
    try {
      const st = await (await fetch('/api/status')).json();
      const nowText = st.last_update_at ? st.last_update_at.slice(5) : '未更新';
      if (!st.running && nowText !== before) {
        clearInterval(timer);
        btn.disabled = false;
        btn.textContent = '↻ 抓取最新';
        await loadFacets();
        search(true);
        setMeta('已抓取最新素材，新增 <b>' + (st.last_update_added || 0) + '</b> 张');
      } else if (Date.now() - started > 600000) {
        clearInterval(timer);
        btn.disabled = false;
        btn.textContent = '↻ 抓取最新';
      }
    } catch (e) { /* 继续轮询 */ }
  }, 5000);
};

$('#emptyClear').onclick = () => {
  $('#q').value = '';
  state.q = '';
  $('#clearq').hidden = true;
  search(true);
};

/* ---------------- 键盘 ---------------- */

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && !$('#lb').hidden) return closeLB();
  if ($('#lb').hidden && e.key === '/' && document.activeElement !== $('#q')) {
    e.preventDefault();
    $('#q').focus();
    return;
  }
  if (!$('#lb').hidden) {
    if (e.key === 'ArrowLeft') step(-1);
    if (e.key === 'ArrowRight') step(1);
  }
});

/* ---------------- 滚动加载 ---------------- */

new IntersectionObserver((entries) => {
  if (entries[0].isIntersecting && !state.loading && state.items.length < state.total) {
    state.page++;
    search(false);
  }
}, { rootMargin: '600px' }).observe($('#sentinel'));

/* ---------------- 启动 ---------------- */

(async function boot() {
  await loadFacets();
  await search(true);
})();
