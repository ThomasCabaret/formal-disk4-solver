# Patch 0.8.0 - same-radius circular pre-word pruning

This differential patch applies on top of 0.7.0.

## Added

- A standalone `formal_disk4.preword` layer executed after `compile_word_case` and before `ExactPartialWordSolver`.
- Propagation of smooth arcs known to have the radius of the disk boundary.
- Convex/concave sign reversal across every internal interface.
- Rejection of a positive-length prototype interval forced to carry both signs.
- Rejection when a mapped smooth circular arc is forced to cross a hard exterior endpoint.
- Rejection when a symbolic circular image is forced to overlap an already known interval with the opposite sign.
- The closed-propagation signed-length identity
  `piece_count * (convex_length - concave_length) = total_exterior_length`.
- Fast HiGHS screening followed by exact rational certification of every LP-dependent rejection.
- Independent configuration and `--no-preword-circular` differential-debug option.
- Progress counters, timing, audit data and oracle statistics.

## Soundness boundary

The filter never invents a word subdivision. It propagates an interval only when both mapped endpoints are forced to existing atomic boundaries. A non-aligned image is still checked for forced endpoint crossing and opposite-sign overlap, but otherwise remains unresolved and is passed to Nielsen-Levi. The signed balance is applied only when no such unresolved image remains.

## Checkpoints

Search semantics changed from v6 to v7. Existing 0.7.0 K4 checkpoints must not be resumed; start the formal search with `run_full_k4.bat --restart` after preserving any old output directory you need.

## Validation

- 53 tests pass.
- `k3-pizza` and `k4-pizza` still produce their expected formal, geometric and visual validation solutions.
- A 20-second K4 profile rejected 1,919 of 1,920 compiled placements before Nielsen-Levi in the development environment.
