from __future__ import annotations

import argparse
import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse

from .core import STAGES


STRATEGIES = (
    "model_random_pool",
    "model_seed_local",
    "model_seed_broad",
    "uniform_control",
)
SOURCES = ("learned", "uniform")
DEEP_STAGES = frozenset(STAGES[8:])


def _load_json_lines(path: Path) -> list[dict[str, Any]]:
    """Read a JSONL file while tolerating its last line being written concurrently."""
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                rows.append(value)
    return rows


def build_dashboard_data(path: Path) -> dict[str, Any]:
    rows = _load_json_lines(path)
    points: list[dict[str, Any]] = []
    for row in rows:
        comparisons = row.get("proposal_strategy_comparison", {})
        if not isinstance(comparisons, Mapping):
            comparisons = {}
        strategies: dict[str, dict[str, Any]] = {}
        for strategy in STRATEGIES:
            stats = comparisons.get(strategy, {})
            if not isinstance(stats, Mapping):
                stats = {}
            histogram = stats.get("terminal_stage_histogram", {})
            if not isinstance(histogram, Mapping):
                histogram = {}
            count = int(stats.get("count", 0) or 0)
            strategies[strategy] = {
                "count": count,
                "depth_sum": float(stats.get("mean_stage_index", 0.0) or 0.0)
                * count,
                "deep_count": sum(
                    int(histogram.get(stage, 0) or 0) for stage in DEEP_STAGES
                ),
            }
        source_comparisons = row.get("proposal_source_comparison", {})
        if not isinstance(source_comparisons, Mapping):
            source_comparisons = {}
        sources: dict[str, dict[str, Any]] = {}
        for source in SOURCES:
            stats = source_comparisons.get(source, {})
            if not isinstance(stats, Mapping):
                stats = {}
            reached = stats.get("stage_reached_counts", {})
            if not isinstance(reached, Mapping):
                reached = {}
            count = int(stats.get("count", 0) or 0)
            sources[source] = {
                "count": count,
                "depth_sum": float(stats.get("mean_stage_index", 0.0) or 0.0)
                * count,
                "reached": [int(reached.get(stage, 0) or 0) for stage in STAGES],
                "deep_count": int(reached.get(STAGES[8], 0) or 0),
            }
        learning_metrics = row.get("learning_metrics", {})
        if not isinstance(learning_metrics, Mapping):
            learning_metrics = {}
        points.append(
            {
                "generation": int(row.get("generation", len(points))),
                "timeouts": int(row.get("timeouts", 0) or 0),
                "max_stage": int(row.get("max_stage_index", 0) or 0),
                "seed_deepest": int(row.get("seed_deepest_stage_index", 0) or 0),
                "duplicate_rejections": sum(
                    int(value or 0)
                    for key, value in row.get("sampling_diagnostics", {}).items()
                    if "duplicate." in str(key)
                ),
                "strategies": strategies,
                "sources": sources,
                "learning_metrics": learning_metrics,
            }
        )
    return {
        "source": str(path.resolve()),
        "stages": list(STAGES),
        "deep_stage_index": 8,
        "points": points,
    }


