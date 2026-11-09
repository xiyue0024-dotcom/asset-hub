'use strict';

/* 静态版：索引一次性加载，检索在浏览器内完成，逻辑与服务端保持一致 */

const $ = (s) => document.querySelector(s);
const esc = (s) => String(s == null ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

const STOP = new Set(['the', 'a', 'an', 'of', 'and', 'or', 'in', 'on', 'at', 'to', 'by',
  'for', 'with', 'cc', 'sa', 'by-sa', 'jpg', 'jpeg', 'png', 'photo', 'image', 'file',
  'picture', 'stock', '素材', '图片']);

// 中文查询词 → 英文同义词（库里标题基本是英文）
const CN2EN = {
  '海滩': ['beach', 'coast', 'shore'], '沙滩': ['beach', 'sand'],
  '海边': ['beach', 'seaside', 'coast'], '日落': ['sunset'],
  '日出': ['sunrise'], '稻田': ['rice terrace', 'rice field', 'paddy'],
  '梯田': ['rice terrace', 'terrace'], '火山': ['volcano', 'mountain'],
  '瀑布': ['waterfall'], '森林': ['forest', 'jungle'],
  '湖泊': ['lake'], '公园': ['park', 'garden'],
  '寺庙': ['temple', 'shrine'], '清真寺': ['mosque'],
  '教堂': ['church', 'cathedral'], '建筑': ['architecture', 'building'],
  '天际线': ['skyline'], '街景': ['street', 'alley'],
  '街道': ['street'], '市场': ['market', 'bazaar'],
  '夜市': ['night market', 'market'], '美食': ['food', 'dish', 'cuisine'],
  '小吃': ['snack', 'street food'], '餐厅': ['restaurant', 'eatery'],
  '咖啡馆': ['cafe', 'coffee', 'kopi'], '咖啡': ['coffee', 'cafe', 'kopi'],
  '酒吧': ['bar', 'pub'], '酒店': ['hotel'], '度假村': ['resort'],
  '民宿': ['guesthouse', 'homestay', 'villa'], '泳池': ['pool'],
  '地铁': ['mrt', 'metro', 'subway'], '公交': ['bus'], '机场': ['airport'],
  '火车站': ['station', 'railway'], '港口': ['harbour', 'harbor', 'port'],
  '船': ['boat', 'ferry'], '摩托车': ['scooter', 'motorbike'],
  '人': ['people', 'person'], '人群': ['crowd', 'people'],
  '舞蹈': ['dance', 'dancer'], '节庆': ['festival', 'ceremony'],
  '仪式': ['ceremony', 'ritual'], '早餐': ['breakfast'],
  '午餐': ['lunch'], '晚餐': ['dinner'],
  '聚餐': ['dining', 'gathering', 'meal'], '用餐': ['dining', 'restaurant'],
  '夜景': ['night', 'nighttime'], '购物': ['shopping', 'mall'],
  '商场': ['mall', 'shopping'], '植物园': ['botanic garden', 'garden'],
  '动物园': ['zoo'],
  '小摊': ['warung', 'stall', 'vendor'], '摊子': ['stall', 'vendor'],
  '摊位': ['stall', 'stand', 'lapak'], '摊贩': ['vendor', 'hawker', 'pedagang'],
  '路边摊': ['street vendor', 'stall', 'warung'], '大排档': ['hawker', 'stall', 'eatery'],
  '吃饭': ['eating', 'dining', 'meal', 'makan'], '饭馆': ['restaurant', 'eatery', 'warung'],
  '食堂': ['canteen', 'kantin'], '菜市场': ['wet market', 'market', 'pasar'],
  '早市': ['morning market', 'pasar pagi'], '夜市摊': ['night market', 'pasar malam'],
  '水果摊': ['fruit stall', 'fruit market'], '鱼市': ['fish market', 'pasar ikan'],
  '组屋': ['hdb', 'public housing', 'flat', 'block'], '走廊': ['corridor', 'hallway'],
  '电梯': ['lift', 'elevator'], '楼下': ['void deck', 'ground floor'],
  '理发': ['barber', 'barbershop', 'haircut'], '理发店': ['barbershop', 'barber'],
  '洗衣店': ['laundry'], '药店': ['pharmacy', 'apotek'], '杂货店': ['grocery', 'sundry', 'provision'],
  '便利店': ['convenience store', 'minimart'], '小卖部': ['shop', 'store', 'kiosk'],
  '网吧': ['internet cafe', 'warnet'], '修车': ['workshop', 'garage', 'bengkel'],
  '摩托车': ['motorcycle', 'scooter', 'motorbike'], '三轮车': ['rickshaw', 'becak', 'trishaw'],
  '小巴': ['minibus', 'van', 'angkot'], '马车': ['carriage', 'cart'],
  '渔船': ['fishing boat', 'boat'], '渔村': ['fishing village', 'village'],
  '农田': ['farm', 'field', 'paddy'], '菜地': ['garden', 'vegetable plot'],
  '收割': ['harvest'], '养牛': ['cattle', 'livestock'],
  '婚礼': ['wedding'], '宴席': ['banquet', 'feast', 'kenduri'],
  '祈祷': ['prayer', 'praying'],
  '小学': ['primary school', 'school'], '学生': ['student', 'schoolchildren'],
  '孩子': ['children', 'kids'], '老人': ['elderly', 'old man', 'old woman'],
  '菜饭': ['economy rice', 'cai fan', 'mixed rice'], '杂菜饭': ['nasi campur', 'economy rice'],
  '糕点': ['kueh', 'cake', 'pastry'], '吐司': ['toast', 'bread'],
  '奶茶': ['teh tarik', 'milk tea'], '咖啡店': ['kopitiam', 'coffee shop', 'cafe'],
};

const CN_EXTRA = ['巴厘岛', '雅加达', '日惹', '万隆', '泗水', '棉兰', '龙目岛', '科莫多',
  '四王群岛', '新加坡', '印尼', '印度尼西亚', '乌布', '水明漾', '库塔', '沙努尔',
  '金巴兰', '努沙杜瓦', '佩尼达', '乌鲁瓦图', '海神庙', '长谷', '登巴萨',
  '牛车水', '小印度', '滨海湾', '圣淘沙', '乌节路', '克拉码头', '甘榜格南',
  '组屋', '走廊', '小摊', '摊位', '摊贩', '吃饭', '用餐', '聚餐',
  '照片', '图片', '素材', '场景', '背景', '特写', '远景', '近景'];

const CN_STOP = new Set(['的', '了', '和', '与', '在', '有', '是', '我', '要', '找',
  '张', '个', '些', '一', '点', '很', '都', '也', '就', '还', '被', '把', '给']);

let CN_VOCAB = [];

function hasChinese(t) {
  return /[\u4e00-\u9fff]/.test(t || '');
}

function segmentCN(text) {
  const out = [];
  let i = 0;
  while (i < text.length) {
    let hit = '';
    for (const w of CN_VOCAB) {
      if (text.startsWith(w, i)) { hit = w; break; }
    }
    if (hit) { out.push(hit); i += hit.length; }
    else { i += 1; }
  }
  return out.length ? out : [text];
}

function buildVocab(items) {
  const set = new Set(Object.keys(CN2EN));
  CN_EXTRA.forEach(w => set.add(w));
  items.forEach(p => {
    if (p.city && p.city !== '其他') set.add(p.city);
    if (p.scene && p.scene !== '其他') set.add(p.scene);
  });
  CN_VOCAB = [...set].filter(w => w.length >= 2).sort((a, b) => b.length - a.length);
}

function expandToken(t) {
  return [t].concat((CN2EN[t] || []).filter(v => v !== t));
}

const SAVED_KEY = 'assethub_saved_v1';
const HIDDEN_KEY = 'assethub_hidden_v1';
const BLUR_THRESHOLD = 12;

const state = {
  q: '', country: '', city: '', scene: '', orient: '', saved: false,
  page: 1, per: 24, mode: 'browse', list: [], shown: 0, idx: -1,
  minpx: 1000000, nowm: true, noselfie: true, noblur: false,
};

let ALL = [];
let SAVED = new Set();
let HIDDEN = new Set();

/* ---------------- 工具 ---------------- */

function tokenize(q) {
  const out = [];
  String(q || '').toLowerCase().split(/[\s,，、/|]+/).forEach(t => {
    t = t.replace(/^[()[\]"'.\-_]+/, '').replace(/[()[\]"'.\-_]+$/, '');
    if (!t || STOP.has(t)) return;
    if (hasChinese(t)) { segmentCN(t).forEach(w => out.push(w)); return; }
    if (/^[a-z0-9]+$/.test(t) && t.length < 2) return;
    out.push(t);
  });
  return out;
}

function originalUrl(th) {
  const m = String(th || '').match(/^(.*)\/thumb\/(.+)\/\d+px-[^/]+$/);
  return m ? m[1] + '/' + m[2] : th;
}

function previewUrl(th) {
  return String(th || '').replace(/\/\d+px-/, '/1280px-');
}

function loadSaved() {
  try { SAVED = new Set(JSON.parse(localStorage.getItem(SAVED_KEY) || '[]')); }
  catch (e) { SAVED = new Set(); }
  try { HIDDEN = new Set(JSON.parse(localStorage.getItem(HIDDEN_KEY) || '[]')); }
  catch (e) { HIDDEN = new Set(); }
  $('#statSaved').textContent = SAVED.size;
}

function persistHidden() {
  try { localStorage.setItem(HIDDEN_KEY, JSON.stringify([...HIDDEN])); } catch (e) {}
}

function persistSaved() {
  try { localStorage.setItem(SAVED_KEY, JSON.stringify([...SAVED])); } catch (e) {}
  $('#statSaved').textContent = SAVED.size;
}

/* ---------------- 检索 ---------------- */

function matchesFilters(p) {
  if (HIDDEN.has(p.id)) return false;
  if (state.country && p.country !== state.country) return false;
  if (state.city && p.city !== state.city) return false;
  if (state.scene && p.scene !== state.scene) return false;
  if (state.orient && p.orientation !== state.orient) return false;
  if (state.saved && !SAVED.has(p.id)) return false;
  if (state.minpx && p.width && p.height && (p.width * p.height) < state.minpx) return false;
  if (state.nowm && p.wm) return false;
  if (state.noselfie && (p.selfie || p.solo)) return false;
  if (state.noblur && p.blur != null && p.blur < BLUR_THRESHOLD) return false;
  return true;
}

function runSearch() {
  const toks = tokenize(state.q);
  const pool = ALL.filter(matchesFilters);
  let ranked = [];

  if (!toks.length) {
    state.mode = 'browse';
    ranked = pool.slice().sort((a, b) => b.id - a.id)
      .map(p => ({ p, pct: 100, weak: false }));
    return { ranked, exact: 0, loose: 0 };
  }

  const exact = [];
  const loose = [];
  const maxScore = 3 * toks.length;

  for (const p of pool) {
    const hit = [];
    for (const t of toks) {
      const vs = expandToken(t);
      if (vs.some(v => p._st.includes(v))) hit.push(vs);
    }
    if (!hit.length) continue;
    let score = 0;
    for (const vs of hit) {
      score += vs.some(v => p._t.includes(v) || p._f.includes(v)) ? 3 : 1;
    }
    const pct = Math.round(Math.min(1, score / maxScore) * 100);
    if (hit.length === toks.length) exact.push({ p, pct, weak: false, score });
    else loose.push({ p, pct, weak: true, score, hits: hit.length });
  }

  if (exact.length) {
    state.mode = 'exact';
    exact.sort((a, b) => b.score - a.score || b.p.id - a.p.id);
    return { ranked: exact, exact: exact.length, loose: loose.length };
  }
  if (loose.length) {
    state.mode = 'loose';
    loose.sort((a, b) => b.hits - a.hits || b.score - a.score || b.p.id - a.p.id);
    return { ranked: loose, exact: 0, loose: loose.length };
  }
  state.mode = 'none';
  return { ranked: [], exact: 0, loose: 0 };
}

/* ---------------- 渲染 ---------------- */

function cardHTML(r, i) {
  const p = r.p;
  const badge = r.weak
    ? `<span class="wbadge">弱匹配 ${r.pct}%</span>`
    : `<span class="lic">${esc(p.license || '')}</span>`;
  const on = SAVED.has(p.id);
  const ar = (p.width && p.height) ? ` style="aspect-ratio:${p.width}/${p.height}"` : '';
  return `<figure class="card${r.weak ? ' weak' : ''}" data-i="${i}">
    <img src="${esc(p.thumb)}" alt="${esc(p.title)}" loading="lazy" decoding="async"${ar}>
    ${badge}
    <button class="fav ${on ? 'on' : ''}" data-id="${p.id}" title="${on ? '取消收藏' : '收藏'}">${on ? '♥' : '♡'}</button>
    <figcaption class="cap">
      <span class="cap-t">${esc(p.title)}</span>
      <span class="cap-m">${esc(p.city)} · ${esc(p.scene)}${p.width ? ' · ' + p.width + '×' + p.height : ''}</span>
    </figcaption>
  </figure>`;
}

function render() {
  const { ranked, exact, loose } = runSearch();
  state.list = ranked;
  state.shown = Math.min(state.per, ranked.length);

  $('#grid').innerHTML = ranked.slice(0, state.shown).map((r, i) => cardHTML(r, i)).join('');

  const n = ranked.length;
  const kw = state.q || '当前筛选';

  if (state.mode === 'none') {
    $('#notice').hidden = true;
    $('#empty').hidden = false;
    $('#emptyTitle').textContent = `没有找到「${kw}」`;
    $('#emptyText').textContent = '素材库里没有任何一张图同时包含这些关键词。可以换个说法，或减少关键词。';
    $('#moreBtn').hidden = true;
    $('#resultMeta').textContent = '0 张素材';
    return;
  }

  $('#empty').hidden = true;

  if (state.mode === 'loose') {
    $('#notice').hidden = false;
    $('#notice').innerHTML = '<span class="n-ico">⚠</span><div>没有精确匹配。<b>下面 ' + n +
      ' 张只命中了部分关键词</b>，不保证符合你要的内容，是否可用请自行判断。</div>';
  } else {
    $('#notice').hidden = true;
  }

  const bits = [];
  if (state.mode === 'exact') bits.push('精确匹配 <b>' + n.toLocaleString() + '</b> 张');
  else if (state.mode === 'loose') bits.push('<b>' + n.toLocaleString() + '</b> 张弱匹配');
  else bits.push('共 <b>' + n.toLocaleString() + '</b> 张素材');
  if (n > state.shown) bits.push('已显示 ' + state.shown);
  if (state.scene) bits.push('场景：' + state.scene);
  if (state.city) bits.push('城市：' + state.city);
  if (state.orient) bits.push(state.orient === 'landscape' ? '横版' : '竖版');
  if (state.saved) bits.push('仅收藏');
  $('#resultMeta').innerHTML = bits.join(' · ');

  $('#moreBtn').hidden = state.shown >= n;
}

function loadMore() {
  const next = Math.min(state.shown + state.per, state.list.length);
  const html = state.list.slice(state.shown, next)
    .map((r, i) => cardHTML(r, state.shown + i)).join('');
  $('#grid').insertAdjacentHTML('beforeend', html);
  state.shown = next;
  $('#moreBtn').hidden = state.shown >= state.list.length;
  renderMetaOnly();
}

function renderMetaOnly() {
  const n = state.list.length;
  const bits = [];
  if (state.mode === 'exact') bits.push('精确匹配 <b>' + n.toLocaleString() + '</b> 张');
  else if (state.mode === 'loose') bits.push('<b>' + n.toLocaleString() + '</b> 张弱匹配');
  else bits.push('共 <b>' + n.toLocaleString() + '</b> 张素材');
  if (n > state.shown) bits.push('已显示 ' + state.shown);
  $('#resultMeta').innerHTML = bits.join(' · ');
}

/* ---------------- 筛选面板 ---------------- */

function buildFacets() {
  const base = ALL.filter(p => !state.country || p.country === state.country);

  const cityMap = new Map();
  const sceneMap = new Map();
  for (const p of base) {
    if (p.city && p.city !== '其他') cityMap.set(p.city, (cityMap.get(p.city) || 0) + 1);
    if (p.scene && p.scene !== '其他') sceneMap.set(p.scene, (sceneMap.get(p.scene) || 0) + 1);
  }

  const sel = $('#citySel');
  const cities = [...cityMap.entries()].sort((a, b) => b[1] - a[1]);
  sel.innerHTML = '<option value="">全部城市</option>' +
    cities.map(([n, c]) => `<option value="${esc(n)}">${esc(n)} · ${c}</option>`).join('');
  if (state.city && cityMap.has(state.city)) sel.value = state.city;
  else if (state.city) { state.city = ''; sel.value = ''; }

  const scenes = [...sceneMap.entries()].sort((a, b) => b[1] - a[1]);
  const chips = [{ n: '', c: 0, label: '全部场景' }]
    .concat(scenes.map(([n, c]) => ({ n, c, label: n })));

  $('#sceneChips').innerHTML = chips.map(x =>
    `<button class="chip ${state.scene === x.n ? 'on' : ''}" data-scene="${esc(x.n)}">` +
    `${esc(x.label)}${x.c ? `<i>${x.c}</i>` : ''}</button>`).join('');

  $('#sceneChips').querySelectorAll('.chip').forEach(b => {
    b.addEventListener('click', () => {
      state.scene = b.dataset.scene;
      $('#sceneChips').querySelectorAll('.chip').forEach(x => x.classList.toggle('on', x === b));
      render();
    });
  });

  $('#statTotal').textContent = ALL.length.toLocaleString();

  const lowres = ALL.filter(p => p.width * p.height < 1000000).length;
  const wm = ALL.filter(p => p.wm).length;
  const ppl = ALL.filter(p => p.selfie || p.solo).length;
  const qi = $('#qinfo');
  if (qi) qi.textContent = `低清 ${lowres} · 疑似水印 ${wm} · 自拍/单人 ${ppl}`;
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
  const pv = previewUrl(p.thumb);
  img.onerror = () => { img.onerror = null; img.src = p.thumb; };
  img.src = pv;
  img.alt = p.title || '';

  $('#lbTitle').textContent = p.title || '未命名素材';

  $('#lbBadges').innerHTML = [
    p.country && `<span class="badge">${esc(p.country)}</span>`,
    p.city && p.city !== '其他' && `<span class="badge">${esc(p.city)}</span>`,
    p.scene && `<span class="badge gray">${esc(p.scene)}</span>`,
    p.orientation && `<span class="badge gray">${p.orientation === 'landscape' ? '横版' : p.orientation === 'portrait' ? '竖版' : '方图'}</span>`,
  ].filter(Boolean).join('');

  const rows = [
    ['尺寸', p.width ? `${p.width} × ${p.height}` : '—'],
    ['版权', p.license || '见来源页'],
    ['作者', p.artist || '未署名'],
  ];
  if (state.mode === 'exact' || state.mode === 'loose') {
    rows.unshift(['匹配度', (r.weak ? '弱匹配 · ' : '') + r.pct + '%']);
  }
  $('#lbMeta').innerHTML = rows.map(([k, v]) => `<dt>${k}</dt><dd>${esc(v)}</dd>`).join('');

  $('#lbDl').href = originalUrl(p.thumb);

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
  };

  $('#lbCopy').onclick = async () => {
    const txt = `${p.title} — ${p.artist || '未署名'} — ${p.license || ''} — ${p.page || ''}`;
    try { await navigator.clipboard.writeText(txt); $('#lbCopy').textContent = '已复制'; }
    catch { $('#lbCopy').textContent = '复制失败'; }
    setTimeout(() => { $('#lbCopy').textContent = '复制署名'; }, 1500);
  };

  $('#lbHide').onclick = () => {
    HIDDEN.add(p.id);
    persistHidden();
    $('#lbHide').textContent = '已隐藏';
    setTimeout(() => {
      closeLB();
      $('#lbHide').textContent = '隐藏此图（水印/人物）';
      buildFacets();
      render();
    }, 400);
  };

  const src = $('#lbSrc');
  if (p.page) { src.href = p.page; src.hidden = false; } else src.hidden = true;
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

function syncUrl() {
  const u = new URL(location.href);
  if (state.q) u.searchParams.set('q', state.q); else u.searchParams.delete('q');
  history.replaceState(null, '', u.toString());
}

function debounce(fn, ms) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

$('#q').addEventListener('input', debounce((e) => {
  state.q = e.target.value.trim();
  $('#clearq').hidden = !state.q;
  syncUrl();
  render();
}, 220));

$('#clearq').onclick = () => {
  $('#q').value = ''; state.q = ''; $('#clearq').hidden = true; syncUrl(); render();
};

$('#emptyClear').onclick = () => $('#clearq').click();

$('#countrySeg').addEventListener('click', (e) => {
  const b = e.target.closest('button');
  if (!b) return;
  $('#countrySeg').querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b));
  state.country = b.dataset.v;
  state.city = ''; state.scene = '';
  buildFacets();
  render();
});

$('#citySel').addEventListener('change', (e) => { state.city = e.target.value; render(); });

$('#orientSeg').addEventListener('click', (e) => {
  const b = e.target.closest('button');
  if (!b) return;
  $('#orientSeg').querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b));
  state.orient = b.dataset.v;
  render();
});

