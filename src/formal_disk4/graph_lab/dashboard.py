from __future__ import annotations

import argparse
import json
import math
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import parse_qs, urlparse

from formal_disk4.geometry.status import read_geometry_status_records

from .dashboard_page import UNIFIED_DASHBOARD_HTML
from .evaluator import GRAPH_STAGES
from .geometry_catalog import GeometryCandidateCatalog
from .rollout_audit import build_audit_report
from .solution_gallery import (
    CompositeGeometrySolutionIndex,
    GeometrySolutionIndex,
)
from .structure_gallery import RecentStructureGallery


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
        "passed": 0.0,
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
    *,
    modes_key: str = "selection_modes",
) -> list[dict[str, float | int | None]]:
    totals = [_blank_transition() for _stage in transition_ids]
    for row in rows:
        modes = row.get(modes_key, {})
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
            for key in ("eligible", "prediction_count"):
                target[key] = int(target[key] or 0) + int(source.get(key, 0) or 0)
            target["passed"] = float(target["passed"] or 0.0) + float(
                source.get("passed", 0.0) or 0.0
            )
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


def _aggregate_outcome(
    rows: Sequence[Mapping[str, Any]],
    mode: str,
    *,
    modes_key: str,
    mapping_mode: bool,
) -> dict[str, float | int | None]:
    selected = 0
    successful = 0
    for row in rows:
        raw_modes = row.get(modes_key, {})
        if not isinstance(raw_modes, Mapping):
            continue
        raw_mode = raw_modes.get(mode, {})
        if not isinstance(raw_mode, Mapping):
            continue
        count = int(raw_mode.get("count", 0) or 0)
        selected += count
        if mapping_mode:
            successful += int(raw_mode.get("profile_emitting_count", 0) or 0)
        else:
            reached = raw_mode.get("stage_reached_counts", {})
            if isinstance(reached, Mapping):
                successful += int(reached.get("geometry_ready", 0) or 0)
    return {
        "selected": selected,
        "successful": successful,
        "rate": successful / selected if selected else None,
    }


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
    require_comparable: bool = False,
) -> dict[str, Any]:
    rows = _load_json_lines(path)
    window = max(1, int(window_generations))
    if not rows:
        source_name = path.name
        empty_kind = (
            "specialization"
            if source_name == "specialization_training_metrics.jsonl"
            else (
                "weak_order"
                if source_name == "weak_order_training_metrics.jsonl"
                else (
                    "mapping"
                    if source_name == "mapping_training_metrics.jsonl"
                    else "graph"
                )
            )
        )
        return {
            "source": str(path.resolve()),
            "stages": list(GRAPH_STAGES),
            "kind": empty_kind,
            "window_generations": window,
            "points": [],
            "transitions": [],
            "summary": {},
        }

    mapping_mode = isinstance(rows[-1].get("filter_order"), Sequence)
    weak_order_mode = str(rows[-1].get("schema_version", "")).startswith(
        "graph-lab-weak-order-"
    )
    specialization_mode = str(rows[-1].get("schema_version", "")).startswith(
        "graph-lab-specialization-"
    )
    transition_ids = (
        tuple(str(value) for value in rows[-1].get("filter_order", ()))
        if mapping_mode
        else GRAPH_STAGES[1:]
    )
    root_label = (
        "specialization.pool"
        if specialization_mode
        else ("weak_order.rollout" if weak_order_mode else "mapping.rollout")
    )
    stage_labels = (
        (root_label, *transition_ids) if mapping_mode else GRAPH_STAGES
    )
    # Mapping/weak filters are instrumentation points, not one homogeneous
    # Markov chain. Their dashboard therefore displays the directly measured
    # P(filter entered), rather than multiplying unrelated conditional rates.
    collection_key = "reach" if mapping_mode else "transitions"
    comparable_rows = [
        row for row in rows if "comparable_selection_modes" in row
    ]
    statistics_rows = comparable_rows if require_comparable else rows
    modes_key = (
        "comparable_selection_modes" if require_comparable else "selection_modes"
    )
    baseline_rows = statistics_rows[:window]
    recent_rows = statistics_rows[-window:]
    baseline = _aggregate(
        baseline_rows,
        "exploration",
        transition_ids,
        collection_key,
        modes_key=modes_key,
    )
    recent_random = _aggregate(
        recent_rows,
        "exploration",
        transition_ids,
        collection_key,
        modes_key=modes_key,
    )
    recent_learned = _aggregate(
        recent_rows,
        "learned",
        transition_ids,
        collection_key,
        modes_key=modes_key,
    )
    if mapping_mode:
        recent_random_conditional = _aggregate(
            recent_rows,
            "exploration",
            transition_ids,
            "filters",
            modes_key=modes_key,
        )
        recent_learned_conditional = _aggregate(
            recent_rows,
            "learned",
            transition_ids,
            "filters",
            modes_key=modes_key,
        )
    else:
        recent_random_conditional = recent_random
        recent_learned_conditional = recent_learned
    recent_outcomes = {
        mode: _aggregate_outcome(
            recent_rows,
            mode,
            modes_key=modes_key,
            mapping_mode=mapping_mode,
        )
        for mode in ("exploration", "learned")
    }

    latest_model = rows[-1].get("model", {})
    if not isinstance(latest_model, Mapping):
        latest_model = {}
    model_transitions = latest_model.get(collection_key, {})
    if not isinstance(model_transitions, Mapping):
        model_transitions = {}
    model_values = latest_model.get("values", {})
    if not isinstance(model_values, Mapping):
        model_values = {}
    model_pairwise = latest_model.get("pairwise_ranking", {})
    if not isinstance(model_pairwise, Mapping):
        model_pairwise = {}
    conditional_models = latest_model.get("filters", {}) if mapping_mode else {}
    if not isinstance(conditional_models, Mapping):
        conditional_models = {}
    value_labels = {
        "profile_emitted": "Formal profile emitted",
        "geometry_solution": "Geometry solution found",
        "nontrivial_geometry_solution": "Non-ring geometry solution found",
    }
    if specialization_mode:
        value_labels = {
            "profile_valid": "Formal specialization accepted",
            **value_labels,
        }
    objectives = []
    for value_id, label in value_labels.items():
        value = model_values.get(value_id, {})
        pair = model_pairwise.get(value_id, {})
        if not isinstance(value, Mapping):
            value = {}
        if not isinstance(pair, Mapping):
            pair = {}
        objectives.append(
            {
                "id": value_id,
                "label": label,
                "eligible": int(value.get("eligible", 0) or 0),
                "actual_rate": value.get("mean_rate"),
                "mean_prediction": value.get("mean_prediction"),
                "auc": value.get("binary_auc", value.get("auc")),
                "active": bool(value.get("active", False)),
                "pair_accuracy": pair.get("accuracy"),
                "pair_count": int(pair.get("pairs", 0) or 0),
                "pair_scope": pair.get("scope"),
            }
        )

    transitions = []
    for index, stage in enumerate(transition_ids):
        model = model_transitions.get(stage, {})
        if not isinstance(model, Mapping):
            model = {}
        conditional_model = conditional_models.get(stage, {})
        if not isinstance(conditional_model, Mapping):
            conditional_model = {}
        diagnosis = _diagnosis(
            baseline[index], recent_random[index], recent_learned[index]
        )
        if bool(model.get("auc_regression", False)):
            diagnosis += "; model validation AUC regressed > 0.05 from its best"
        transitions.append(
            {
                "index": index,
                "from": root_label if mapping_mode else stage_labels[index],
                "to": stage,
                "baseline": baseline[index],
                "recent_random": recent_random[index],
                "recent_learned": recent_learned[index],
                "recent_random_conditional": recent_random_conditional[index],
                "recent_learned_conditional": recent_learned_conditional[index],
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
                "model_brier": model.get("brier_score"),
                "conditional_model_auc": conditional_model.get("binary_auc"),
                "conditional_model_brier": conditional_model.get("brier_score"),
                "conditional_model_active": bool(
                    conditional_model.get("active", False)
                ),
                "model_auc_regression": bool(model.get("auc_regression", False)),
                "diagnosis": diagnosis,
            }
        )

    stride = max(1, math.ceil(len(statistics_rows) / max(1, int(max_points))))
    endpoints = list(range(stride - 1, len(statistics_rows), stride))
    if statistics_rows and (not endpoints or endpoints[-1] != len(statistics_rows) - 1):
        endpoints.append(len(statistics_rows) - 1)
    points = []
    for end in endpoints:
        rolling_rows = statistics_rows[max(0, end - window + 1) : end + 1]
        random_stats = _aggregate(
            rolling_rows,
            "exploration",
            transition_ids,
            collection_key,
            modes_key=modes_key,
        )
        learned_stats = _aggregate(
            rolling_rows,
            "learned",
            transition_ids,
            collection_key,
            modes_key=modes_key,
        )
        points.append(
            {
                "generation": int(statistics_rows[end].get("generation", end)),
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
            "specialization"
            if specialization_mode
            else (
                "weak_order"
                if weak_order_mode
                else ("mapping" if mapping_mode else "graph")
            )
        ),
        "window_generations": window,
        "points": points,
        "transitions": transitions,
        "objectives": objectives,
        "probability_semantics": (
            "direct_filter_reach" if mapping_mode else "sequential_transition"
        ),
        "comparison": {
            "required": require_comparable,
            "comparable_generations": len(comparable_rows),
            "statistics_generations": len(statistics_rows),
            "scope": (
                str(comparable_rows[-1].get("comparison", {}).get("scope", ""))
                if comparable_rows
                and isinstance(comparable_rows[-1].get("comparison"), Mapping)
                else None
            ),
        },
        "recent_outcomes": recent_outcomes,
        "summary": {
            "latest_generation": int(rows[-1].get("generation", len(rows) - 1)),
            "completed_generations": len(rows),
            "comparable_generations": len(comparable_rows),
            "evaluated": total_evaluated,
            "geometry_ready": total_geometry,
            "training_output_bytes": int(
                rows[-1].get("training_output_bytes", 0) or 0
            ),
            "max_training_bytes": rows[-1].get("max_training_bytes"),
            "training_loss": latest_model.get("training_loss"),
            "policy_mode": latest_model.get("mode", "learned"),
            "curriculum": latest_model.get("curriculum", {}),
            "pool_coverage": rows[-1].get("pool_coverage", {}),
            "validation_auc_regressions": sum(
                bool(item.get("model_auc_regression", False))
                for item in transitions
            ),
        },
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def build_unified_dashboard_data(
    output: Path,
    catalog: GeometryCandidateCatalog,
    structures: RecentStructureGallery | None = None,
    *,
    window_generations: int = 50,
    max_points: int = 400,
    page: int = 1,
    page_size: int = 100,
    include_importance: set[str] | None = None,
    include_statuses: set[str] | None = None,
    structure_limit: int = 100,
) -> dict[str, Any]:
    output = output.resolve()
    geometry_output = output / "geometry"
    level_specs = (
        (
            "Graphes",
            "Le premier ranker choisit les structures complètes proposées par le prior.",
            output / "training_metrics.jsonl",
            False,
        ),
        (
            "Mappings",
            "Le deuxième ranker choisit orientation et décalage cyclique sur un graphe fixé.",
            output / "mapping_training_metrics.jsonl",
            True,
        ),
        (
            "Ordres faibles",
            "Le troisième ranker choisit successivement les blocs de chaque rollout.",
            output / "weak_order_training_metrics.jsonl",
            True,
        ),
        (
            "Familles et spécialisations",
            "Le quatrième ranker classe ensemble les familles finies et leurs spécialisations pour un même cas de mots.",
            output / "specialization_training_metrics.jsonl",
            True,
        ),
    )
    levels = []
    for title, description, source, require_comparable in level_specs:
        level = build_dashboard_data(
            source,
            window_generations=window_generations,
            max_points=max_points,
            require_comparable=require_comparable,
        )
        level["title"] = title
        level["description"] = description
        levels.append(level)

    coverage_rows = _load_json_lines(output / "rollout_coverage_metrics.jsonl")
    coverage = (
        build_audit_report(
            coverage_rows, window_generations=max(1, window_generations)
        )
        if coverage_rows
        else {}
    )
    statuses = read_geometry_status_records(
        geometry_output / "geometry_status.sqlite3"
    )
    recovery_output = output / "geometry-recovery"
    recovery_statuses = read_geometry_status_records(
        recovery_output / "geometry_status.sqlite3"
    )
    # Recovery only targets inconclusive failures. Its later result is more
    # informative, while a solution from either worker is always authoritative.
    for profile_id, recovery_status in recovery_statuses.items():
        primary_status = statuses.get(profile_id)
        if (
            primary_status is None
            or recovery_status.status == "solution_found"
            or primary_status.status != "solution_found"
        ):
            statuses[profile_id] = recovery_status
    worker = _read_json(geometry_output / "geometry_worker_state.json")
    recovery_worker = _read_json(
        recovery_output / "geometry_recovery_state.json"
    )
    processing = recovery_worker.get("current_profile_id") or worker.get(
        "current_profile_id"
    )
    gallery = catalog.page(
        page=page,
        page_size=page_size,
        statuses=statuses,
        processing_profile_id=(str(processing) if processing else None),
        include_importance=include_importance,
        include_statuses=include_statuses,
    )
    return {
        "schema_version": "graph-lab-unified-dashboard-v1",
        "output": str(output),
        "levels": levels,
        "coverage": coverage,
        "worker": worker,
        "recovery_worker": recovery_worker,
        "gallery": gallery,
        "recent_structures": (
            structures.recent(structure_limit)
            if structures is not None
            else {"requested": structure_limit, "available": 0, "items": []}
        ),
        "state": _read_json(output / "state.json"),
        "report": _read_json(output / "report.json"),
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
    output: Path,
    catalog: GeometryCandidateCatalog,
    solutions: GeometrySolutionIndex | CompositeGeometrySolutionIndex,
    structures: RecentStructureGallery,
    window_generations: int,
    max_points: int,
) -> type[BaseHTTPRequestHandler]:
    class DashboardHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - standard-library callback name
            parsed = urlparse(self.path)
            route = parsed.path
            if route == "/":
                self._send(
                    200,
                    "text/html; charset=utf-8",
                    UNIFIED_DASHBOARD_HTML.encode("utf-8"),
                )
            elif route == "/api/data":
                query = parse_qs(parsed.query, keep_blank_values=True)
                try:
                    page = int(query.get("page", ["1"])[0])
                    page_size = int(query.get("page_size", ["100"])[0])
                    structure_limit = int(
                        query.get("structure_limit", ["100"])[0]
                    )
                except ValueError:
                    page, page_size, structure_limit = 1, 100, 100
                importance_parameter = query.get("importance")
                importance = {
                    value
                    for value in (importance_parameter or [""])[0].split(",")
                    if value in {"pizza", "important", "alert"}
                }
                status_parameter = query.get("statuses")
                statuses = {
                    value
                    for value in (status_parameter or [""])[0].split(",")
                    if value
                    in {
                        "pending",
                        "processing",
                        "solution_found",
                        "rejected_certain",
                        "no_solution_found",
                    }
                }
                payload = json.dumps(
                    build_unified_dashboard_data(
                        output,
                        catalog,
                        structures,
                        window_generations=window_generations,
                        max_points=max_points,
                        page=page,
                        page_size=page_size,
                        include_importance=(
                            importance if importance_parameter is not None else None
                        ),
                        include_statuses=(
                            statuses if status_parameter is not None else None
                        ),
                        structure_limit=structure_limit,
                    ),
                    ensure_ascii=False,
                ).encode("utf-8")
                self._send(200, "application/json; charset=utf-8", payload)
            elif route == "/api/solution-svg":
                query = parse_qs(parsed.query)
                profile_id = str(query.get("profile", [""])[0])
                try:
                    svg = solutions.svg(profile_id) if profile_id else None
                except Exception as error:
                    self._send(
                        422,
                        "text/plain; charset=utf-8",
                        f"Assembly rendering failed: {error}\n".encode("utf-8"),
                    )
                    return
                if svg is None:
                    self._send(404, "text/plain; charset=utf-8", b"Not found\n")
                else:
                    self._send(200, "image/svg+xml; charset=utf-8", svg.encode("utf-8"))
            elif route == "/api/structure-svg":
                query = parse_qs(parsed.query)
                visit_id = str(query.get("visit", [""])[0])
                try:
                    svg = structures.svg(visit_id) if visit_id else None
                except Exception as error:
                    self._send(
                        422,
                        "text/plain; charset=utf-8",
                        f"Structure rendering failed: {error}\n".encode("utf-8"),
                    )
                    return
                if svg is None:
                    self._send(404, "text/plain; charset=utf-8", b"Not found\n")
                else:
                    self._send(
                        200,
                        "image/svg+xml; charset=utf-8",
                        svg.encode("utf-8"),
                    )
            elif route == "/favicon.ico":
                self._send(204, "image/x-icon", b"")
            else:
                self._send(404, "text/plain; charset=utf-8", b"Not found\n")

        def _send(self, status: int, content_type: str, body: bytes) -> None:
            try:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                # A dashboard refresh may supersede its previous fetch, and a
                # browser tab may close while a large JSON response is still
                # being written. This disconnect belongs to that one HTTP
                # client; it must neither print a server traceback nor affect
                # the learning and geometry worker threads.
                return

        def log_message(self, format: str, *args: object) -> None:
            return

    return DashboardHandler


class GraphLabDashboardServer:
    def __init__(
        self,
        output: Path,
        *,
        host: str = "127.0.0.1",
        port: int = 8766,
        window_generations: int = 50,
        max_points: int = 400,
        catalog_path: Path | None = None,
    ) -> None:
        self.output = output.resolve()
        self.geometry_output = self.output / "geometry"
        self.geometry_output.mkdir(parents=True, exist_ok=True)
        self.catalog = GeometryCandidateCatalog(
            (
                self.geometry_output / "geometry_candidate_catalog.sqlite3"
                if catalog_path is None
                else catalog_path.resolve()
            ),
            self.output / "geometry_candidates.jsonl",
        )
        self.solutions = CompositeGeometrySolutionIndex(
            (
                self.geometry_output / "geometric_solutions.jsonl",
                self.output
                / "geometry-recovery"
                / "geometric_solutions.jsonl",
            )
        )
        self.structures = RecentStructureGallery(
            self.output / "observations.jsonl"
        )
        self.server = ThreadingHTTPServer(
            (host, int(port)),
            make_handler(
                self.output,
                self.catalog,
                self.solutions,
                self.structures,
                window_generations,
                max_points,
            ),
        )
        bound_host, bound_port = self.server.server_address[:2]
        self.url = f"http://{bound_host}:{bound_port}/"
        self.stop_event = threading.Event()
        self.server_thread: threading.Thread | None = None
        self.catalog_thread: threading.Thread | None = None

    def _index_catalog(self) -> None:
        while not self.stop_event.is_set():
            try:
                before = self.catalog.progress()["source_offset"]
                after = self.catalog.ingest(maximum_lines=1000)["source_offset"]
                delay = 0.05 if after > before else 1.0
            except Exception:
                delay = 2.0
            self.stop_event.wait(delay)

    def start(self, *, open_browser: bool = True) -> None:
        self.catalog_thread = threading.Thread(
            target=self._index_catalog,
            name="graph-lab-candidate-index",
            daemon=True,
        )
        self.catalog_thread.start()
        self.server_thread = threading.Thread(
            target=self.server.serve_forever,
            name="graph-lab-dashboard",
            daemon=True,
        )
        self.server_thread.start()
        if open_browser:
            threading.Timer(0.25, webbrowser.open, args=(self.url,)).start()

    def serve_forever(self, *, open_browser: bool = True) -> None:
        self.catalog_thread = threading.Thread(
            target=self._index_catalog,
            name="graph-lab-candidate-index",
            daemon=True,
        )
        self.catalog_thread.start()
        if open_browser:
            threading.Timer(0.25, webbrowser.open, args=(self.url,)).start()
        self.server.serve_forever()

    def close(self) -> None:
        self.stop_event.set()
        if self.server_thread is not None and self.server_thread.is_alive():
            self.server.shutdown()
        self.server.server_close()
        if self.server_thread is not None:
            self.server_thread.join(timeout=2.0)
        if self.catalog_thread is not None:
            self.catalog_thread.join(timeout=2.0)
        self.catalog.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Unified live Graph Lab dashboard")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output/graph_lab/up-to-13"),
        help="Graph Lab output directory",
    )
    parser.add_argument("--window-generations", type=int, default=50)
    parser.add_argument("--max-points", type=int, default=400)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument(
        "--catalog-path",
        type=Path,
        help=(
            "optional independent candidate index; useful when another live "
            "dashboard already owns the default catalog"
        ),
    )
    parser.add_argument("--no-browser", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    dashboard = GraphLabDashboardServer(
        args.output,
        host=args.host,
        port=args.port,
        window_generations=args.window_generations,
        max_points=args.max_points,
        catalog_path=args.catalog_path,
    )
    print(f"Graph Lab dashboard: {dashboard.url}")
    print(f"Reading: {args.output.resolve()}")
    print("Press Ctrl+C to stop.")
    try:
        dashboard.serve_forever(open_browser=not args.no_browser)
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
    finally:
        dashboard.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
