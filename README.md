# junit_time_diff

`junit_time_diff` compares test execution times from JUnit XML reports and highlights meaningful slowdowns, speedups, new tests, and removed tests.

It works especially well with pytest's built-in `--junit-xml` output and can compare either single runs or averages computed from multiple XML files.

## Installation

```bash
pip install junit-time-diff
```

For local development from this repository:

```bash
pip install -e .
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
usage: junit-time-diff [-h] [--threshold THRESHOLD] [--min-diff MIN_DIFF]
                       baseline current
```

Arguments:

- `baseline`: Baseline JUnit XML file or glob pattern such as `baseline.xml` or `baseline*.xml`
- `current`: Current JUnit XML file or glob pattern such as `current.xml` or `current*.xml`

Options:

- `--threshold`: Ratio threshold for reporting changes, default `1.10`
- `--min-diff`: Minimum absolute duration change in seconds, default `0.01`

## Example Output

```text
================================================================================
TEST TIMING COMPARISON REPORT
================================================================================

SUMMARY
--------------------------------------------------------------------------------
Baseline: 9 tests, 3.64s total
Current:  9 tests, 3.69s total
Difference: +0.05s (+1.3%)
New tests: 1, Removed tests: 1
```

The report then includes any significant slower tests, faster tests, new tests, removed tests, and a final verdict.

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
junit-time-diff baseline.xml current.xml --threshold 1.05
```

## Tips

- Run several repetitions and compare averages to reduce noise.
- Compare results on the same machine when possible.
- Keep the selected test set consistent between baseline and current runs.
- Ignore tiny changes unless they are part of a repeated pattern.

## Development

Build the package:

```bash
python3 -m build
```

Run tests:

```bash
pytest
```
