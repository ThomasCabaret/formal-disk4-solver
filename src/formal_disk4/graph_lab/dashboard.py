from __future__ import annotations

import argparse
import json
import math
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse

from .evaluator import GRAPH_STAGES


def _load_json_lines(path: Path) -> list[dict[str, Any]]:
    """Read durable JSONL rows and ignore a concurrently written final line."""

    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        for line in stream:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                rows.append(value)
    rows.sort(key=lambda row: int(row.get("generation", 0)))
    return rows


def _blank_transition() -> dict[str, float | int | None]:
    return {
        "eligible": 0,
        "passed": 0,
        "prediction_sum": 0.0,
        "prediction_count": 0,
        "rate": None,
        "predicted_rate": None,
    }


def _aggregate(
    rows: Sequence[Mapping[str, Any]],
    mode: str,
    transition_ids: Sequence[str],
    collection_key: str,
) -> list[dict[str, float | int | None]]:
    totals = [_blank_transition() for _stage in transition_ids]
    for row in rows:
        modes = row.get("selection_modes", {})
        if not isinstance(modes, Mapping):
            continue
        mode_data = modes.get(mode, {})
        if not isinstance(mode_data, Mapping):
            continue
        transitions = mode_data.get(collection_key, {})
        if not isinstance(transitions, Mapping):
            continue
        for index, stage in enumerate(transition_ids):
            source = transitions.get(stage, {})
            if not isinstance(source, Mapping):
                continue
            target = totals[index]
            for key in ("eligible", "passed", "prediction_count"):
                target[key] = int(target[key] or 0) + int(source.get(key, 0) or 0)
            target["prediction_sum"] = float(
                target["prediction_sum"] or 0.0
            ) + float(source.get("prediction_sum", 0.0) or 0.0)
    for total in totals:
        eligible = int(total["eligible"] or 0)
        predicted = int(total["prediction_count"] or 0)
        total["rate"] = float(total["passed"] or 0) / eligible if eligible else None
        total["predicted_rate"] = (
            float(total["prediction_sum"] or 0.0) / predicted
            if predicted
            else None
        )
    return totals


def _percentage_point_delta(left: object, right: object) -> float | None:
    if left is None or right is None:
        return None
    return 100.0 * (float(left) - float(right))


def _diagnosis(
    baseline: Mapping[str, object],
    recent_random: Mapping[str, object],
    recent_learned: Mapping[str, object],
) -> str:
    if int(baseline.get("eligible", 0) or 0) < 20:
        return "Initial sample too small"
    if int(baseline.get("passed", 0) or 0) == 0:
        return "No positive signal in the initial control"
    if int(recent_learned.get("eligible", 0) or 0) < 20:
        return "Recent learned sample too small"
    learned_rate = recent_learned.get("rate")
    random_rate = recent_random.get("rate")
    baseline_rate = baseline.get("rate")
    if learned_rate is None:
        return "No recent learned examples reach the previous stage"
    notes = []
    if float(learned_rate) >= 0.9:
        notes.append("strong learned passage")
    elif random_rate is not None and float(learned_rate) >= float(random_rate) + 0.2:
        notes.append("clear enrichment")
    elif random_rate is not None and float(learned_rate) <= float(random_rate) + 0.05:
        notes.append("little learned enrichment")
    else:
        notes.append("moderate enrichment")
    if (
        random_rate is not None
        and baseline_rate is not None
        and int(recent_random.get("eligible", 0) or 0) >= 20
        and float(random_rate) + 0.1 < float(baseline_rate)
    ):
        notes.append("recent pool is harder / possible exhaustion")
    return "; ".join(notes)