$('#savedOnly').addEventListener('change', (e) => { state.saved = e.target.checked; render(); });

$('#optHd').addEventListener('change', (e) => {
  state.minpx = e.target.checked ? 1000000 : 0;
  render();
});
$('#optWm').addEventListener('change', (e) => { state.nowm = e.target.checked; render(); });
$('#optSelfie').addEventListener('change', (e) => { state.noselfie = e.target.checked; render(); });
$('#optBlur').addEventListener('change', (e) => { state.noblur = e.target.checked; render(); });

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

(async function boot() {
  loadSaved();
  const heights = [220, 180, 260, 200, 240, 190, 230, 210];
  $('#grid').innerHTML = heights
    .map(h => `<div class="sk" style="height:${h}px"></div>`).join('');
  document.body.classList.add('is-searching');
  try {
    const res = await fetch('./data/library.json', { cache: 'no-cache' });
    const data = await res.json();
    ALL = data.items.map(x => {
      const p = {
        id: x.i, title: x.t, descr: x.d, city: x.c, scene: x.s, country: x.n,
        orientation: x.o, width: x.w, height: x.h, thumb: x.th, page: x.pg,
        license: x.li, artist: x.ar, selfie: x.sf, solo: x.so, wm: x.wm, blur: x.bl,
      };
      p._t = String(p.title || '').toLowerCase();
      p._f = [p.country, p.city, p.scene].join(' ').toLowerCase();
      p._st = [p.title, p.descr, p.country, p.city, p.scene, p.license].join(' ').toLowerCase();
      return p;
    });
    $('#statUpdate').textContent = data.updated ? data.updated.slice(5) : '—';
    buildVocab(ALL);
    $('#footInfo').textContent =
      `素材来自 Wikimedia Commons，共 ${ALL.length.toLocaleString()} 张，版权归原作者所有`;

    const q0 = new URL(location.href).searchParams.get('q') || '';
    if (q0) { state.q = q0; $('#q').value = q0; $('#clearq').hidden = false; }

    buildFacets();
    render();
    document.body.classList.remove('is-searching');
  } catch (err) {
    document.body.classList.remove('is-searching');
    $('#resultMeta').textContent = '素材索引加载失败，请刷新重试';
    console.error(err);
  }
})();
