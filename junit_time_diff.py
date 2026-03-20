#!/usr/bin/env python3
"""Compare test execution times from JUnit XML reports."""

import argparse
import glob
import statistics
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

__version__ = "0.1.0"


def load_junit_timings(filepath: Path) -> dict[str, Any]:
    """Load timing data from a JUnit XML file.

    Args:
        filepath: Path to the JUnit XML file.

    Returns:
        Dictionary with 'total_duration', 'test_count', and 'tests' keys.
    """
    tree = ET.parse(filepath)
    root = tree.getroot()

    tests: dict[str, dict[str, Any]] = {}
    total_duration = 0.0

    # Handle both <testsuites> wrapper and direct <testsuite>
    testsuites = root.findall(".//testsuite")
    if not testsuites:
        testsuites = [root] if root.tag == "testsuite" else []

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

            tests[test_id] = {
                "duration": duration,
                "outcome": outcome,
            }
            total_duration += duration

    return {
        "total_duration": total_duration,
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
    files = sorted(glob.glob(pattern))

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


def compare_timings(
    baseline: dict[str, Any],
    current: dict[str, Any],
    threshold: float = 1.10,
    min_threshold_seconds: float = 0.01,
) -> int:
    """Compare timing data and report significant differences.

    Args:
        baseline: Baseline timing data (before changes)
        current: Current timing data (after changes)
        threshold: Percentage threshold for reporting (e.g., 1.10 = 10% slower)
        min_threshold_seconds: Minimum absolute time difference to report (in seconds)

    Returns:
        Exit code (0 = no issues, 1 = significant slowdown detected)
    """
    baseline_tests = baseline["tests"]
    current_tests = current["tests"]

    # Find common tests
    common_tests = set(baseline_tests.keys()) & set(current_tests.keys())
    new_tests = set(current_tests.keys()) - set(baseline_tests.keys())
    removed_tests = set(baseline_tests.keys()) - set(current_tests.keys())

    # Calculate total time changes
    baseline_total = baseline["total_duration"]
    current_total = current["total_duration"]
    total_diff = current_total - baseline_total
    total_percent = (current_total / baseline_total - 1) * 100 if baseline_total > 0 else 0.0

    print("=" * 80)
    print("TEST TIMING COMPARISON REPORT")
    print("=" * 80)
    print()

    # Summary
    print("SUMMARY")
    print("-" * 80)
    baseline_runs = baseline.get("num_runs", 1)
    current_runs = current.get("num_runs", 1)
    if baseline_runs > 1 or current_runs > 1:
        print(
            f"Baseline: {baseline['test_count']} tests, {baseline_total:.2f}s total "
            f"(averaged over {baseline_runs} run(s))"
        )
        print(
            f"Current:  {current['test_count']} tests, {current_total:.2f}s total "
            f"(averaged over {current_runs} run(s))"
        )
    else:
        print(f"Baseline: {baseline['test_count']} tests, {baseline_total:.2f}s total")
        print(f"Current:  {current['test_count']} tests, {current_total:.2f}s total")
    print(f"Difference: {total_diff:+.2f}s ({total_percent:+.1f}%)")
    print(f"New tests: {len(new_tests)}, Removed tests: {len(removed_tests)}")
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
            percent_change = (ratio - 1) * 100
        else:
            ratio = float("inf") if current_duration > 0 else 1.0
            percent_change = 0.0

        # Check if difference is significant
        is_significant = (ratio >= threshold and diff >= min_threshold_seconds) or (
            ratio <= (2 - threshold) and abs(diff) >= min_threshold_seconds
        )
        if not is_significant:
            continue

        test_info = {
            "id": test_id,
            "baseline": baseline_duration,
            "current": current_duration,
            "diff": diff,
            "percent": percent_change,
        }
        if diff > 0:
            slower.append(test_info)
        else:
            faster.append(test_info)

    # Report slower tests
    if slower:
        slower.sort(key=lambda item: abs(item["diff"]), reverse=True)

        print(f"SLOWER TESTS ({len(slower)} tests)")
        print("-" * 80)
        print(f"{'Test':<60} {'Before':>10} {'After':>10} {'Diff':>10} {'Change':>8}")
        print("-" * 80)

        for test in slower[:20]:  # Show top 20
            test_name = test["id"]
            if len(test_name) > 60:
                test_name = "..." + test_name[-57:]

            print(
                f"{test_name:<60} "
                f"{test['baseline']:>9.3f}s "
                f"{test['current']:>9.3f}s "
                f"{test['diff']:>+9.3f}s "
                f"{test['percent']:>+7.1f}%"
            )

        if len(slower) > 20:
            print(f"... and {len(slower) - 20} more slower tests")
        print()

    # Report faster tests
    if faster:
        faster.sort(key=lambda item: abs(item["diff"]), reverse=True)

        print(f"FASTER TESTS ({len(faster)} tests)")
        print("-" * 80)
        print(f"{'Test':<60} {'Before':>10} {'After':>10} {'Diff':>10} {'Change':>8}")
        print("-" * 80)

        for test in faster[:20]:  # Show top 20
            test_name = test["id"]
            if len(test_name) > 60:
                test_name = "..." + test_name[-57:]

            print(
                f"{test_name:<60} "
                f"{test['baseline']:>9.3f}s "
                f"{test['current']:>9.3f}s "
                f"{test['diff']:>+9.3f}s "
                f"{test['percent']:>+7.1f}%"
            )

        if len(faster) > 20:
            print(f"... and {len(faster) - 20} more faster tests")
        print()

    # Report new tests
    if new_tests:
        new_test_list = sorted(
            ((test_id, current_tests[test_id]["duration"]) for test_id in new_tests),
            key=lambda item: item[1],
            reverse=True,
        )
        new_tests_total = sum(duration for _, duration in new_test_list)
        print(f"NEW TESTS ({len(new_tests)} tests, {new_tests_total:.2f}s total)")
        print("-" * 80)

        for test_id, duration in new_test_list[:10]:  # Show top 10
            test_name = test_id
            if len(test_name) > 60:
                test_name = "..." + test_name[-57:]
            print(f"{test_name:<60} {duration:>9.3f}s")

        if len(new_tests) > 10:
            print(f"... and {len(new_tests) - 10} more new tests")
        print()

    # Report removed tests
    if removed_tests:
        print(f"REMOVED TESTS ({len(removed_tests)} tests)")
        print("-" * 80)
        for test_id in sorted(removed_tests)[:10]:  # Show top 10
            test_name = test_id
            if len(test_name) > 70:
                test_name = "..." + test_name[-67:]
            print(f"  {test_name}")

        if len(removed_tests) > 10:
            print(f"... and {len(removed_tests) - 10} more removed tests")
        print()

    # Final verdict
    print("=" * 80)
    print("VERDICT")
    print("-" * 80)

    if not slower:
        print("✓ No significant performance regressions detected!")
        return_code = 0
    elif total_percent > 5:
        print(f"⚠ WARNING: Overall test suite is {total_percent:.1f}% slower!")
        print(f"  {len(slower)} tests got slower (threshold: {(threshold - 1) * 100:.0f}%)")
        return_code = 1
    else:
        print(f"ℹ INFO: Some tests got slower, but overall impact is {total_percent:+.1f}%")
        print(f"  {len(slower)} tests got slower (threshold: {(threshold - 1) * 100:.0f}%)")
        return_code = 0

    if faster:
        print(f"✓ {len(faster)} tests got faster!")

    print("=" * 80)
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

Generate JUnit XML with pytest:
  # Single run
  pytest --junit-xml=baseline.xml

  # Multiple runs (reduces timing variance)
  for i in {{1..5}}; do pytest --junit-xml=baseline$i.xml; done
  for i in {{1..5}}; do pytest --junit-xml=current$i.xml; done
  %(prog)s "baseline*.xml" "current*.xml"
        """.strip(),
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
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the command-line interface."""
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        print()
        baseline = load_and_average_timings(args.baseline)
        print()
        current = load_and_average_timings(args.current)
        print()
        return compare_timings(baseline, current, args.threshold, args.min_diff)
    except Exception as ex:
        print(f"Error: {ex}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
