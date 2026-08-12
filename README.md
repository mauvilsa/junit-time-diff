# junit-time-diff

`junit-time-diff` compares test execution times from JUnit XML reports and highlights meaningful slowdowns, speedups, new tests, and removed tests.

It works especially well with pytest's built-in `--junit-xml` output and can compare either single runs or averages computed from multiple XML files.

## Two Overall Comparisons

Every report contains two overall timing comparisons, because they answer different questions:

- **All tests**: the time of the whole baseline run against the time of the whole current run. This tells you whether the test suite as a whole became faster or slower, which is what matters for CI wall clock time. It moves whenever tests are added or removed, even if no existing test changed.
- **Common tests**: the same comparison restricted to the tests present in both runs. Since existing tests normally keep testing the same thing, this is the number that tells you whether the code itself became faster or slower. Adding or removing tests does not affect it.

The verdict and the exit code are based on the **common tests** comparison, so that a new slow test does not report a false regression, and deleting a slow test does not hide a real one.

## Installation

```bash
pip install junit-time-diff
```

For local development from this repository:

```bash
pip install -e .[test]
```

This installs the `junit-time-diff` command.

## Quick Start

### Single Run Comparison

```bash
pytest --junit-xml=baseline.xml

# make changes

pytest --junit-xml=current.xml

junit-time-diff baseline.xml current.xml
```

### Averaged Comparison Across Multiple Runs

```bash
for i in {1..5}; do pytest --junit-xml=baseline$i.xml; done

# make changes

for i in {1..5}; do pytest --junit-xml=current$i.xml; done

junit-time-diff "baseline*.xml" "current*.xml"
```

Quoting the glob pattern is recommended so the tool receives the pattern and expands it consistently.

## CLI Usage

```bash
junit-time-diff --help
```

```text
usage: junit-time-diff [-h] [--version] [--threshold THRESHOLD]
                       [--min-diff MIN_DIFF]
                       [--overall-threshold OVERALL_THRESHOLD]
                       baseline current
```

Arguments:

- `baseline`: Baseline JUnit XML file or glob pattern such as `baseline.xml` or `baseline*.xml`
- `current`: Current JUnit XML file or glob pattern such as `current.xml` or `current*.xml`

Options:

- `--threshold`: Ratio by which a single test must change to be listed, default `1.10`. A test is reported as slower at `1.10x` its baseline duration and as faster at `1/1.10x`
- `--min-diff`: Minimum absolute duration change in seconds for a single test to be listed, default `0.01`. Both this and `--threshold` must be exceeded, so tiny fast tests never create noise
- `--overall-threshold`: Percentage by which the total time of the tests common to both runs may grow before the command exits with code `1`, default `5`

## Exit Codes

- `0`: no significant regression. Either no test got slower, or the tests common to both runs stayed within `--overall-threshold`
- `1`: the tests common to both runs are more than `--overall-threshold` percent slower, or the reports could not be read

A run with no tests in common exits with `0` and prints a warning, since there is nothing to compare.

## Example Output

```text
====================================================================================================
TEST TIMING COMPARISON REPORT
====================================================================================================

SUMMARY
----------------------------------------------------------------------------------------------------
Baseline: 9 tests, 3.51s total
Current:  9 tests, 3.69s total
Common tests: 8, New tests: 1, Removed tests: 1

OVERALL TIMING
----------------------------------------------------------------------------------------------------
Scope                                                          Before      After       Diff   Change
----------------------------------------------------------------------------------------------------
All tests (9 -> 9)                                              3.51s      3.69s     +0.18s    +5.1%
Common tests (8)                                                3.51s      3.69s     +0.18s    +5.0%
The all-tests change is the common-tests change (+0.176s) plus new tests (+0.004s) minus removed tests (0.000s).

SLOWER TESTS (2 tests)
----------------------------------------------------------------------------------------------------
Test                                                           Before      After       Diff   Change
----------------------------------------------------------------------------------------------------
tests.test_complex::test_complex_four                          1.108s     1.422s    +0.314s   +28.3%
tests.test_complex::test_complex_one                           1.527s     1.694s    +0.167s   +10.9%

====================================================================================================
VERDICT
----------------------------------------------------------------------------------------------------
⚠ WARNING: Tests common to both runs are slower: 3.51s -> 3.69s (+5.0%)!
  2 tests got slower (per-test threshold: 10%)
✓ 1 test got faster!
ℹ The whole test suite changed by +5.1%, new and removed tests included
====================================================================================================
```

The full report also lists faster tests, new tests, and removed tests, each sorted by duration.

## Typical Workflows

### Compare Python Versions

```bash
python3.11 -m pytest --junit-xml=py311.xml
python3.12 -m pytest --junit-xml=py312.xml

junit-time-diff py311.xml py312.xml
```

### Compare a Specific Test Subset

```bash
pytest tests/test_api.py --junit-xml=baseline_api.xml

# make changes

pytest tests/test_api.py --junit-xml=current_api.xml

junit-time-diff baseline_api.xml current_api.xml
```

### Use a Stricter Threshold

```bash
junit-time-diff baseline.xml current.xml --threshold 1.05 --overall-threshold 2
```

### Fail a CI Job on a Regression

```bash
# Exits with 1 when the tests present in both runs are more than 5% slower.
junit-time-diff "baseline*.xml" "current*.xml"
```

## Tips

- Run several repetitions and compare averages to reduce noise.
- Compare results on the same machine when possible.
- Keep the selected test set consistent between baseline and current runs.
- Ignore tiny changes unless they are part of a repeated pattern.
- Read the common-tests comparison to judge the code, and the all-tests comparison to judge the CI time.

## Development

Build the package:

```bash
python3 -m build
```

Run tests:

```bash
pytest
```
