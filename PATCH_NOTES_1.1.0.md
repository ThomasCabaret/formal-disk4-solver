# Patch 1.1.0 - Parameterized double-cycle validation family

Apply this differential patch over version 1.0.1.

## New ready case

`double-cycle-6` encodes twelve congruent tiles with contact graph equal to the
prism graph over `C6`:

- `E1,...,E6` form the exterior cycle and each owns one disk-boundary arc;
- `I1,...,I6` form the interior cycle;
- each `Ei` shares one interface with `Ii`;
- `Ei,E(i+1),Ii,I(i+1)` meet at a four-tile interior vertex;
- all inner tiles meet at the central point `Z`;
- no tile is declared to contain the disk centre strictly.

The builder is generic: `build_double_cycle_map(N)` supports every `N >= 3`.
The registry accepts `double-cycle-N`; `double-cycle-6` and alias `dc6` are
listed as the bundled case.

## Large-domain assignment support

The six-cycle case has 6,115,295,232 raw phase/reflection assignments.  The
runner no longer materializes symmetry-off assignment domains.  It decodes the
current assignment directly from its mixed-radix index, which keeps startup and
checkpoint resume bounded in memory.

The new configuration key

```json
"track_exact_domain_size": false
```

disables only the exact weak-order counting DP.  Actual weak-order generation,
length/angle pruning, preword pruning and Nielsen-Levi solving are unchanged.
This is necessary because the twelve-cycle weak-order count has a prohibitively
large dynamic-programming state lattice.

## Case files and launchers

The ready case lives under `config/cases/double-cycle-6/` and writes independent
state under:

```text
output/cases/double-cycle-6/checkpoint.sqlite3
```

Launch it with:

```bat
run_case.bat double-cycle-6 profile
run_case.bat double-cycle-6 search --restart
run_double_cycle_6_pipeline.bat --restart
```

Create another size with:

```bat
create_double_cycle_case.bat 8
run_case.bat double-cycle-8 search --restart
```

## Validation

- 68 unit tests pass.
- `double-cycle-6` validates with 12 pieces, 18 internal interfaces, 6 exterior
  interfaces, 42 contour occurrences and a dihedral automorphism group of order
  12.
- A bounded profile starts immediately at assignment 1 of 6,115,295,232.
- SQLite resume was checked across two bounded runs of the same case.
