#!/usr/bin/env python3
"""Compare test execution times from JUnit XML reports."""

import argparse
import glob
import math
import os
import statistics
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

__version__ = "0.1.0"

# Percentage by which the common-test total must grow before the run is considered a regression.
DEFAULT_OVERALL_THRESHOLD = 5.0

# Maximum number of entries printed per report section.
MAX_CHANGED_TESTS = 20
MAX_LISTED_TESTS = 10

# Width of the test identifier column, and of the report as a whole. The four numeric columns of
# the report tables take up the remaining 42 characters.
TEST_COLUMN_WIDTH = 58
REPORT_WIDTH = TEST_COLUMN_WIDTH + 42


def load_junit_timings(filepath: Path) -> dict[str, Any]:
    """Load timing data from a JUnit XML file.

    Test cases are keyed by ``"{classname}::{name}"``. If the same identifier appears more than
    once in a report (for example because the test was rerun), the durations are added together so
    that the total always matches the sum of the reported per-test durations.

    Args:
        filepath: Path to the JUnit XML file.

    Returns:
        Dictionary with 'total_duration', 'test_count', and 'tests' keys.
    """
    tree = ET.parse(filepath)
    root = tree.getroot()

    tests: dict[str, dict[str, Any]] = {}

    # Handle both <testsuites> wrapper and direct <testsuite>
    testsuites = root.findall(".//testsuite")
    if root.tag == "testsuite":
        testsuites.insert(0, root)

    for testsuite in testsuites:
        for testcase in testsuite.findall("testcase"):
            classname = testcase.get("classname", "")
            name = testcase.get("name", "")
            time_str = testcase.get("time", "0")

            # Create unique test ID
            test_id = f"{classname}::{name}"

            # Parse time
            try:
                duration = float(time_str)
            except (TypeError, ValueError):
                duration = 0.0

            # Determine outcome
            if testcase.find("failure") is not None:
                outcome = "failed"
            elif testcase.find("error") is not None:
                outcome = "error"
            elif testcase.find("skipped") is not None:
                outcome = "skipped"
            else:
                outcome = "passed"

            if test_id in tests:
                tests[test_id]["duration"] += duration
            else:
                tests[test_id] = {"duration": duration}
            tests[test_id]["outcome"] = outcome

    return {
        "total_duration": sum(test["duration"] for test in tests.values()),
        "test_count": len(tests),
        "tests": tests,
    }


def load_and_average_timings(pattern: str) -> dict[str, Any]:
    """Load timing data from one or more JUnit XML files and average durations.

    Args:
        pattern: File pattern to match (e.g., "baseline*.xml" or "baseline.xml")

    Returns:
        Dictionary with averaged timing data.
    """
    # Find all matching files
    files = sorted(glob.glob(os.path.expanduser(pattern)))

    if not files:
        raise FileNotFoundError(f"No files match pattern: {pattern}")

    print(f"Loading {len(files)} file(s) matching '{pattern}':")
    for file in files:
        print(f"  - {file}")

    # Load all timing data
    all_timings = [load_junit_timings(Path(file)) for file in files]

    if len(all_timings) == 1:
        # Single file, return as-is
        return all_timings[0]

    # Collect all test IDs across all runs
    all_test_ids = set()
    for timing in all_timings:
        all_test_ids.update(timing["tests"].keys())

    # Calculate average duration for each test
    averaged_tests: dict[str, dict[str, Any]] = {}
    for test_id in all_test_ids:
        durations = []
        outcomes = []

        for timing in all_timings:
            if test_id in timing["tests"]:
                durations.append(timing["tests"][test_id]["duration"])
                outcomes.append(timing["tests"][test_id]["outcome"])

        # Average duration
        avg_duration = statistics.mean(durations) if durations else 0.0

        # Most common outcome (or first if tied)
        outcome = max(set(outcomes), key=outcomes.count) if outcomes else "unknown"

        averaged_tests[test_id] = {
            "duration": avg_duration,
            "outcome": outcome,
            "runs": len(durations),  # Track how many runs included this test
        }

    # Calculate total duration
    total_duration = sum(test["duration"] for test in averaged_tests.values())

    return {
        "total_duration": total_duration,
        "test_count": len(averaged_tests),
        "tests": averaged_tests,
        "num_runs": len(all_timings),
    }


