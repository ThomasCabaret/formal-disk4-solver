from __future__ import annotations

import argparse


def add_search_arguments(parser: argparse.ArgumentParser) -> None:
    """Add the shared, strategy-neutral Graph Lab search controls."""

    parser.add_argument(
        "--output-directory",
        help="override the Graph Lab output directory (kept inside the project)",
    )
    parser.add_argument(
        "--policy",
        choices=("prior", "learned"),
        help=(
            "graph-ordering policy; the stable default is prior, while learned "
            "ranking remains an explicit experimental opt-in"
        ),
    )
    parser.add_argument(
        "--tile-counts",
        metavar="DOMAIN",
        help=(
            "override the tile-count domain, for example 3-13,18-19; "
            "omitted sizes are never proposed"
        ),
    )
    parser.add_argument(
        "--exclude-rings",
        action="store_true",
        help="exclude outside-star plus simple tile-cycle graphs before ordering",
    )
    parser.add_argument(
        "--stein-symmetric",
        action="store_true",
        help=(
            "restrict proposals to audited Stein graphs with an imposed "
            "nontrivial rotational symmetry"
        ),
    )
    parser.add_argument(
        "--symmetry-orders",
        metavar="DOMAIN",
        help="optional Stein rotation-order domain, for example 2-4,6,8",
    )
    parser.add_argument(
        "--outer-crown-only",
        action="store_true",
        help="solve only the outer crown cut from each complete Stein graph",
    )
    parser.add_argument(
        "--free-outer-boundary",
        action="store_true",
        help=(
            "keep the complete graph while replacing its disk-circle boundary "
            "by an unconstrained free boundary"
        ),
    )
    parser.add_argument(
        "--joint-arrangement-search",
        action="store_true",
        help=(
            "jointly backtrack contour mappings and weak cyclic orders instead "
            "of enumerating or ranking complete mappings"
        ),
    )
    parser.add_argument(
        "--partial-crown-tiles",
        "--crown-region-tiles",
        dest="partial_crown_tiles",
        metavar="DOMAIN",
        help=(
            "solve a connected outer-crown region of the requested size(s); "
            "this implies --outer-crown-only"
        ),
    )
    parser.add_argument(
        "--prototype-symmetry",
        choices=("none", "structural"),
        help=(
            "leave the prototype unconstrained, or impose the structural "
            "rotation order on the prototype contour"
        ),
    )
