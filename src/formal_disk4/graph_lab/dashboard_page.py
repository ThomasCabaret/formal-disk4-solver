from __future__ import annotations


UNIFIED_DASHBOARD_HTML = r"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Formal Disk 4 — Graph Lab</title>
<style>
:root{color-scheme:light dark;--bg:#f3f1ea;--panel:#fff;--ink:#20231f;--muted:#69706a;
--line:#d8d6ce;--green:#157b61;--green-soft:#dcefe8;--orange:#c96b31;--orange-soft:#f7e2d3;
--blue:#4d63ad;--red:#b83e3e;--red-soft:#f7dddd;--yellow:#a06a12;--yellow-soft:#f8eccb}
@media(prefers-color-scheme:dark){:root{--bg:#171a18;--panel:#222623;--ink:#eff2ed;--muted:#aeb5ad;
--line:#424841;--green:#51c5a2;--green-soft:#183c32;--orange:#f09a63;--orange-soft:#4b2c1c;
--blue:#abb4ff;--red:#ff8582;--red-soft:#4c2222;--yellow:#f0c56f;--yellow-soft:#45391f}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.42 system-ui,sans-serif}
main{max-width:1500px;margin:auto;padding:20px}header{display:flex;align-items:flex-start;justify-content:space-between;
gap:18px;flex-wrap:wrap}h1{font-size:25px;margin:0}h2{font-size:19px;margin:0 0 4px}h3{font-size:15px;margin:0}
.muted{color:var(--muted)}.toolbar,.tabs,.pager{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
button,select{font:inherit;color:var(--ink);background:var(--panel);border:1px solid var(--line);border-radius:7px;padding:7px 11px;cursor:pointer}
button.active{background:var(--green);border-color:var(--green);color:#fff}.tabs{margin:18px 0 13px}.tab{font-weight:650}
.view[hidden]{display:none}.summary{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:9px;margin:12px 0}
.stat,.level,.candidate{background:var(--panel);border:1px solid var(--line);border-radius:10px}.stat{padding:10px 12px}
.stat span{display:block;color:var(--muted);font-size:12px}.stat strong{font-size:20px}.level{padding:14px;margin:12px 0}
.level-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;flex-wrap:wrap}.level-metrics{color:var(--muted)}
.nested-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:12px}.nested h3{text-align:center;margin-bottom:4px}
.nested svg{display:block;width:100%;height:auto;max-height:310px}.survival{font-size:12px;color:var(--muted);text-align:center;margin-top:2px}
.table-wrap{overflow-x:auto;margin-top:12px}table{width:100%;border-collapse:collapse;font-size:12px}th,td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
th:first-child,td:first-child{text-align:left;white-space:normal}th{color:var(--muted);font-weight:650}.positive{color:var(--green)}.negative{color:var(--red)}
.geometry-head{display:block}.geometry-head>.summary{width:100%;grid-template-columns:repeat(auto-fit,minmax(140px,1fr))}.candidate-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:11px;margin:12px 0}
.gallery-filters{display:flex;gap:18px;align-items:flex-start;flex-wrap:wrap;margin:10px 0 12px}.filter-group{display:flex;gap:9px;align-items:center;flex-wrap:wrap}.filter-group strong{font-size:12px;color:var(--muted)}.filter-group label{white-space:nowrap}
.candidate{padding:11px;position:relative;border-left-width:5px}.candidate.pizza{opacity:.72;border-left-color:var(--line)}
.candidate.important{border-left-color:var(--yellow)}.candidate.alert{border-left-color:var(--red);background:var(--red-soft)}
.candidate.solution_found{box-shadow:inset 0 0 0 1px var(--green)}.candidate.processing{box-shadow:inset 0 0 0 2px var(--orange)}
.candidate-title{display:flex;justify-content:space-between;gap:8px;align-items:start}.candidate code{font-size:11px;overflow-wrap:anywhere}
.candidate-sequence{font-size:17px;font-weight:650;margin-bottom:2px}
.badge{display:inline-block;border-radius:999px;padding:2px 7px;font-size:11px;background:var(--bg);border:1px solid var(--line);white-space:nowrap}
.badge.solution_found{background:var(--green-soft);color:var(--green)}.badge.rejected_certain{background:var(--red-soft);color:var(--red)}
.badge.no_solution_found{background:var(--yellow-soft);color:var(--yellow)}.badge.processing{background:var(--orange-soft);color:var(--orange)}
.candidate img{display:block;width:100%;aspect-ratio:18/13;object-fit:contain;margin-top:9px;border-radius:6px;background:#62676d}
.facts{display:flex;gap:8px;flex-wrap:wrap;color:var(--muted);font-size:12px;margin-top:7px}.reason{font-size:12px;margin-top:7px;overflow-wrap:anywhere}
.empty{padding:40px;text-align:center;color:var(--muted)}#status{margin-top:5px}.worker-error{color:var(--red);font-weight:650}
@media(max-width:720px){main{padding:12px}.nested-grid{grid-template-columns:1fr}.candidate-grid{grid-template-columns:1fr}}
</style></head><body><main>
<header><div><h1>Graph Lab</h1><div id="status" class="muted">Chargement…</div></div>
<div class="toolbar"><label><input id="auto" type="checkbox" checked> actualisation 5 s</label><button id="refresh">Rafraîchir</button></div></header>
<nav class="tabs" aria-label="Sections"><button class="tab active" data-view="learning">Apprentissage</button><button class="tab" data-view="geometry">Candidats géométriques</button></nav>
<section id="learning" class="view"><div id="lab-summary" class="summary"></div><div id="levels"></div></section>
<section id="geometry" class="view" hidden>
 <div class="geometry-head"><div><h2>File géométrique</h2><div id="worker" class="muted"></div></div><div id="geometry-summary" class="summary"></div></div>
 <div id="gallery-filters" class="gallery-filters">
  <div class="filter-group"><strong>Structures</strong><label><input type="checkbox" data-importance="pizza" checked> pizzas / anneaux</label><label><input type="checkbox" data-importance="important" checked> non triviales ≥ 12</label><label><input type="checkbox" data-importance="alert" checked> alertes &lt; 12</label></div>
  <div class="filter-group"><strong>États</strong><label><input type="checkbox" data-gallery-status="pending" checked> attente</label><label><input type="checkbox" data-gallery-status="processing" checked> en cours</label><label><input type="checkbox" data-gallery-status="solution_found" checked> solutions</label><label><input type="checkbox" data-gallery-status="rejected_certain" checked> rejets certains</label><label><input type="checkbox" data-gallery-status="no_solution_found" checked> inconclusifs</label></div>
 </div>
 <div class="pager"><button id="previous">Précédente</button><span id="page-label"></span><button id="next">Suivante</button><label>par page <select id="page-size"><option>25</option><option>50</option><option selected>100</option></select></label></div>
 <div id="candidate-grid" class="candidate-grid"></div>
</section>
<script>
const ns='http://www.w3.org/2000/svg';let payload=null,timer=null,page=1,refreshSequence=0;
const $=id=>document.getElementById(id);function el(tag,cls,text){const n=document.createElement(tag);if(cls)n.className=cls;if(text!=null)n.textContent=text;return n}
function pct(v){return v==null?'—':`${(100*v).toFixed(v<.01?2:1)} %`}function number(v){return v==null?'—':Number(v).toLocaleString('fr-FR')}
function bytes(v){if(v==null)return'—';const u=['o','Kio','Mio','Gio'];let i=0;while(v>=1024&&i<3){v/=1024;i++}return`${v.toFixed(i<2?0:2)} ${u[i]}`}
function stat(label,value,detail=''){const n=el('div','stat');n.append(el('span','',label),el('strong','',value));if(detail)n.append(el('div','muted',detail));return n}
function modeCell(s){return s&&s.eligible?`${number(s.passed)} / ${number(s.eligible)} · ${pct(s.rate)}`:'—'}
function nestedSvg(transitions,key){const W=420,H=300,cx=W/2,cy=H/2,maxW=380,maxH=255;let cumulative=1;const svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox',`0 0 ${W} ${H}`);svg.setAttribute('role','img');svg.setAttribute('aria-label',`Survie cumulée ${key}`);
 const outer=document.createElementNS(ns,'rect');for(const[k,v]of Object.entries({x:(W-maxW)/2,y:(H-maxH)/2,width:maxW,height:maxH,fill:'none',stroke:'var(--line)','stroke-width':2}))outer.setAttribute(k,v);svg.append(outer);
 transitions.forEach((t,i)=>{const rate=t[key]?.rate;if(rate==null)return;cumulative*=Math.max(0,Math.min(1,rate));const scale=Math.sqrt(cumulative),w=maxW*scale,h=maxH*scale,r=document.createElementNS(ns,'rect');const attrs={x:cx-w/2,y:cy-h/2,width:w,height:h,fill:key==='recent_learned'?'var(--green-soft)':'var(--orange-soft)',stroke:key==='recent_learned'?'var(--green)':'var(--orange)','stroke-width':Math.max(.6,1.6-i*.025),'fill-opacity':Math.min(.82,.16+i*.025)};for(const[k,v]of Object.entries(attrs))r.setAttribute(k,v);const title=document.createElementNS(ns,'title');title.textContent=`${t.to}: conditionnel ${pct(rate)}, cumulé ${pct(cumulative)}`;r.append(title);svg.append(r)});svg.dataset.survival=cumulative;return svg}
function renderLevel(level){const section=el('section','level'),head=el('div','level-head'),title=el('div'),comparison=level.comparison||{},paired=Boolean(comparison.required);title.append(el('h2','',level.title),el('div','muted',level.description));const s=level.summary||{},comparisonText=paired?` · ${number(comparison.statistics_generations)} générations appariées`:'';head.append(title,el('div','level-metrics',`${number(s.evaluated)} évaluations · ${number(s.geometry_ready)} geometry-ready · loss ${s.training_loss==null?'—':Number(s.training_loss).toFixed(4)}${comparisonText}`));section.append(head);
 if(paired&&!comparison.statistics_generations){section.append(el('div','empty','Comparaison en attente de nouvelles métriques appariées. Les anciennes cohortes non comparables ne sont plus affichées.'));return section}
 const grid=el('div','nested-grid');for(const [key,mode,label] of [['recent_random','exploration',paired?'Hasard dans les mêmes pools':'Témoin aléatoire récent'],['recent_learned','learned',paired?'Learning dans les mêmes pools':'Politique apprise récente']]){const box=el('div','nested'),outcome=level.recent_outcomes?.[mode]||{};box.append(el('h3','',label));const svg=nestedSvg(level.transitions,key);box.append(svg,el('div','survival',`Indice cumulé des filtres : ${pct(Number(svg.dataset.survival))} · issue réellement atteinte : ${number(outcome.successful)} / ${number(outcome.selected)} · ${pct(outcome.rate)}`));grid.append(box)}section.append(grid);
 const wrap=el('div','table-wrap'),table=el('table'),thead=el('thead'),hr=el('tr');['Filtre','Aléatoire récent','Learning récent','Gain','AUC','Diagnostic'].forEach(x=>hr.append(el('th','',x)));thead.append(hr);const tbody=el('tbody');for(const t of level.transitions){const tr=el('tr'),gain=t.learned_vs_random_pp;[t.to,modeCell(t.recent_random),modeCell(t.recent_learned),gain==null?'—':`${gain>=0?'+':''}${gain.toFixed(1)} pp`,t.model_auc==null?'—':Number(t.model_auc).toFixed(3),t.diagnosis].forEach((x,i)=>{const td=el('td',i===3&&gain!=null?(gain>=0?'positive':'negative'):'',x);tr.append(td)});tbody.append(tr)}table.append(thead,tbody);wrap.append(table);section.append(wrap);return section}
function renderLearning(){const levels=$('levels');levels.replaceChildren();for(const level of payload.levels)levels.append(renderLevel(level));const g=payload.levels[0]?.summary||{},cov=payload.coverage?.recent?.levels||{};$('lab-summary').replaceChildren(stat('Dernière génération',number(g.latest_generation)),stat('Rollouts de graphes',number(g.evaluated)),stat('Geometry-ready (visites)',number(g.geometry_ready),'pas des solutions distinctes'),stat('Graphes effectifs récents',cov.graph?Number(cov.graph.effective_ids).toFixed(1):'—'),stat('Sortie du training',g.max_training_bytes?`${bytes(g.training_output_bytes)} / ${bytes(g.max_training_bytes)}`:bytes(g.training_output_bytes)))}
const labels={pending:'En attente',processing:'Résolution en cours',solution_found:'Solution trouvée',rejected_certain:'Rejet certain',no_solution_found:'Recherche infructueuse'};
function candidateCard(item){const card=el('article',`candidate ${item.importance} ${item.status}`),head=el('div','candidate-title'),left=el('div');left.append(el('div','candidate-sequence',`Ligne ${number(item.last_line)}`),el('code','',item.formal_profile_id));if(item.importance==='alert')left.append(el('div','worker-error','★ Non-pizza de moins de 12 tuiles'));else if(item.pizza_kind==='uniform_orientation_ring')left.append(el('div','muted','Pizza / orientations uniformes'));else if(item.pizza_kind==='mixed_orientation_ring')left.append(el('div','muted','Anneau / orientations mixtes'));else if(item.importance==='pizza')left.append(el('div','muted','Anneau / pizza'));else left.append(el('div','muted','Structure non triviale'));head.append(left,el('span',`badge ${item.status}`,labels[item.status]||item.status));card.append(head);
 if(item.preview_url){const img=el('img');img.src=item.preview_url;img.alt=`Assemblage ${item.formal_profile_id}`;img.loading='lazy';card.append(img)}
 const facts=el('div','facts');[`tuiles ${item.tile_count}`,`arêtes ${item.edge_count}`,`symétrie imposée ${item.symmetry_order}`,`g${item.generation??'?'}`,`vu ${item.occurrences}×`].forEach(x=>facts.append(el('span','',x)));if(item.updated_utc){const d=new Date(item.updated_utc);if(!Number.isNaN(d.valueOf()))facts.append(el('span','',`géométrie ${d.toLocaleString('fr-FR')}`))}card.append(facts);if(item.reason)card.append(el('div','reason',item.reason));return card}
function renderGeometry(){const gallery=payload.gallery,counts=gallery.counts||{},worker=payload.worker||{};$('worker').textContent=`Worker : ${worker.phase||'inconnu'}${worker.current_profile_id?' · '+worker.current_profile_id:''}`;$('worker').className=worker.error?'worker-error':'muted';if(worker.error)$('worker').textContent+=` · ${worker.error}`;
 $('geometry-summary').replaceChildren(stat('Profils distincts',number(gallery.distinct_total)),stat('Émissions totales',number(gallery.occurrences_total)),stat('Affichés par les filtres',number(gallery.total)),stat('En attente',number(counts.pending)),stat('En cours',number(counts.processing)),stat('Solutions',number(counts.solution_found)),stat('Rejets certains',number(counts.rejected_certain)),stat('Inconclusifs',number(counts.no_solution_found)));
 const grid=$('candidate-grid');grid.replaceChildren();if(!gallery.items.length)grid.append(el('div','empty','Aucun candidat indexé.'));else for(const item of gallery.items)grid.append(candidateCard(item));page=gallery.page;$('page-label').textContent=`Page ${gallery.page} / ${gallery.pages}`;$('previous').disabled=gallery.page<=1;$('next').disabled=gallery.page>=gallery.pages}
function checkedValues(attribute){return [...document.querySelectorAll(`input[${attribute}]:checked`)].map(input=>input.getAttribute(attribute)).join(',')}
async function refresh(){const sequence=++refreshSequence;try{const size=Number($('page-size').value),importance=checkedValues('data-importance'),statuses=checkedValues('data-gallery-status'),query=new URLSearchParams({page:String(page),page_size:String(size),importance,statuses}),r=await fetch(`/api/data?${query}`,{cache:'no-store'});if(!r.ok)throw new Error(await r.text());const nextPayload=await r.json();if(sequence!==refreshSequence)return;payload=nextPayload;$('status').textContent=`Actualisé à ${new Date().toLocaleTimeString()} · ${payload.output}`;$('status').className='muted';renderLearning();renderGeometry()}catch(e){if(sequence!==refreshSequence)return;$('status').textContent=`Erreur : ${e.message}`;$('status').className='worker-error'}}
document.querySelectorAll('.tab').forEach(b=>b.onclick=()=>{document.querySelectorAll('.tab').forEach(x=>x.classList.toggle('active',x===b));document.querySelectorAll('.view').forEach(v=>v.hidden=v.id!==b.dataset.view)});
$('previous').onclick=()=>{page=Math.max(1,page-1);refresh()};$('next').onclick=()=>{page++;refresh()};$('page-size').onchange=()=>{page=1;refresh()};$('refresh').onclick=refresh;$('auto').onchange=e=>{clearInterval(timer);if(e.target.checked)timer=setInterval(refresh,5000)};refresh();timer=setInterval(refresh,5000);
document.querySelectorAll('#gallery-filters input').forEach(input=>input.onchange=()=>{page=1;refresh()});
</script></main></body></html>"""
