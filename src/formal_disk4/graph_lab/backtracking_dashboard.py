from __future__ import annotations

"""Small live dashboard for deterministic fixed-graph backtracking campaigns."""

import json
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


_PAGE = r"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Formal Disk 4 · Backtracking Lab</title>
<style>
:root{color-scheme:dark;--bg:#11161d;--panel:#1a222d;--line:#334154;--fg:#edf3f8;--muted:#aab8c6;--good:#64d59a;--warn:#f3c96b;--bad:#f27f79}
*{box-sizing:border-box}[hidden]{display:none!important}body{margin:0;background:var(--bg);color:var(--fg);font:14px system-ui,sans-serif}main{max-width:1320px;margin:auto;padding:20px}h1,h2{margin:.2em 0 .6em}.top,.grid{display:grid;gap:14px}.top{grid-template-columns:repeat(6,minmax(130px,1fr))}.grid{grid-template-columns:minmax(320px,1fr) minmax(430px,1.5fr);margin-top:14px}.card,.stat{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px}.stat b{display:block;font-size:22px;margin-top:5px}.muted{color:var(--muted)}img{display:block;width:100%;max-height:520px;object-fit:contain;background:white;border-radius:7px}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:7px;border-bottom:1px solid var(--line)}code{font-size:12px}.good{color:var(--good)}.warn{color:var(--warn)}.bad{color:var(--bad)}@media(max-width:900px){.top{grid-template-columns:repeat(2,1fr)}.grid{grid-template-columns:1fr}}
</style></head><body><main>
<h1>Backtracking Lab</h1><div id="headline" class="muted">Chargement…</div>
<section class="top" id="stats"></section>
<section class="card" style="margin-top:14px"><h2>Branche de recherche courante</h2><div class="muted">Les choix ci-dessous sont locaux : leur fraction n'est pas un pourcentage global de l'arbre.</div><pre id="branch"></pre></section>
<section class="grid"><article class="card"><h2>Graphe courant</h2><div id="graph-meta" class="muted"></div><img id="graph" alt="Graphe courant"></article>
<article class="card"><h2>Résultat géométrique</h2><div id="geometry" class="muted">Aucune solution pour le moment.</div><img id="solution" hidden alt="Solution géométrique"></article></section>
<section class="card" style="margin-top:14px"><h2>Principaux rejets et issues formelles</h2><div class="muted">Compteurs cumulés du graphe courant, y compris les sous-arbres coupés avant une feuille. Une lacune ou un cas différé n'est jamais un certificat négatif.</div><table><thead><tr><th>Cause</th><th>Nombre</th></tr></thead><tbody id="outcomes"></tbody></table></section>
<section class="card" style="margin-top:14px"><h2>Graphes terminés</h2><table><thead><tr><th>#</th><th>tuiles</th><th>statut</th><th>début</th><th>fin</th><th>durée</th><th>feuilles</th><th>profils</th><th>solution</th></tr></thead><tbody id="rows"></tbody></table></section>
</main><script>
const fmt=n=>Number(n||0).toLocaleString('fr-FR'), sec=n=>`${Number(n||0).toFixed(1)} s`;
function stat(label,value){const d=document.createElement('div');d.className='stat';d.innerHTML=`<span class="muted">${label}</span><b>${value}</b>`;return d}
async function refresh(){try{const p=await(await fetch('/api/status',{cache:'no-store'})).json(),s=p.status||{},r=p.results?.graphs||{},c=s.counters||{};
document.querySelector('#headline').textContent=`${s.state||'initialisation'} · ${s.phase||''} · mise à jour ${s.updated_utc||'—'}`;
const sp=s.search_progress||{};document.querySelector('#branch').textContent=sp.engine?`${sp.engine} · incidences ${sp.assigned_occurrences}/${sp.total_occurrences}\nLP : ${fmt(sp.linear_calls)} appels, ${fmt(sp.linear_rejections)} rejets · ${sec(sp.linear_seconds)}\nSecteurs conservés : ${fmt(sp.word_sector_cases)} cas, ${fmt(sp.word_sector_rejections)} rejets LP, ${fmt(sp.word_sector_depth)} décisions actives\n`+(sp.branch_path||[]).map(x=>`${x.tile||x.occurrence||'Secteur de mots'}: choix ${x.choice}/${x.choices} · ${x.kind==='chart'?`orientation ${x.parity}, décalage ${x.cut}`:x.relation}`).join('\n'):'Ce moteur ne publie pas de branche détaillée.';
const liveElapsed=s.state==='running'&&s.started_unix?Date.now()/1000-Number(s.started_unix):Number(s.elapsed_seconds||0);
const stats=document.querySelector('#stats'),euclid=`${fmt(c.euclidean_placement_numerically_feasible)} / ${fmt(c.euclidean_placement_audits)}`,euclidPruned=`${fmt(c.euclidean_partial_pruned_subtrees)} / ${fmt(c.euclidean_partial_audits)}`;stats.replaceChildren(stat('Graphe',`${fmt(s.current_graph_index)} / ${fmt(s.graph_count)}`),stat('Temps courant',sec(liveElapsed)),stat('Nœuds',fmt(c.arrangement_nodes)),stat('Feuilles',fmt(c.joint_arrangement_kernel_calls)),stat('Feuilles/s',Number(s.leaves_per_second||0).toFixed(2)),stat('Profils formels',fmt(s.formal_profiles)),stat('Audit euclidien faisable',euclid),stat('Sous-arbres euclidiens coupés',euclidPruned));
if(sp.engine==='contact_types'){stats.replaceChildren(stat('Graphe',`${fmt(s.current_graph_index)} / ${fmt(s.graph_count)}`),stat('Temps courant',sec(liveElapsed)),stat('Nœuds de contact',fmt(c.contact_nodes)),stat('Arrangements complets',fmt(c.joint_arrangement_kernel_calls)),stat('Profils formels',fmt(s.formal_profiles)),stat('Rejets précoces de longueur',fmt(sp.linear_rejections)),stat('Rejets de coïncidence angulaire',fmt(c.contact_cut_angle_rejections)),stat('Temps des vérifications LP',sec(sp.linear_seconds)));}
if(sp.engine==='contact_types'){stats.append(stat('Rejets par rotation des contacts',fmt(c.contact_turn_rejections)),stat('Temps propagation des rotations',sec(sp.contact_turn_seconds)));}
if(sp.engine==='contact_types'){stats.append(stat('Rejets par propagation des mots',fmt(c.contact_word_rejections)),stat('Subdivisions forcées (Levi)',fmt(sp.word_propagation_splits)),stat('Égalités de points propagées',fmt(sp.word_propagation_point_relations)),stat('Temps propagation des mots',sec(sp.word_propagation_seconds)),stat('Cas Levi testés',fmt(sp.word_refinement_cases)),stat('Nœuds Levi fermés (tous les cas)',fmt(sp.word_refinement_closed)),stat('Anticipations Levi non conclues',fmt(sp.word_refinement_deferred)),stat('Résolutions de mots réutilisées',fmt(c.word_cache_hits)));}
if(sp.engine==='contact_types'){document.querySelector('#branch').textContent+=`\nPropagation partielle : ${fmt(sp.word_propagation_residuals)} états avec équations résiduelles, ${fmt(sp.word_propagation_limited)} passages limités. Ces limites ne rejettent pas la branche : le noyau formel reste appelé aux feuilles.`;}
document.querySelector('#graph-meta').textContent=s.current_graph?`n=${s.current_graph.tile_count} · ${s.current_graph.graph_id} · ${s.current_graph.edge_count||s.current_graph.edges?.length||0} arêtes`:'Aucun graphe actif';
const graph=document.querySelector('#graph');if(s.current_graph_svg){graph.src='/api/current-graph.svg?ts='+Date.now();graph.hidden=false}else graph.hidden=true;
const solution=document.querySelector('#solution'),geo=document.querySelector('#geometry');if(s.solution_graph_id){solution.src='/api/solution.svg?graph_id='+encodeURIComponent(s.solution_graph_id)+'&ts='+Date.now();solution.hidden=false;geo.textContent=`Solution trouvée pour ${s.solution_graph_id}`}else{solution.hidden=true;geo.textContent=`Tentatives géométriques : ${fmt(s.geometry_attempts)} · dernier statut : ${s.geometry_status||'—'}`}
const outcomes=document.querySelector('#outcomes');outcomes.replaceChildren();Object.entries(c).filter(([k,v])=>Number(v)>0&&(k.endsWith('_rejections')||k.startsWith('deferred_')||k.startsWith('unsupported_')||k.endsWith('_errors')||k==='profiles_emitted')).sort((a,b)=>Number(b[1])-Number(a[1])).slice(0,16).forEach(([k,v])=>{const tr=document.createElement('tr'),a=document.createElement('td'),b=document.createElement('td');a.textContent=k;b.textContent=fmt(v);tr.append(a,b);outcomes.append(tr)});
const body=document.querySelector('#rows');body.replaceChildren();Object.values(r).sort((a,b)=>(a.graph_index||0)-(b.graph_index||0)).forEach(x=>{const tr=document.createElement('tr');tr.innerHTML=`<td>${fmt(x.graph_index)}</td><td>${fmt(x.tile_count)}</td><td>${x.status||''}</td><td>${x.started_utc||''}</td><td>${x.completed_utc||''}</td><td>${sec(x.wall_elapsed_seconds)}</td><td>${fmt(x.kernel_calls)}</td><td>${fmt(x.formal_profile_count)}</td><td></td>`;if(x.solution_svg){const a=document.createElement('a');a.href='/api/solution.svg?graph_id='+encodeURIComponent(x.graph_id);a.target='_blank';a.textContent='voir';tr.lastElementChild.append(a)}body.append(tr)});
}catch(e){document.querySelector('#headline').textContent='Dashboard indisponible : '+e}finally{setTimeout(refresh,1500)}}refresh();
</script></body></html>"""


class BacktrackingDashboardServer:
    def __init__(
        self,
        output: Path,
        *,
        host: str = "127.0.0.1",
        port: int = 8770,
    ) -> None:
        self.output = output.resolve()
        self.host = str(host)
        self.port = int(port)
        self.httpd: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/"

    def _json(self, name: str) -> object:
        path = self.output / name
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _safe_file(self, raw: object) -> Path | None:
        if not isinstance(raw, str) or not raw:
            return None
        path = Path(raw).resolve()
        try:
            path.relative_to(self.output)
        except ValueError:
            return None
        return path if path.is_file() else None

    def _handler(self):
        dashboard = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, _format: str, *_args: object) -> None:
                return

            def _send(self, status: int, content_type: str, body: bytes) -> None:
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                    return

            def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
                parsed = urlparse(self.path)
                if parsed.path == "/":
                    self._send(HTTPStatus.OK, "text/html; charset=utf-8", _PAGE.encode())
                    return
                if parsed.path == "/api/status":
                    payload = {
                        "status": dashboard._json("status.json"),
                        "results": dashboard._json("results.json"),
                    }
                    self._send(
                        HTTPStatus.OK,
                        "application/json; charset=utf-8",
                        json.dumps(payload).encode(),
                    )
                    return
                if parsed.path == "/api/current-graph.svg":
                    status = dashboard._json("status.json")
                    path = dashboard._safe_file(
                        status.get("current_graph_svg")
                        if isinstance(status, dict)
                        else None
                    )
                elif parsed.path == "/api/solution.svg":
                    graph_id = parse_qs(parsed.query).get("graph_id", [""])[0]
                    results = dashboard._json("results.json")
                    graphs = results.get("graphs", {}) if isinstance(results, dict) else {}
                    row = graphs.get(graph_id, {}) if isinstance(graphs, dict) else {}
                    path = dashboard._safe_file(
                        row.get("solution_svg") if isinstance(row, dict) else None
                    )
                else:
                    path = None
                if path is None:
                    self._send(HTTPStatus.NOT_FOUND, "text/plain", b"not found")
                    return
                self._send(HTTPStatus.OK, "image/svg+xml", path.read_bytes())

        return Handler

    def start(self, *, open_browser: bool = True) -> None:
        self.httpd = ThreadingHTTPServer((self.host, self.port), self._handler())
        self.thread = threading.Thread(
            target=self.httpd.serve_forever,
            name="backtracking-lab-dashboard",
            daemon=True,
        )
        self.thread.start()
        if open_browser:
            webbrowser.open(self.url)

    def close(self) -> None:
        if self.httpd is not None:
            self.httpd.shutdown()
            self.httpd.server_close()
        if self.thread is not None:
            self.thread.join(timeout=5.0)