def percent_change(before: float, after: float) -> float:
    """Return the percentage change from ``before`` to ``after``.

    Returns infinity when ``before`` is zero and ``after`` is not, since the relative change is
    undefined in that case.
    """
    if before > 0:
        return (after / before - 1) * 100
    return float("inf") if after > 0 else 0.0


def format_percent(value: float, width: int = 8) -> str:
    """Format a percentage for a report column, showing 'n/a' when it is not a finite number."""
    if not math.isfinite(value):
        return f"{'n/a':>{width}}"
    return f"{value:>+{width - 1}.1f}%"


def count_tests(count: int) -> str:
    """Return a count of tests as text, e.g. '1 test' or '3 tests'."""
    return f"{count} test" if count == 1 else f"{count} tests"


def truncate_test_id(test_id: str, width: int = TEST_COLUMN_WIDTH) -> str:
    """Left-truncate a test identifier so that it fits in ``width`` characters."""
    if len(test_id) <= width:
        return test_id
    return "..." + test_id[-(width - 3) :]


def total_duration_of(tests: dict[str, dict[str, Any]], test_ids: set[str]) -> float:
    """Return the summed duration of the given test identifiers."""
    return sum(tests[test_id]["duration"] for test_id in test_ids if test_id in tests)


def print_changed_tests(title: str, tests: list[dict[str, Any]]) -> None:
    """Print a table of tests whose duration changed significantly."""
    print(f"{title} ({count_tests(len(tests))})")
    print("-" * REPORT_WIDTH)
    print(f"{'Test':<{TEST_COLUMN_WIDTH}} {'Before':>10} {'After':>10} {'Diff':>10} {'Change':>8}")
    print("-" * REPORT_WIDTH)

    for test in tests[:MAX_CHANGED_TESTS]:
        print(
            f"{truncate_test_id(test['id']):<{TEST_COLUMN_WIDTH}} "
            f"{test['baseline']:>9.3f}s "
            f"{test['current']:>9.3f}s "
            f"{test['diff']:>+9.3f}s "
            f"{format_percent(test['percent'])}"
        )

    if len(tests) > MAX_CHANGED_TESTS:
        print(f"... and {len(tests) - MAX_CHANGED_TESTS} more")
    print()


def print_listed_tests(title: str, tests: dict[str, dict[str, Any]], test_ids: set[str]) -> None:
    """Print a table of tests that only exist in one of the two runs, slowest first."""
    listed = sorted(
        ((test_id, tests[test_id]["duration"]) for test_id in test_ids),
        key=lambda item: item[1],
        reverse=True,
    )
    print(f"{title} ({count_tests(len(listed))}, {sum(duration for _, duration in listed):.3f}s total)")
    print("-" * REPORT_WIDTH)

    for test_id, duration in listed[:MAX_LISTED_TESTS]:
        print(f"{truncate_test_id(test_id):<{TEST_COLUMN_WIDTH}} {duration:>9.3f}s")

    if len(listed) > MAX_LISTED_TESTS:
        print(f"... and {len(listed) - MAX_LISTED_TESTS} more")
    print()


