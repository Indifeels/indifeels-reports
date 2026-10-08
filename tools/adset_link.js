(function(){var C=["#F04A23","#F36227","#F5772A","#F8912F","#FBA52F","#FCB927","#FCD02B","#F2DA2D","#DFE02F","#BDD83A","#A2CF3E","#8DC83F","#76BF44","#5EBB4A"],pend={},old={};
function esc(t){return String(t).replace(/[&<>"']/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]})}
function box(){return '<span class="lkw"><input class="lki" type="url" inputmode="url" placeholder="Paste product link to track stock" aria-label="Product link"><button class="lkb" type="button">Track</button><span class="lke" role="status"></span></span>'}
function bar(r){var idx=Math.min(13,Math.floor(13*r.a/r.n+0.5)),g="";for(var i=0;i<14;i++)g+='<i style="background:'+C[i]+'"'+(i===idx?' class="mk"':'')+'></i>';
var im=(r.image&&r.image.indexOf("https://cdn.shopify.com/")===0)?'<img class="stki" src="'+esc(r.image+(r.image.indexOf("?")>-1?"&":"?")+"width=140")+'" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.style.display=\'none\'">':"";
return '<span class="stkw" title="'+esc(r.title)+': '+r.a+' of '+r.n+' variants in stock"><span class="stkc"><span class="stk">'+g+'</span><span class="stkl">'+r.a+' of '+r.n+' variants in stock</span><button class="lkc" type="button">Change</button></span><span class="stkr">'+im+'<span class="stkp">'+esc(r.title)+'</span></span></span>'}
function wrap(el){return el.closest('.lk')}
document.addEventListener('click',function(e){var b=e.target.closest&&e.target.closest('.lkb,.lkc');if(!b)return;var w=wrap(b);if(!w)return;var aid=w.getAttribute('data-aid');
if(b.classList.contains('lkc')){old[aid]=w.innerHTML;w.innerHTML=box().replace('<span class="lke"','<button class="lkb lkn" type="button">Cancel</button><span class="lke"');var i=w.querySelector('.lki');if(i)i.focus();return}
if(b.classList.contains('lkn')){if(old[aid]!==undefined)w.innerHTML=old[aid];return}
var inp=w.querySelector('.lki'),err=w.querySelector('.lke'),url=(inp&&inp.value||'').trim();
if(!url){err.textContent='Paste the product link first.';return}
err.textContent='';b.disabled=true;b.textContent='Saving…';var req='l'+Date.now()+Math.random().toString(36).slice(2,6);pend[req]=aid;
try{parent.postMessage({type:'adset-link',action:'set',aid:aid,url:url,req:req},'*')}catch(x){err.textContent="Couldn't reach the app.";b.disabled=false;b.textContent='Track'}});
document.addEventListener('keydown',function(e){if(e.key==='Enter'&&e.target.classList&&e.target.classList.contains('lki')){var w=wrap(e.target),b=w&&w.querySelector('.lkb:not(.lkn)');if(b)b.click()}});
window.addEventListener('message',function(e){var d=e.data||{};if(d.type!=='adset-link-result')return;var aid=pend[d.req]||d.aid;delete pend[d.req];
var w=document.querySelector('.lk[data-aid="'+String(aid).replace(/[^0-9]/g,'')+'"]');if(!w)return;
if(d.ok&&d.action==='set'&&d.n){w.innerHTML=bar({title:d.title,a:d.a,n:d.n,image:d.image});return}
var err=w.querySelector('.lke'),b=w.querySelector('.lkb:not(.lkn)');if(err)err.textContent=d.error||"Couldn't save the link.";if(b){b.disabled=false;b.textContent='Track'}});})();
