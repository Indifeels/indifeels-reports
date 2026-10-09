(function(){var C=["#F04A23","#F36227","#F5772A","#F8912F","#FBA52F","#FCB927","#FCD02B","#F2DA2D","#DFE02F","#BDD83A","#A2CF3E","#8DC83F","#76BF44","#5EBB4A"],pend={},old={},last={},tmr={};
function esc(t){return String(t).replace(/[&<>"']/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]})}
function box(){return '<span class="lkw"><input class="lki" type="text" inputmode="url" placeholder="Search product or paste link" aria-label="Search product or paste link" autocomplete="off"><button class="lkb" type="button">Track</button><span class="lke" role="status"></span><span class="lks" hidden></span></span>'}
function acts(){return '<span class="lka"><button class="lkp" type="button">Copy link</button><button class="lkc" type="button">Change</button><button class="lkx" type="button">Remove</button></span>'}
function img(u,w){return (u&&u.indexOf("https://cdn.shopify.com/")===0)?esc(u+(u.indexOf("?")>-1?"&":"?")+"width="+w):""}
function bar(r){var idx=Math.min(13,Math.floor(13*r.a/r.n+0.5)),g="";for(var i=0;i<14;i++)g+='<i style="background:'+C[i]+'"'+(i===idx?' class="mk"':'')+'></i>';
var im=img(r.image,140)?'<img class="stki" src="'+img(r.image,140)+'" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.style.display=\'none\'">':"";
return '<span class="stkw" title="'+esc(r.title)+': '+r.a+' of '+r.n+' variants in stock"><span class="stkc"><span class="stk">'+g+'</span><span class="stkl">'+r.a+' of '+r.n+' variants in stock</span>'+acts()+'</span><span class="stkr">'+im+'<span class="stkp">'+esc(r.title)+'</span></span></span>'}
function wrap(el){return el.closest('.lk')}
function post(o){try{parent.postMessage(o,'*');return true}catch(x){return false}}
function rid(aid){var r='l'+Date.now()+Math.random().toString(36).slice(2,6);pend[r]=aid;return r}
function copy(t,b){var done=function(ok){var o=b.textContent;b.textContent=ok?'Copied':'Copy failed';setTimeout(function(){b.textContent=o},1400)};
function fb(){try{var a=document.createElement('textarea');a.value=t;a.style.position='fixed';a.style.opacity='0';document.body.appendChild(a);a.select();var ok=document.execCommand('copy');document.body.removeChild(a);done(ok)}catch(e){done(false)}}
if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(t).then(function(){done(true)},fb)}else fb()}
var PR=null,coll={};
function prods(){if(PR===null){try{PR=JSON.parse(document.getElementById('prods').textContent)}catch(e){PR=[]}}return PR}
function chips(){var c={};prods().forEach(function(p){(p[5]||[]).forEach(function(n){if(!/^(all|home ?page|frontpage|featured|best ?sellers?)$/i.test(n))c[n]=(c[n]||0)+1})});return Object.keys(c).filter(function(n){return c[n]>=2}).sort(function(a,b){return c[b]-c[a]}).slice(0,10)}
function render(w){var l=w.querySelector('.lks'),i=w.querySelector('.lki');if(!l||!i)return;var aid=w.getAttribute('data-aid'),q=i.value.trim().toLowerCase(),words=q?q.split(/\s+/):[],cur=coll[aid]||'';
if(/^https?:\/\//.test(q)){l.hidden=true;return}
var ch=chips(),res=prods().filter(function(p){var t=p[0].toLowerCase();return words.every(function(x){return t.indexOf(x)>-1})&&(!cur||(p[5]||[]).indexOf(cur)>-1)});
if(!q&&!cur&&ch.length===0){l.hidden=true;return}
res.sort(function(a,b){return (b[3]>0)-(a[3]>0)||a[0].localeCompare(b[0])});
var h=(ch.length?'<div class="lch">'+ch.map(function(n){return '<button type="button" class="lc'+(n===cur?' on':'')+'" data-c="'+esc(n)+'">'+esc(n)+'</button>'}).join('')+'</div>':'');
h+='<div class="lsl">'+(res.length?res.slice(0,40).map(function(p){var im=img(p[2],80);return '<div class="lsi" data-url="https://indifeels.com/products/'+esc(p[1])+'">'+(im?'<img src="'+im+'" alt="" referrerpolicy="no-referrer" onerror="this.style.display=\'none\'">':'<i></i>')+'<span>'+esc(p[0])+'<small>'+p[3]+' of '+p[4]+' variants in stock</small></span></div>'}).join(''):'<div class="lse">No active product matches.</div>')+'</div>';
l.innerHTML=h;l.hidden=false}
function hideList(w){var l=w&&w.querySelector('.lks');if(l)l.hidden=true}
document.addEventListener('click',function(e){
var t=e.target;if(!t.closest)return;
var lc=t.closest('.lc');if(lc){var w1=wrap(lc),a1=w1.getAttribute('data-aid'),c1=lc.getAttribute('data-c');coll[a1]=(coll[a1]===c1)?'':c1;render(w1);return}
var it=t.closest('.lsi');if(it){var w0=wrap(it),i0=w0.querySelector('.lki');i0.value=it.getAttribute('data-url');hideList(w0);var tb=w0.querySelector('.lkb:not(.lkn)');if(tb)tb.click();return}
document.querySelectorAll('.lks:not([hidden])').forEach(function(l){if(!l.closest('.lk').contains(t))l.hidden=true});
var b=t.closest('.lkb,.lkc,.lkp,.lkx');if(!b)return;var w=wrap(b);if(!w)return;var aid=w.getAttribute('data-aid');
if(b.classList.contains('lkp')){var h=w.getAttribute('data-h');if(h)copy('https://indifeels.com/products/'+h,b);return}
if(b.classList.contains('lkx')){if(!b.getAttribute('data-sure')){b.setAttribute('data-sure','1');b.textContent='Tap again to remove';setTimeout(function(){if(b.isConnected){b.removeAttribute('data-sure');b.textContent='Remove'}},3000);return}b.disabled=true;b.textContent='Removing…';if(!post({type:'adset-link',action:'remove',aid:aid,req:rid(aid)})){b.disabled=false;b.textContent='Remove'}return}
if(b.classList.contains('lkc')){old[aid]=w.innerHTML;w.innerHTML=box().replace('<span class="lke"','<button class="lkb lkn" type="button">Cancel</button><span class="lke"');var i=w.querySelector('.lki');if(i)i.focus();return}
if(b.classList.contains('lkn')){if(old[aid]!==undefined)w.innerHTML=old[aid];return}
var inp=w.querySelector('.lki'),err=w.querySelector('.lke'),url=(inp&&inp.value||'').trim();
if(!/^https?:\/\//i.test(url)){err.textContent=url?'Pick a product from the list, or paste its link.':'Search a product or paste its link first.';return}
err.textContent='';b.disabled=true;b.textContent='Saving…';
if(!post({type:'adset-link',action:'set',aid:aid,url:url,req:rid(aid)})){err.textContent="Couldn't reach the app.";b.disabled=false;b.textContent='Track'}});
document.addEventListener('input',function(e){var i=e.target;if(!i.classList||!i.classList.contains('lki'))return;var w=wrap(i),aid=w.getAttribute('data-aid'),q=i.value.trim(),l=w.querySelector('.lks');
if(prods().length){render(w);return}
clearTimeout(tmr[aid]);if(q.length<2||/^https?:\/\//i.test(q)){if(l)l.hidden=true;return}
tmr[aid]=setTimeout(function(){var r=rid(aid);last[aid]=r;if(l){l.hidden=false;l.innerHTML='<div class="lse">Searching…</div>'}post({type:'adset-link',action:'search',aid:aid,q:q,req:r})},250)});
document.addEventListener('focusin',function(e){var i=e.target;if(i.classList&&i.classList.contains('lki')&&prods().length)render(wrap(i))});
document.addEventListener('keydown',function(e){if(e.target.classList&&e.target.classList.contains('lki')){if(e.key==='Enter'){var w=wrap(e.target),b=w&&w.querySelector('.lkb:not(.lkn)');if(b)b.click()}else if(e.key==='Escape')hideList(wrap(e.target))}});
function applyList(items){(items||[]).forEach(function(it){var w=document.querySelector('.lk[data-aid="'+String(it.adset_id).replace(/[^0-9]/g,'')+'"]');var qi=w&&w.querySelector('.lki');if(!w||(qi&&(qi.value||document.activeElement===qi)))return;
var cur=w.getAttribute('data-h')||'';
if(it.handle==='-'){if(cur){w.removeAttribute('data-h');w.innerHTML=box()}return}
if(it.handle===cur)return;var p=prods().filter(function(x){return x[1]===it.handle})[0];if(!p)return;
w.setAttribute('data-h',it.handle);w.innerHTML=bar({title:p[0],a:p[3],n:p[4],image:p[2]})})}
// the report is a snapshot from its last build, so ask the app for the links saved since then
try{parent.postMessage({type:'adset-link',action:'list',aid:'0',req:'list'},'*')}catch(x){}
window.addEventListener('message',function(e){var d=e.data||{};if(d.type!=='adset-link-result')return;var aid=pend[d.req]||d.aid;delete pend[d.req];
if(d.action==='list'){if(d.ok)applyList(d.items);return}
var w=document.querySelector('.lk[data-aid="'+String(aid).replace(/[^0-9]/g,'')+'"]');if(!w)return;
if(d.action==='search'){if(last[aid]!==d.req)return;var l=w.querySelector('.lks');if(!l)return;
if(!d.ok){l.innerHTML='<div class="lse">'+esc(d.error||"Search failed")+'</div>';return}
var it=d.items||[];l.innerHTML=it.length?it.map(function(p){var im=img(p.image,80);return '<div class="lsi" data-url="https://indifeels.com/products/'+esc(p.handle)+'">'+(im?'<img src="'+im+'" alt="" referrerpolicy="no-referrer" onerror="this.style.display=\'none\'">':'<i></i>')+'<span>'+esc(p.title)+'<small>'+p.a+' of '+p.n+' variants in stock</small></span></div>'}).join(''):'<div class="lse">No active product matches that name.</div>';l.hidden=false;return}
if(d.ok&&d.action==='remove'){w.removeAttribute('data-h');w.innerHTML=box();return}
if(d.ok&&d.action==='set'&&d.n){if(d.handle)w.setAttribute('data-h',d.handle);var a2=d.a,n2=d.n,p2=prods().filter(function(p){return p[1]===d.handle})[0];if(p2&&!d.live){a2=p2[3];n2=p2[4]}w.innerHTML=bar({title:d.title,a:a2,n:n2,image:d.image});return}
var err=w.querySelector('.lke'),b=w.querySelector('.lkb:not(.lkn)'),x=w.querySelector('.lkx');if(err)err.textContent=d.error||"Couldn't save the link.";if(b){b.disabled=false;b.textContent='Track'}if(x){x.disabled=false;x.textContent='Remove'}});
// full screen: the app shell enlarges this report's frame
var fs=false;function setFs(on){fs=on;var b=document.getElementById('fsb');if(b)b.innerHTML=on?'&#x2715; Exit full screen':'&#x26F6; Full screen';post({type:'report-fullscreen',on:on})}
document.addEventListener('click',function(e){if(e.target.closest&&e.target.closest('#fsb'))setFs(!fs)});
document.addEventListener('keydown',function(e){if(e.key==='Escape'&&fs)setFs(false)});
window.addEventListener('message',function(e){var d=e.data||{};if(d.type==='report-fullscreen-state'&&fs!==!!d.on){fs=!!d.on;var b=document.getElementById('fsb');if(b)b.innerHTML=fs?'&#x2715; Exit full screen':'&#x26F6; Full screen'}});
})();
