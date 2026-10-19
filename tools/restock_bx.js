/*BXJS_START*/
const bxEsc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const bxEff = r => r.ship_qty == null ? r.qty : r.ship_qty;
const bxFmt = d => d.toLocaleDateString(undefined, {day: 'numeric', month: 'short', year: 'numeric'});
const bxShipDate = b => b.ship_date ? new Date(b.ship_date + 'T00:00:00') : b.shipped_at ? new Date(b.shipped_at) : null;
const bxAgo = d => { const n = Math.max(0, Math.floor((Date.now() - d.getTime()) / 86400000)); return n === 0 ? 'today' : n + (n === 1 ? ' day' : ' days') + ' ago'; };
const bxUrl = u => /^https?:\/\//i.test(u || '') ? u : '';
const bxLink = u => /^https:\/\//.test(u || '') ? bxEsc(u) : '';
const bxImg0 = r => { const s = r.image ? bxEsc(r.image) + (r.image.includes('?') ? '&' : '?') + 'width=200' : ''; return s ? `<img src="${s}" alt="" referrerpolicy="no-referrer" onerror="this.outerHTML='<div class=ph></div>'">` : '<div class="ph"></div>'; };
/* product image, linked to the product page (new tab) when we know it */
const bxImg = r => { const u = bxLink(r.product_url); return u ? `<a class="pl" href="${u}" target="_blank" rel="noopener noreferrer" title="Open product page">${bxImg0(r)}</a>` : bxImg0(r); };
/* product name, linked the same way */
const bxName = r => { if (!r.product_title) return ''; const u = bxLink(r.product_url), t = bxEsc(r.product_title); return `<div class="pn">${u ? `<a href="${u}" target="_blank" rel="noopener noreferrer" title="Open product page">${t} ↗</a>` : t}</div>`; };
const bxByVariant = (a, b) => String(a.variant_title).localeCompare(String(b.variant_title), undefined, {numeric: true});
function bxGroup(list) { const m = new Map(); list.forEach(r => { if (!m.has(r.product_id)) m.set(r.product_id, []); m.get(r.product_id).push(r); }); return [...m.values()]; }
const bxToday = () => { const d = new Date(); return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0'); };

/* Delete-box control: only the newest open box can be deleted; its items move to another open box or back to the order list. */
function bxDel(b, n, others, o) {
  if (o.lastOpen && o.lastOpen !== b.box_no) return `<span class="bx-note">To delete this box, delete ${bxEsc(o.lastOpen)} first.</span>`;
  const armed = o.armDel === b.box_no, sel = o.delTo || (others.length ? others[0] : '__master');
  const pick = (n && others.length) ? `<label class="bx-mvto">Move its ${n} item${n === 1 ? '' : 's'} to<select data-delto>${others.map(x => `<option value="${bxEsc(x)}"${sel === x ? ' selected' : ''}>${bxEsc(x)}</option>`).join('')}<option value="__master"${sel === '__master' ? ' selected' : ''}>↩ Order list</option></select></label>` : '';
  return pick + `<button class="danger${armed ? ' arm' : ''}" data-delbox="${bxEsc(b.box_no)}">${armed ? 'Tap again to delete' : 'Delete box'}</button>`;
}

/* Supplier-only "permanently discontinued" button (two taps). Hidden unless o.canDisc; shows a waiting pill once sent. */
const bxDisc = (pid, o) => {
  if (!o || !o.canDisc) return '';
  pid = String(pid);
  if (o.discPend && o.discPend.has(pid)) return '<span class="dq">⏳ Discontinue sent · waiting for the owner to confirm</span>';
  const a = o.armDisc === pid;
  return `<button class="danger dsc${a ? ' arm' : ''}" data-disc="${bxEsc(pid)}">${a ? 'Sure it’s permanently discontinued? Tap again' : 'Permanently discontinued?'}</button>`;
};

/* One box tile. b = box row, lines = its order lines, o = {ro, open, who, openBoxes}. */
function bxTile(b, lines, o) {
  const shipped = b.status === 'shipped', units = lines.reduce((a, r) => a + bxEff(r), 0), n = lines.length;
  const d = shipped ? bxShipDate(b) : null, url = bxUrl(b.tracking_url);
  const live = lines.filter(r => r.status === 'shipped').length, rem = o.rem || (() => 0);
  const head = `<div class="bx-h" data-bxt="${bxEsc(b.box_no)}"><span class="chev">▶</span>
    <span class="bx-title">${bxEsc(b.box_no)}${o.who ? ' · ' + bxEsc(o.who) : ''}</span>
    <span class="bx-pill ${shipped ? 'sh' : 'op'}">${shipped ? 'Shipped' : 'Packing'}</span>
    <span class="bx-sum">${n} item${n === 1 ? '' : 's'} added · ${units} unit${units === 1 ? '' : 's'}</span>
    <span class="bx-right">${(o.recv && live) ? '<button class="recvbox" data-recvbox="' + bxEsc(b.box_no) + '" title="Everything in this box arrived">Whole box received</button>' : ''}${shipped && d ? '<span>🚚 Shipped ' + bxFmt(d) + ' · ' + bxAgo(d) + '</span>' : ''}${url ? '<a class="bx-trkl" href="' + bxEsc(url) + '" target="_blank" rel="noopener noreferrer">🔗 Track parcel' + (b.tracking_no ? ' · ' + bxEsc(b.tracking_no) : '') + ' ↗</a>' : (b.tracking_no ? '<span>Tracking ' + bxEsc(b.tracking_no) + '</span>' : '')}</span></div>`;
  const others = (o.openBoxes || []).filter(x => x !== b.box_no);
  const mvSel = (key, label) => `<select data-mvg="${bxEsc(key)}"><option value="">${label}</option>${others.map(x => `<option value="${bxEsc(x)}">${bxEsc(x)}</option>`).join('')}<option value="__master">↩ Back to order list</option></select>`;
  const selN = o.selP ? [...o.selP].filter(k => k.startsWith(b.box_no + '|')).length : 0;
  const rows = g => `<div class="bx-prod">${bxImg(g[0])}<div class="pc">${(!o.ro && !shipped) ? `<div class="pnrow">${bxName(g[0]) || '<div class="pn"></div>'}<span class="pmv"><label class="ck"><input type="checkbox" data-selp="${bxEsc(b.box_no + '|' + g[0].product_id)}" ${(o.selP && o.selP.has(b.box_no + '|' + g[0].product_id)) ? 'checked' : ''}> Select</label></span></div><div class="pact"><label class="bx-mvto">Move whole product (${g.length} variant${g.length === 1 ? '' : 's'}) to<select data-mvg="${bxEsc('p:' + b.box_no + '|' + g[0].product_id)}"><option value="">Choose box…</option>${others.map(x => `<option value="${bxEsc(x)}">${bxEsc(x)}</option>`).join('')}<option value="__master">↩ Back to order list</option></select></label>${bxDisc(g[0].product_id, o)}</div>` : bxName(g[0])}<table><thead><tr><th>Variant</th><th style="text-align:center">Ordered</th><th style="text-align:center">${shipped ? 'Packed' : 'Packed'}</th>${(!o.ro && !shipped) ? '<th>Move / remove</th>' : '<th></th>'}</tr></thead><tbody>
    ${g.slice().sort(bxByVariant).map(r => { const more = rem(r), recvd = r.status === 'received', canRecv = o.recv && r.status === 'shipped';
      return `<tr><td>${bxEsc(r.variant_title)}${r.wrong_pick ? '<span class="wp" title="Tagged to another supplier">⚠ wrong pick</span>' : ''}<span class="sub">Ordered ${r.saved_at ? bxFmt(new Date(r.saved_at)) : ''}</span></td><td class="q">${r.qty}${more > 0 ? '<span class="low" title="Still on the order list, not in this box">+' + more + ' more ordered</span>' : ''}</td>
      <td class="q">${(!o.ro && !shipped) ? `<span class="stp"><button data-q="-1" data-id="${bxEsc(r.id)}" ${bxEff(r) <= 0 ? 'disabled' : ''}>−</button><b>${bxEff(r)}</b><button data-q="1" data-id="${bxEsc(r.id)}" ${bxEff(r) >= r.qty ? 'disabled' : ''}>+</button></span>` : bxEff(r)}${bxEff(r) < r.qty ? '<span class="low">short ' + (r.qty - bxEff(r)) + '</span>' : ''}</td>
      <td class="st">${(!o.ro && !shipped) ? `<span style="display:inline-flex;gap:8px;align-items:center"><select data-mv="${bxEsc(r.id)}"><option value="">Move to…</option>${others.map(x => `<option value="${bxEsc(x)}">${bxEsc(x)}</option>`).join('')}<option value="__master">↩ Back to order list</option></select><button class="x" data-rm="${bxEsc(r.id)}" title="Remove from this box (back to the order list)">✕</button></span>` : recvd ? '<span class="low" style="background:var(--green-bg);color:var(--green)">✅ Received</span>' : canRecv ? `<button class="recv" data-recv="${bxEsc(r.id)}">Received</button>` : ''}</td></tr>`; }).join('')}
    </tbody></table></div></div>`;
  let body = n ? bxGroup(lines).map(rows).join('') : `<div class="bx-empty">Nothing in this box yet. Pick items from the order list and press “Add to box”.</div>`;
  if (!o.ro && !shipped) {
    body += `<div class="bx-ship" data-shipbox="${bxEsc(b.box_no)}"><label>Ship date<input type="date" class="bx-date" value="${bxToday()}"></label>
      <label>Tracking link (optional)<input type="text" class="bx-url u" placeholder="https://…" maxlength="500"></label>
      <label>Tracking number (optional)<input type="text" class="bx-no" maxlength="80"></label>
      <button class="primary" data-ship="${bxEsc(b.box_no)}" ${n ? '' : 'disabled'}>Ship this box</button>
      ${n && others.length ? `<span class="bx-mvbox">${mvSel('a:' + b.box_no, 'Move all to…')}${selN ? mvSel('s:' + b.box_no, 'Move selected (' + selN + ') to…') : ''}</span>` : ''}
      ${bxDel(b, n, others, o)}
      <span class="bx-note">When shipped, the next item you add starts the next box.</span></div>`;
  }
  let trkHtml = '';
  if (shipped) {
    trkHtml = o.ro ? ((url || b.tracking_no) ? `<div class="bx-trk"><span><b>Tracking</b> ${b.tracking_no ? bxEsc(b.tracking_no) : ''} ${url ? '<a href="' + bxEsc(url) + '" target="_blank" rel="noopener noreferrer">' + bxEsc(url.length > 60 ? url.slice(0, 57) + '…' : url) + '</a>' : ''}</span></div>` : '')
      : `<div class="bx-trk" data-trkbox="${bxEsc(b.box_no)}"><label>Tracking link<input type="text" class="bx-url u" value="${bxEsc(b.tracking_url || '')}" placeholder="https://…" maxlength="500"></label>
      <label>Tracking number<input type="text" class="bx-no" value="${bxEsc(b.tracking_no || '')}" maxlength="80"></label><button data-trk="${bxEsc(b.box_no)}">Save tracking</button></div>`;
  }
  if (trkHtml) body = trkHtml + body;
  return `<section class="bx${o.open ? ' open' : ''}" data-bx="${bxEsc(b.box_no)}">${head}<div class="bx-body">${body}</div></section>`;
}

/* Collapsible section tile: Order list / Packing / Shipped. Click the bar to open. */
const bxSecOpen = new Map();
const bxSec = (key, title, count, body, o) => { const open = bxSecOpen.has(key) ? bxSecOpen.get(key) : !!(o && o.open);
  return `<section class="sc sc-${bxEsc((o && o.cls) || String(key).replace(/^(sv|my)-/, ''))}${open ? ' open' : ''}" data-sc="${bxEsc(key)}"><div class="sc-h" data-sct="${bxEsc(key)}"><span class="chev">▶</span><span class="sc-t">${title}</span><span class="sc-n">${count}</span><span class="sc-hint"><i class="h-c">Click to open</i><i class="h-o">Click to close</i></span></div><div class="sc-body">${body}</div></section>`; };
document.addEventListener('click', e => {
  const h = e.target.closest('[data-sct]'); if (!h || e.target.closest('a, input, select, button, label')) return;
  const sc = h.closest('.sc'); sc.classList.toggle('open'); bxSecOpen.set(h.getAttribute('data-sct'), sc.classList.contains('open'));
});
const bxPlural = (n, w) => n + ' ' + (n === 1 ? w : w === 'box' ? 'boxes' : w + 's');
/*BXJS_END*/
