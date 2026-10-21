"""Bounded diagnostic, NOT the unbounded interactive campaign.

Same fixed tetrad and contact engine, with/without word propagation. Word time guards
are explicit here so this diagnostic remains short; report deferred systems
as such. Counts describe different trees, not a speedup estimate.
"""
import argparse
from pathlib import Path
from time import perf_counter

from formal_disk4.graph_lab.backtracking_lab import _evaluation_config
from formal_disk4.graph_lab.evaluator import GraphFormalEvaluator
from formal_disk4.graph_lab.exhaustive_local import center_ring_candidates
from formal_disk4.pipeline.output import atomic_write_json, JsonlWriter


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=float, default=30)
    parser.add_argument('--output', default='output/contact-v2-benchmark.json')
    parser.add_argument('--variant', choices=('both', 'before', 'after'), default='both')
    parser.add_argument('--comparison', choices=('propagation', 'refinement', 'sectors'), default='propagation')
    args = parser.parse_args()
    root = Path.cwd()
    candidate = next(iter(center_ring_candidates(4, 4)))
    report = {}
    variants = ('contact-before-words', 'contact-with-words') if args.variant == 'both' else (
        'contact-before-words' if args.variant == 'before' else 'contact-with-words',)
    for engine in variants:
        config = _evaluation_config(root/'config/local_graph_campaign/formal.json', engine='contact-types')
        config['contact_word_propagation'] = args.comparison != 'propagation' or engine == 'contact-with-words'
        config['contact_word_refinement_depth'] = (
            2 if args.comparison != 'propagation' and engine == 'contact-with-words' else 0)
        config['contact_word_sectors'] = args.comparison == 'sectors' and engine == 'contact-with-words'
        config['mapping_search_overrides']['solver']['max_seconds_per_word_case'] = 1.0
        evaluator = GraphFormalEvaluator(root, config)
        started = perf_counter()
        latest = {}
        def progress(payload):
            latest.update(payload)
        profiles_path = (root/args.output).with_name(Path(args.output).stem + '-' + engine + '-profiles.jsonl')
        with JsonlWriter(profiles_path, append=True) as writer:
            def save_profile(profile):
                writer.write(profile)
                return False
            result = evaluator.evaluate_joint_arrangements(candidate, profile_consumer=save_profile,
                progress_sink=progress, external_stop_predicate=lambda: perf_counter()-started >= args.seconds)
        report[engine] = dict(elapsed=perf_counter()-started, stop=result.stop_reason,
            error=result.error, profiles=len(result.profiles), counters=result.counters,
            search_progress=latest.get('search_progress', {}))
        report[engine]['profiles_file'] = str(profiles_path)
        report[engine]['comparison'] = args.comparison
        print(engine, report[engine], flush=True)
        atomic_write_json(root/args.output, report)


if __name__ == '__main__':
    main()