def compare_timings(
    baseline: dict[str, Any],
    current: dict[str, Any],
    threshold: float = 1.10,
    min_threshold_seconds: float = 0.01,
    overall_threshold: float = DEFAULT_OVERALL_THRESHOLD,
) -> int:
    """Compare timing data and report significant differences.

    Two overall comparisons are reported. The 'all tests' comparison covers every test in each run
    and tells whether the test suite as a whole became faster or slower. The 'common tests'
    comparison only covers tests present in both runs, and is the one that reflects whether the
    code itself became faster or slower, since it is unaffected by added or removed tests.

    Args:
        baseline: Baseline timing data (before changes)
        current: Current timing data (after changes)
        threshold: Ratio threshold for reporting a per-test change (e.g., 1.10 = 10% slower)
        min_threshold_seconds: Minimum absolute time difference to report (in seconds)
        overall_threshold: Percentage by which the common-test total may grow before failing

    Returns:
        Exit code (0 = no issues, 1 = significant slowdown detected)
    """
    baseline_tests = baseline["tests"]
    current_tests = current["tests"]

    # Find common tests
    common_tests = set(baseline_tests.keys()) & set(current_tests.keys())
    new_tests = set(current_tests.keys()) - set(baseline_tests.keys())
    removed_tests = set(baseline_tests.keys()) - set(current_tests.keys())

    # Overall time change across every test of each run
    all_baseline_total = baseline["total_duration"]
    all_current_total = current["total_duration"]
    all_percent = percent_change(all_baseline_total, all_current_total)

    # Overall time change restricted to the tests present in both runs
    common_baseline_total = total_duration_of(baseline_tests, common_tests)
    common_current_total = total_duration_of(current_tests, common_tests)
    common_percent = percent_change(common_baseline_total, common_current_total)

    print("=" * REPORT_WIDTH)
    print("TEST TIMING COMPARISON REPORT")
    print("=" * REPORT_WIDTH)
    print()

    # Summary
    print("SUMMARY")
    print("-" * REPORT_WIDTH)
    baseline_runs = baseline.get("num_runs", 1)
    current_runs = current.get("num_runs", 1)
    if baseline_runs > 1 or current_runs > 1:
        print(
            f"Baseline: {count_tests(baseline['test_count'])}, {all_baseline_total:.2f}s total "
            f"(averaged over {baseline_runs} run(s))"
        )
        print(
            f"Current:  {count_tests(current['test_count'])}, {all_current_total:.2f}s total "
            f"(averaged over {current_runs} run(s))"
        )
    else:
        print(f"Baseline: {count_tests(baseline['test_count'])}, {all_baseline_total:.2f}s total")
        print(f"Current:  {count_tests(current['test_count'])}, {all_current_total:.2f}s total")
    print(f"Common tests: {len(common_tests)}, New tests: {len(new_tests)}, Removed tests: {len(removed_tests)}")
    print()

    # Overall timing, both for the whole suite and for the tests present in both runs
    print("OVERALL TIMING")
    print("-" * REPORT_WIDTH)
    print(f"{'Scope':<{TEST_COLUMN_WIDTH}} {'Before':>10} {'After':>10} {'Diff':>10} {'Change':>8}")
    print("-" * REPORT_WIDTH)
    scopes = [
        (
            f"All tests ({baseline['test_count']} -> {current['test_count']})",
            all_baseline_total,
            all_current_total,
            all_percent,
        ),
        (
            f"Common tests ({len(common_tests)})",
            common_baseline_total,
            common_current_total,
            common_percent,
        ),
    ]
    for label, before, after, percent in scopes:
        print(
            f"{label:<{TEST_COLUMN_WIDTH}} "
            f"{before:>9.2f}s "
            f"{after:>9.2f}s "
            f"{after - before:>+9.2f}s "
            f"{format_percent(percent)}"
        )
    if new_tests or removed_tests:
        new_total = total_duration_of(current_tests, new_tests)
        removed_total = total_duration_of(baseline_tests, removed_tests)
        print(
            f"The all-tests change is the common-tests change "
            f"({common_current_total - common_baseline_total:+.3f}s) plus new tests ({new_total:+.3f}s) "
            f"minus removed tests ({removed_total:.3f}s)."
        )
    print()

    # Analyze common tests
    slower = []
    faster = []

    for test_id in common_tests:
        baseline_duration = baseline_tests[test_id]["duration"]
        current_duration = current_tests[test_id]["duration"]
        diff = current_duration - baseline_duration

        if baseline_duration > 0:
            ratio = current_duration / baseline_duration
        else:
            ratio = float("inf") if current_duration > 0 else 1.0

        # Check if difference is significant: the relative change must clear the threshold in
        # either direction, and the absolute change must be worth looking at.
        if abs(diff) < min_threshold_seconds:
            continue
        if not (ratio >= threshold or ratio <= 1 / threshold):
            continue

        test_info = {
            "id": test_id,
            "baseline": baseline_duration,
            "current": current_duration,
            "diff": diff,
            "percent": percent_change(baseline_duration, current_duration),
        }
        if diff > 0:
            slower.append(test_info)
        else:
            faster.append(test_info)

    slower.sort(key=lambda item: abs(item["diff"]), reverse=True)
    faster.sort(key=lambda item: abs(item["diff"]), reverse=True)

    if slower:
        print_changed_tests("SLOWER TESTS", slower)
    if faster:
        print_changed_tests("FASTER TESTS", faster)
    if new_tests:
        print_listed_tests("NEW TESTS", current_tests, new_tests)
    if removed_tests:
        print_listed_tests("REMOVED TESTS", baseline_tests, removed_tests)

    # Final verdict
    print("=" * REPORT_WIDTH)
    print("VERDICT")
    print("-" * REPORT_WIDTH)

    common_change = (
        f"{common_baseline_total:.2f}s -> {common_current_total:.2f}s ({format_percent(common_percent).strip()})"
    )
    if not common_tests:
        print("⚠ WARNING: Baseline and current runs have no tests in common!")
        return_code = 0
    elif common_percent > overall_threshold:
        print(f"⚠ WARNING: Tests common to both runs are slower: {common_change}!")
        print(f"  {count_tests(len(slower))} got slower (per-test threshold: {(threshold - 1) * 100:.0f}%)")
        return_code = 1
    elif slower:
        print(f"ℹ INFO: Some tests got slower, but tests common to both runs changed only {common_change}")
        print(f"  {count_tests(len(slower))} got slower (per-test threshold: {(threshold - 1) * 100:.0f}%)")
        return_code = 0
    else:
        print("✓ No significant performance regressions detected!")
        return_code = 0

    if faster:
        print(f"✓ {count_tests(len(faster))} got faster!")

    if new_tests or removed_tests:
        changed = format_percent(all_percent).strip()
        print(f"ℹ The whole test suite changed by {changed}, new and removed tests included")

    print("=" * REPORT_WIDTH)
    return return_code