def build_dashboard_data(
    path: Path,
    *,
    window_generations: int = 50,
    max_points: int = 400,
) -> dict[str, Any]:
    rows = _load_json_lines(path)
    window = max(1, int(window_generations))
    if not rows:
        return {
            "source": str(path.resolve()),
            "stages": list(GRAPH_STAGES),
            "window_generations": window,
            "points": [],
            "transitions": [],
            "summary": {},
        }

    mapping_mode = isinstance(rows[-1].get("filter_order"), Sequence)
    weak_order_mode = str(rows[-1].get("schema_version", "")).startswith(
        "graph-lab-weak-order-"
    )
    transition_ids = (
        tuple(str(value) for value in rows[-1].get("filter_order", ()))
        if mapping_mode
        else GRAPH_STAGES[1:]
    )
    stage_labels = (
        (
            "weak_order.state" if weak_order_mode else "mapping.sampled",
            *transition_ids,
        )
        if mapping_mode
        else GRAPH_STAGES
    )
    collection_key = "filters" if mapping_mode else "transitions"
    baseline_rows = rows[:window]
    recent_rows = rows[-window:]
    baseline = _aggregate(
        baseline_rows, "exploration", transition_ids, collection_key
    )
    recent_random = _aggregate(
        recent_rows, "exploration", transition_ids, collection_key
    )
    recent_learned = _aggregate(
        recent_rows, "learned", transition_ids, collection_key
    )

    latest_model = rows[-1].get("model", {})
    if not isinstance(latest_model, Mapping):
        latest_model = {}
    model_transitions = latest_model.get(collection_key, {})
    if not isinstance(model_transitions, Mapping):
        model_transitions = {}

    transitions = []
    for index, stage in enumerate(transition_ids):
        model = model_transitions.get(stage, {})
        if not isinstance(model, Mapping):
            model = {}
        transitions.append(
            {
                "index": index,
                "from": stage_labels[index],
                "to": stage,
                "baseline": baseline[index],
                "recent_random": recent_random[index],
                "recent_learned": recent_learned[index],
                "learned_vs_baseline_pp": _percentage_point_delta(
                    recent_learned[index]["rate"], baseline[index]["rate"]
                ),
                "learned_vs_random_pp": _percentage_point_delta(
                    recent_learned[index]["rate"], recent_random[index]["rate"]
                ),
                "model_auc": model.get(
                    "binary_auc" if mapping_mode else "auc"
                ),
                "model_active": bool(model.get("active", False)),
                "diagnosis": _diagnosis(
                    baseline[index], recent_random[index], recent_learned[index]
                ),
            }
        )

    stride = max(1, math.ceil(len(rows) / max(1, int(max_points))))
    endpoints = list(range(stride - 1, len(rows), stride))
    if not endpoints or endpoints[-1] != len(rows) - 1:
        endpoints.append(len(rows) - 1)
    points = []
    for end in endpoints:
        rolling_rows = rows[max(0, end - window + 1) : end + 1]
        random_stats = _aggregate(
            rolling_rows, "exploration", transition_ids, collection_key
        )
        learned_stats = _aggregate(
            rolling_rows, "learned", transition_ids, collection_key
        )
        points.append(
            {
                "generation": int(rows[end].get("generation", end)),
                "random": [item["rate"] for item in random_stats],
                "learned": [item["rate"] for item in learned_stats],
            }
        )

    total_evaluated = sum(int(row.get("evaluated", 0) or 0) for row in rows)
    total_geometry = sum(int(row.get("geometry_ready", 0) or 0) for row in rows)
    return {
        "source": str(path.resolve()),
        "stages": list(stage_labels),
        "kind": (
            "weak_order"
            if weak_order_mode
            else ("mapping" if mapping_mode else "graph")
        ),
        "window_generations": window,
        "points": points,
        "transitions": transitions,
        "summary": {
            "latest_generation": int(rows[-1].get("generation", len(rows) - 1)),
            "completed_generations": len(rows),
            "evaluated": total_evaluated,
            "geometry_ready": total_geometry,
            "training_output_bytes": int(
                rows[-1].get("training_output_bytes", 0) or 0
            ),
            "max_training_bytes": rows[-1].get("max_training_bytes"),
            "training_loss": latest_model.get("training_loss"),
        },
    }