HTML = r"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Mapping Lab — suivi</title>
<style>
:root { color-scheme: light dark; --bg:#f5f3ee; --panel:#fff; --ink:#20231f;
  --muted:#6d716b; --grid:#d8d8d0; --policy:#147d64; --replay:#cf6b32; --broad:#b33c78;
  --uniform:#6d72b5; --accent:#174f43; }
@media (prefers-color-scheme:dark) { :root { --bg:#171a18; --panel:#222623;
  --ink:#eff2ed; --muted:#aeb5ad; --grid:#424841; --policy:#52c8a5;
  --replay:#f49a62; --broad:#ef79b4; --uniform:#aeb2ff; --accent:#92dec8; } }
* { box-sizing:border-box } body { margin:0; background:var(--bg); color:var(--ink);
  font:15px/1.45 system-ui,sans-serif } main { max-width:1180px; margin:auto; padding:24px }
header { display:flex; gap:16px; align-items:center; justify-content:space-between; flex-wrap:wrap }
h1 { margin:0; font-size:24px } .controls { display:flex; gap:12px; align-items:center }
button { border:0; border-radius:7px; padding:9px 15px; color:white; background:var(--accent);
  cursor:pointer; font-weight:650 } button:hover { filter:brightness(1.1) }
.status { color:var(--muted); margin:5px 0 18px; overflow-wrap:anywhere }
.cards { display:grid; grid-template-columns:repeat(5,minmax(120px,1fr)); gap:10px; margin-bottom:14px }
.card,.chartbox,.help,.tablebox { background:var(--panel); border:1px solid var(--grid); border-radius:10px }
.card { padding:11px 14px } .card span { display:block; color:var(--muted); font-size:12px }
.card strong { display:block; font-size:21px; margin-top:2px }
.chartbox { padding:14px; margin:12px 0 } h2 { font-size:16px; margin:0 0 2px }
.subtitle { color:var(--muted); font-size:13px; margin-bottom:8px }
svg { width:100%; height:310px; display:block; overflow:visible }
.legend { display:flex; gap:18px; flex-wrap:wrap; margin:4px 0 0 54px; font-size:13px }
.key:before { content:""; display:inline-block; width:20px; height:3px; margin:0 6px 3px 0;
  background:var(--c) } .help { padding:14px 18px; margin-top:12px }
.help p { margin:5px 0 } code { font-family:ui-monospace,monospace }
.tablebox { padding:14px; margin:12px 0; overflow-x:auto } table { width:100%; border-collapse:collapse; font-size:13px }
th,td { padding:7px 9px; border-bottom:1px solid var(--grid); text-align:right; white-space:nowrap }
th:first-child,td:first-child { text-align:left } th { color:var(--muted); font-weight:650 }
@media(max-width:700px) { main{padding:12px}.cards{grid-template-columns:1fr 1fr} svg{height:260px} }
</style>
</head>
<body><main>
<header><h1>Mapping Lab — évolution de l’apprentissage</h1><div class="controls">
<label><input id="auto" type="checkbox" checked> auto (5 s)</label><button id="refresh">Rafraîchir</button>
</div></header>
<div id="status" class="status">Chargement…</div>
<section class="cards">
 <div class="card"><span>Dernière génération</span><strong id="generation">—</strong></div>
 <div class="card"><span>Meilleur étage mémorisé</span><strong id="deepest">—</strong></div>
 <div class="card"><span>Loss neurale récente</span><strong id="loss">—</strong></div>
 <div class="card"><span>Doublons refusés</span><strong id="duplicates">—</strong></div>
 <div class="card"><span>Timeouts (dernière génération)</span><strong id="timeouts">—</strong></div>
</section>
<section class="chartbox"><h2>Profondeur moyenne atteinte</h2>
 <div class="subtitle">Moyenne glissante sur 25 générations — plus haut est mieux.</div>
 <svg id="depth" role="img" aria-label="Profondeur moyenne par stratégie"></svg>
 <div class="legend"><span class="key" style="--c:var(--policy)">Sélection neurale</span>
 <span class="key" style="--c:var(--uniform)">Aléatoire témoin</span></div>
</section>
<section class="chartbox"><h2>Passages au niveau 8 ou au-delà</h2>
 <div class="subtitle">Taux pour 1 000 essais (ce n’est pas un numéro de niveau), moyenne glissante sur 100 générations.</div>
 <svg id="deep" role="img" aria-label="Taux de passages profonds par stratégie"></svg>
 <div class="legend"><span class="key" style="--c:var(--policy)">Sélection neurale</span>
 <span class="key" style="--c:var(--uniform)">Aléatoire témoin</span></div>
</section>
<section class="tablebox"><h2>Signal observé, filtre par filtre</h2><div class="subtitle">Effectifs cumulés : “entrés” ont atteint le filtre précédent, “passés” ont atteint le suivant.</div>
<table><thead><tr><th>Transition</th><th>Neural entrés</th><th>Neural passés</th><th>Neural %</th><th>Témoin entrés</th><th>Témoin passés</th><th>Témoin %</th></tr></thead><tbody id="transitions"></tbody></table></section>
<section class="tablebox"><h2>Ce que le réseau apprend sur la validation</h2><div class="subtitle">AUC = 0,5 : hasard ; AUC proche de 1 : séparation prédictive. Une tête inactive n’a pas encore les deux classes.</div>
<table><thead><tr><th>Transition</th><th>Exemples</th><th>Positifs</th><th>Taux</th><th>AUC</th><th>Log-loss</th><th>Active</th></tr></thead><tbody id="modelMetrics"></tbody></table></section>
<section class="help"><p><strong>Ce qu’on cherche :</strong> la courbe verte doit rester au-dessus du témoin violet et les AUC des goulets non triviaux doivent dépasser 0,5 sur la validation.</p>
<p>Le tableau conditionnel montre immédiatement si un palier fournit un signal abondant, rare, ou encore nul. Le second graphique mesure uniquement un taux pour 1 000 essais.</p></section>
</main>
<script>
const names={learned:'Sélection neurale',uniform:'Aléatoire'};
const colors={learned:'--policy',uniform:'--uniform'};
const ns='http://www.w3.org/2000/svg'; let timer=null;
function svgEl(tag,attrs={}){const e=document.createElementNS(ns,tag);for(const[k,v]of Object.entries(attrs))e.setAttribute(k,v);return e}
function rolling(points,key,windowSize){return points.map((p,i)=>{let count=0,sum=0,deep=0;
  for(let j=Math.max(0,i-windowSize+1);j<=i;j++){const s=points[j].sources[key];count+=s.count;sum+=s.depth_sum;deep+=s.deep_count}
  return {x:p.generation,depth:count?sum/count:null,deep:count?1000*deep/count:null}})}
function pct(a,b){return a?`${(100*b/a).toFixed(3)} %`:'—'}
function renderTables(data,points){const totals={learned:Array(data.stages.length).fill(0),uniform:Array(data.stages.length).fill(0)};
  for(const p of points)for(const source of Object.keys(totals))p.sources[source].reached.forEach((v,i)=>totals[source][i]+=v);
  const body=document.getElementById('transitions');body.replaceChildren();for(let i=4;i<data.stages.length;i++){const row=document.createElement('tr');const values=[`${i-1} ${data.stages[i-1]} → ${i} ${data.stages[i]}`,totals.learned[i-1],totals.learned[i],pct(totals.learned[i-1],totals.learned[i]),totals.uniform[i-1],totals.uniform[i],pct(totals.uniform[i-1],totals.uniform[i])];for(const value of values){const cell=document.createElement('td');cell.textContent=value;row.append(cell)}body.append(row)}
  const metricsBody=document.getElementById('modelMetrics');metricsBody.replaceChildren();const latest=points.at(-1)?.learning_metrics?.transitions||{};for(const[key,m]of Object.entries(latest)){const i=Number(key),row=document.createElement('tr');const values=[`${i-1} ${data.stages[i-1]} → ${i} ${data.stages[i]}`,m.eligible,m.positives,m.positive_rate==null?'—':`${(100*m.positive_rate).toFixed(3)} %`,m.auc==null?'—':m.auc.toFixed(3),m.log_loss==null?'—':m.log_loss.toFixed(4),m.active?'oui':'non'];for(const value of values){const cell=document.createElement('td');cell.textContent=value;row.append(cell)}metricsBody.append(row)}}
function chart(id,series,valueKey,yMin,yMax,yLabels){const svg=document.getElementById(id);svg.replaceChildren();
  const W=1000,H=310,L=145,R=18,T=15,B=42,plotW=W-L-R,plotH=H-T-B;svg.setAttribute('viewBox',`0 0 ${W} ${H}`);
  const all=series.flatMap(s=>s.values.filter(v=>v[valueKey]!=null));if(!all.length){const t=svgEl('text',{x:W/2,y:H/2,'text-anchor':'middle',fill:'currentColor'});t.textContent='Pas encore de données';svg.append(t);return}
  const xmin=Math.min(...all.map(v=>v.x)),xmax=Math.max(...all.map(v=>v.x)); if(yMax==null)yMax=Math.max(1,...all.map(v=>v[valueKey]));
  const X=x=>L+(x-xmin)/Math.max(1,xmax-xmin)*plotW,Y=y=>T+(yMax-y)/Math.max(.0001,yMax-yMin)*plotH;
  for(let i=0;i<=5;i++){const y=yMin+(yMax-yMin)*i/5,py=Y(y);svg.append(svgEl('line',{x1:L,x2:W-R,y1:py,y2:py,stroke:'var(--grid)','stroke-width':1}));
    const t=svgEl('text',{x:L-9,y:py+4,'text-anchor':'end',fill:'var(--muted)','font-size':12});t.textContent=yLabels?yLabels(y):y.toFixed(yMax<=10?1:0);svg.append(t)}
  for(let i=0;i<=4;i++){const x=xmin+(xmax-xmin)*i/4,px=X(x);const t=svgEl('text',{x:px,y:H-12,'text-anchor':'middle',fill:'var(--muted)','font-size':12});t.textContent=Math.round(x);svg.append(t)}
  const xlabel=svgEl('text',{x:W-R,y:H-12,'text-anchor':'end',fill:'var(--muted)','font-size':12});xlabel.textContent='génération';svg.append(xlabel);
  for(const s of series){const pts=s.values.filter(v=>v[valueKey]!=null);if(!pts.length)continue;const d=pts.map((v,i)=>`${i?'L':'M'}${X(v.x).toFixed(1)},${Y(v[valueKey]).toFixed(1)}`).join(' ');
    svg.append(svgEl('path',{d,fill:'none',stroke:`var(${colors[s.key]})`,'stroke-width':s.key==='uniform'?2:3,'stroke-dasharray':s.key==='uniform'?'7 5':'none','stroke-linejoin':'round'}))}}
async function refresh(){try{const response=await fetch('/api/data',{cache:'no-store'});if(!response.ok)throw new Error(await response.text());const data=await response.json(),p=data.points;
  document.getElementById('status').textContent=`${data.source} — ${p.length} générations lues — actualisé à ${new Date().toLocaleTimeString()}`;
  if(!p.length){chart('depth',[], 'depth',0,10);chart('deep',[],'deep',0,null);return}const last=p[p.length-1];
  document.getElementById('generation').textContent=last.generation;
  document.getElementById('deepest').textContent=`${last.seed_deepest} · ${data.stages[last.seed_deepest]||'?'}`;
  document.getElementById('loss').textContent=last.learning_metrics?.training_loss==null?'—':last.learning_metrics.training_loss.toFixed(4);
  document.getElementById('duplicates').textContent=last.duplicate_rejections;
  document.getElementById('timeouts').textContent=last.timeouts;
  const depthSeries=Object.keys(names).map(key=>({key,values:rolling(p,key,25)}));const deepSeries=Object.keys(names).map(key=>({key,values:rolling(p,key,100)}));
  chart('depth',depthSeries,'depth',3,Math.max(8,...depthSeries.flatMap(s=>s.values.map(v=>v.depth||0))),y=>{const i=Math.round(y);return Math.abs(i-y)<.15&&data.stages[i]?`${i} ${data.stages[i]}`:y.toFixed(1)});
  chart('deep',deepSeries,'deep',0,null,null);
  renderTables(data,p);
}catch(e){document.getElementById('status').textContent=`Erreur : ${e.message}`}}
document.getElementById('refresh').onclick=refresh;document.getElementById('auto').onchange=e=>{if(e.target.checked){timer=setInterval(refresh,5000)}else{clearInterval(timer)}};
refresh();timer=setInterval(refresh,5000);
</script></body></html>"""


def make_handler(source: Path) -> type[BaseHTTPRequestHandler]:
    class DashboardHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - standard-library callback name
            route = urlparse(self.path).path
            if route == "/":
                self._send(200, "text/html; charset=utf-8", HTML.encode("utf-8"))
            elif route == "/api/data":
                payload = json.dumps(build_dashboard_data(source)).encode("utf-8")
                self._send(200, "application/json; charset=utf-8", payload)
            else:
                self._send(404, "text/plain; charset=utf-8", b"Not found\n")

        def _send(self, status: int, content_type: str, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    return DashboardHandler


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Live Mapping Lab chart dashboard")
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("output/mapping_lab/wheel-6/generations.jsonl"),
        help="generations.jsonl to follow",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    source = args.input.resolve()
    server = ThreadingHTTPServer((args.host, args.port), make_handler(source))
    url = f"http://{args.host}:{args.port}/"
    print(f"Mapping Lab dashboard: {url}")
    print(f"Reading: {source}")
    print("Press Ctrl+C to stop.")
    if not args.no_browser:
        threading.Timer(0.25, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