def build_parser() -> argparse.ArgumentParser:
    """Create the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="junit-time-diff",
        description="Compare test execution times from JUnit XML reports.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Compare single baseline with current run
  %(prog)s baseline.xml current.xml

  # Compare averaged results from multiple runs
  %(prog)s "baseline*.xml" "current*.xml"

  # Use custom threshold (15%% instead of default 10%%)
  %(prog)s baseline.xml current.xml --threshold 1.15

  # Ignore differences less than 0.05 seconds
  %(prog)s baseline.xml current.xml --min-diff 0.05

  # Fail as soon as the tests common to both runs are more than 2%% slower
  %(prog)s baseline.xml current.xml --overall-threshold 2

Generate JUnit XML with pytest:
  # Single run
  pytest --junit-xml=baseline.xml

  # Multiple runs (reduces timing variance)
  for i in {1..5}; do pytest --junit-xml=baseline$i.xml; done
  for i in {1..5}; do pytest --junit-xml=current$i.xml; done
  %(prog)s "baseline*.xml" "current*.xml"
        """.strip(),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "baseline",
        help="Baseline JUnit XML file or pattern (for example 'baseline.xml' or 'baseline*.xml').",
    )
    parser.add_argument(
        "current",
        help="Current JUnit XML file or pattern (for example 'current.xml' or 'current*.xml').",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=1.10,
        help="Ratio threshold for reporting significant changes (default: 1.10 = 10%% slower).",
    )
    parser.add_argument(
        "--min-diff",
        type=float,
        default=0.01,
        help="Minimum absolute time difference in seconds to report (default: 0.01).",
    )
    parser.add_argument(
        "--overall-threshold",
        type=float,
        default=DEFAULT_OVERALL_THRESHOLD,
        help=(
            "Percentage by which the total time of the tests present in both runs may grow "
            f"before exiting with code 1 (default: {DEFAULT_OVERALL_THRESHOLD:g})."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the command-line interface."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.threshold <= 1:
        parser.error("--threshold must be greater than 1")
    if args.min_diff < 0:
        parser.error("--min-diff must not be negative")

    try:
        print()
        baseline = load_and_average_timings(args.baseline)
        print()
        current = load_and_average_timings(args.current)
        print()
        return compare_timings(baseline, current, args.threshold, args.min_diff, args.overall_threshold)
    except Exception as ex:
        print(f"Error: {ex}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