HTML = r"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Graph Lab — transitions</title>
<style>
:root{color-scheme:light dark;--bg:#f4f1ea;--panel:#fff;--ink:#20231f;--muted:#6d716b;
--grid:#d8d5cc;--green:#147d64;--orange:#d07032;--blue:#5368b1;--red:#b94a48}
@media(prefers-color-scheme:dark){:root{--bg:#171a18;--panel:#222623;--ink:#eff2ed;
--muted:#aeb5ad;--grid:#424841;--green:#52c8a5;--orange:#f49a62;--blue:#aeb2ff;--red:#ff8582}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.42 system-ui,sans-serif}
main{max-width:1300px;margin:auto;padding:22px}header{display:flex;gap:14px;justify-content:space-between;
align-items:center;flex-wrap:wrap}h1{font-size:24px;margin:0}.controls{display:flex;gap:12px;align-items:center;flex-wrap:wrap}
button,select{border:1px solid var(--grid);border-radius:7px;padding:8px 12px;background:var(--panel);color:var(--ink)}
button{cursor:pointer;font-weight:650;background:var(--green);color:white}.status{color:var(--muted);margin:5px 0 16px;overflow-wrap:anywhere}
.cards{display:grid;grid-template-columns:repeat(5,minmax(130px,1fr));gap:10px}.card,.panel{background:var(--panel);
border:1px solid var(--grid);border-radius:10px}.card{padding:11px 14px}.card span{display:block;color:var(--muted);font-size:12px}
.card strong{display:block;font-size:20px;margin-top:2px}.panel{padding:14px;margin-top:12px;overflow-x:auto}h2{font-size:16px;margin:0 0 3px}
.subtitle{color:var(--muted);font-size:13px;margin-bottom:9px}svg{display:block;width:100%;height:340px;min-width:640px}
.legend{display:flex;gap:20px;flex-wrap:wrap;margin-left:68px;font-size:13px}.key:before{content:"";display:inline-block;width:21px;
height:3px;margin:0 6px 3px 0;background:var(--c)}table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:8px 9px;
border-bottom:1px solid var(--grid);text-align:right;vertical-align:top;white-space:nowrap}th:first-child,td:first-child,th:last-child,td:last-child{text-align:left}
th{color:var(--muted);font-weight:650}.note{white-space:normal;min-width:190px}.help p{margin:6px 0}.good{color:var(--green)}.bad{color:var(--red)}
@media(max-width:760px){main{padding:12px}.cards{grid-template-columns:1fr 1fr}}
</style></head><body><main>
<header><h1>Graph Lab — passage entre les filtres</h1><div class="controls">
<label>Transition <select id="transition"></select></label>
<label><input id="auto" type="checkbox" checked> auto (5 s)</label><button id="refresh">Rafraîchir</button></div></header>
<div id="status" class="status">Chargement…</div>
<section class="cards">
 <div class="card"><span>Dernière génération</span><strong id="generation">—</strong></div>
 <div class="card"><span>Candidats évalués</span><strong id="evaluated">—</strong></div>
 <div class="card"><span>Geometry ready</span><strong id="geometry">—</strong></div>
 <div class="card"><span>Disque d'entraînement</span><strong id="disk">—</strong></div>
 <div class="card"><span>Loss récente</span><strong id="loss">—</strong></div>
</section>
<section class="panel"><h2>Probabilité conditionnelle de franchir la transition choisie</h2>
 <div class="subtitle">Fenêtre glissante de <span id="window">—</span> générations. Plus haut est mieux ; la ligne 90 % matérialise l'objectif ambitieux.</div>
 <svg id="chart" role="img" aria-label="Taux conditionnel par génération"></svg>
 <div class="legend"><span class="key" style="--c:var(--blue)">Témoin initial</span>
 <span class="key" style="--c:var(--orange)">Témoin aléatoire récent</span>
 <span class="key" style="--c:var(--green)">Choix du modèle</span></div>
</section>
<section class="panel"><h2>Toutes les transitions</h2>
 <div class="subtitle">Chaque cellule donne passés / éligibles, puis le taux. « Éligible » signifie que le candidat a atteint l'étape précédente.</div>
 <table><thead><tr><th>Transition</th><th>Initial aléatoire</th><th>Aléatoire récent</th><th>Modèle récent</th>
 <th>Gain vs témoin récent</th><th>Prévu par modèle</th><th>AUC validation</th><th>Lecture rapide</th></tr></thead><tbody id="rows"></tbody></table>
</section>
<section class="panel help"><h2>Comment lire ces nombres</h2>
 <p><strong>Vert au-dessus de l'orange :</strong> le ranking appris enrichit réellement le pool actuel. Orange en baisse par rapport au bleu : le pool restant est devenu plus difficile, ce qui peut venir de la mémoire anti-doublons ou de l'évolution des mutations.</p>
 <p><strong>Zéro positif avec beaucoup d'éligibles :</strong> aucun signal supervisé n'existe encore pour ce palier. Peu d'éligibles : le goulet se situe avant. Une AUC élevée dit que la tête sait classer ; elle ne garantit pas que la sélection produit un taux élevé.</p>
 <p>Avec <code>training_metrics.jsonl</code>, les courbes décrivent le ranker de graphes. Avec <code>mapping_training_metrics.jsonl</code>, elles décrivent le ranker de mappings complets. Avec <code>weak_order_training_metrics.jsonl</code>, elles comparent les trajectoires dont chaque bloc d'ordre faible est tiré par le ranker aux trajectoires uniformes. Dans les trois cas, l'orange est le témoin stochastique du même niveau.</p>
</section></main>
<script>
const ns='http://www.w3.org/2000/svg';let data=null,timer=null;
function E(tag,a={}){const e=document.createElementNS(ns,tag);for(const[k,v]of Object.entries(a))e.setAttribute(k,v);return e}
function pct(v){return v==null?'—':`${(100*v).toFixed(v<.01?2:1)} %`}
function cell(s){return s&&s.eligible?`${s.passed} / ${s.eligible} · ${pct(s.rate)}`:'—'}
function bytes(v){if(v==null)return'—';const units=['B','KiB','MiB','GiB'];let i=0;while(v>=1024&&i<3){v/=1024;i++}return`${v.toFixed(i<2?0:2)} ${units[i]}`}
function renderTable(){const body=document.getElementById('rows');body.replaceChildren();for(const t of data.transitions){const tr=document.createElement('tr');
 const values=[`${t.from} → ${t.to}`,cell(t.baseline),cell(t.recent_random),cell(t.recent_learned),
 t.learned_vs_random_pp==null?'—':`${t.learned_vs_random_pp>=0?'+':''}${t.learned_vs_random_pp.toFixed(1)} pp`,
 pct(t.recent_learned.predicted_rate),t.model_auc==null?'—':t.model_auc.toFixed(3),t.diagnosis];
 values.forEach((v,i)=>{const td=document.createElement('td');td.textContent=v;if(i===7)td.className='note';tr.append(td)});body.append(tr)}}
function renderChart(){const svg=document.getElementById('chart');svg.replaceChildren();if(!data||!data.points.length)return;
 const idx=Number(document.getElementById('transition').value||0),W=1100,H=340,L=64,R=18,T=18,B=42,pw=W-L-R,ph=H-T-B;
 svg.setAttribute('viewBox',`0 0 ${W} ${H}`);const pts=data.points,x0=pts[0].generation,x1=pts.at(-1).generation;
 const X=x=>L+(x-x0)/Math.max(1,x1-x0)*pw,Y=y=>T+(1-y)*ph;
 for(let i=0;i<=5;i++){const rate=i/5,y=Y(rate);svg.append(E('line',{x1:L,x2:W-R,y1:y,y2:y,stroke:'var(--grid)'}));
  const tx=E('text',{x:L-9,y:y+4,'text-anchor':'end',fill:'var(--muted)','font-size':12});tx.textContent=`${i*20} %`;svg.append(tx)}
 const target=E('line',{x1:L,x2:W-R,y1:Y(.9),y2:Y(.9),stroke:'var(--red)','stroke-width':1.5,'stroke-dasharray':'5 5'});svg.append(target);
 for(let i=0;i<=4;i++){const x=x0+(x1-x0)*i/4,tx=E('text',{x:X(x),y:H-12,'text-anchor':'middle',fill:'var(--muted)','font-size':12});tx.textContent=Math.round(x);svg.append(tx)}
 const series=[['random','var(--orange)','7 5'],['learned','var(--green)','none']];for(const[key,color,dash]of series){let d='',open=false;
  for(const p of pts){const value=p[key][idx];if(value==null){open=false;continue}d+=`${open?'L':'M'}${X(p.generation).toFixed(1)},${Y(value).toFixed(1)} `;open=true}
  if(d)svg.append(E('path',{d,fill:'none',stroke:color,'stroke-width':key==='learned'?3:2,'stroke-dasharray':dash,'stroke-linejoin':'round'}))}
 const base=data.transitions[idx]?.baseline?.rate;if(base!=null)svg.append(E('line',{x1:L,x2:W-R,y1:Y(base),y2:Y(base),stroke:'var(--blue)','stroke-width':2,'stroke-dasharray':'3 5'}));}
function setupTransitions(){const select=document.getElementById('transition'),old=select.value;select.replaceChildren();data.transitions.forEach(t=>{const o=document.createElement('option');o.value=t.index;o.textContent=`${t.from} → ${t.to}`;select.append(o)});if(old&&Number(old)<data.transitions.length)select.value=old;select.onchange=renderChart}
async function refresh(){try{const r=await fetch('/api/data',{cache:'no-store'});if(!r.ok)throw new Error(await r.text());data=await r.json();
 document.getElementById('status').textContent=`${data.source} — actualisé à ${new Date().toLocaleTimeString()}`;document.getElementById('window').textContent=data.window_generations;
 const s=data.summary||{};document.getElementById('generation').textContent=s.latest_generation??'—';document.getElementById('evaluated').textContent=s.evaluated??'—';
 document.getElementById('geometry').textContent=s.geometry_ready??'—';document.getElementById('disk').textContent=s.max_training_bytes?`${bytes(s.training_output_bytes)} / ${bytes(s.max_training_bytes)}`:bytes(s.training_output_bytes);
 document.getElementById('loss').textContent=s.training_loss==null?'—':Number(s.training_loss).toFixed(4);setupTransitions();renderTable();renderChart();
 }catch(e){document.getElementById('status').textContent=`Erreur : ${e.message}`}}
document.getElementById('refresh').onclick=refresh;document.getElementById('auto').onchange=e=>{clearInterval(timer);if(e.target.checked)timer=setInterval(refresh,5000)};
refresh();timer=setInterval(refresh,5000);
</script></body></html>"""


def make_handler(
    source: Path, window_generations: int, max_points: int
) -> type[BaseHTTPRequestHandler]:
    class DashboardHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - standard-library callback name
            route = urlparse(self.path).path
            if route == "/":
                self._send(200, "text/html; charset=utf-8", HTML.encode("utf-8"))
            elif route == "/api/data":
                payload = json.dumps(
                    build_dashboard_data(
                        source,
                        window_generations=window_generations,
                        max_points=max_points,
                    )
                ).encode("utf-8")
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
    parser = argparse.ArgumentParser(description="Live Graph Lab transition dashboard")
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("output/graph_lab/up-to-13/mapping_training_metrics.jsonl"),
        help="graph or mapping compact metrics JSONL to follow",
    )
    parser.add_argument("--window-generations", type=int, default=50)
    parser.add_argument("--max-points", type=int, default=400)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--no-browser", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    source = args.input.resolve()
    server = ThreadingHTTPServer(
        (args.host, args.port),
        make_handler(source, args.window_generations, args.max_points),
    )
    url = f"http://{args.host}:{args.port}/"
    print(f"Graph Lab dashboard: {url}")
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
