from pathlib import Path
from typing import Any

import pytest

from junit_time_diff import (
    __version__,
    compare_timings,
    format_percent,
    load_and_average_timings,
    load_junit_timings,
    main,
    percent_change,
)

TESTS_DIR = Path(__file__).parent


def timings(**durations: float) -> dict[str, Any]:
    """Build a timing dictionary in the shape returned by load_junit_timings."""
    tests = {test_id: {"duration": duration, "outcome": "passed"} for test_id, duration in durations.items()}
    return {
        "total_duration": sum(durations.values()),
        "test_count": len(tests),
        "tests": tests,
    }


def test_load_junit_timings_parses_sample_file() -> None:
    result = load_junit_timings(TESTS_DIR / "baseline.xml")

    assert result["test_count"] == 9
    assert result["total_duration"] == pytest.approx(3.512)
    assert result["tests"]["tests.test_complex::test_complex_one"]["duration"] == pytest.approx(1.527)
    assert result["tests"]["tests.test_simple::test_simple_three"]["outcome"] == "passed"


def test_load_junit_timings_handles_direct_testsuite_and_outcomes(
    tmp_path: Path,
) -> None:
    xml_path = tmp_path / "single.xml"
    xml_path.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<testsuite name="pytest" tests="3">
  <testcase classname="suite" name="passing" time="0.100" />
  <testcase classname="suite" name="failing" time="0.200"><failure /></testcase>
  <testcase classname="suite" name="erroring" time="0.000"><error /></testcase>
  <testcase classname="suite" name="bad_time" time="oops"><skipped /></testcase>
</testsuite>
""",
        encoding="utf-8",
    )

    result = load_junit_timings(xml_path)

    assert result["test_count"] == 4
    assert result["total_duration"] == pytest.approx(0.3)
    assert result["tests"]["suite::failing"]["outcome"] == "failed"
    assert result["tests"]["suite::erroring"]["outcome"] == "error"
    assert result["tests"]["suite::bad_time"]["duration"] == 0.0
    assert result["tests"]["suite::bad_time"]["outcome"] == "skipped"


def test_load_junit_timings_merges_repeated_test_ids(tmp_path: Path) -> None:
    """Reruns of the same test share an identifier, so their durations must be added together."""
    xml_path = tmp_path / "reruns.xml"
    xml_path.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="first">
    <testcase classname="suite" name="flaky" time="0.100"><failure /></testcase>
    <testcase classname="suite" name="stable" time="0.500" />
  </testsuite>
  <testsuite name="second">
    <testcase classname="suite" name="flaky" time="0.200" />
  </testsuite>
</testsuites>
""",
        encoding="utf-8",
    )

    result = load_junit_timings(xml_path)

    assert result["test_count"] == 2
    assert result["tests"]["suite::flaky"]["duration"] == pytest.approx(0.3)
    # The total must stay consistent with the per-test durations it is compared against.
    assert result["total_duration"] == pytest.approx(0.8)
    assert result["total_duration"] == pytest.approx(sum(test["duration"] for test in result["tests"].values()))


def test_load_and_average_timings_single_file_returns_single_run_data(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = load_and_average_timings(str(TESTS_DIR / "baseline.xml"))

    assert "num_runs" not in result
    assert result["test_count"] == 9

    output = capsys.readouterr().out
    assert "Loading 1 file(s)" in output


def test_load_and_average_timings_combines_multiple_runs(tmp_path: Path) -> None:
    run1 = tmp_path / "baseline1.xml"
    run2 = tmp_path / "baseline2.xml"
    run1.write_text((TESTS_DIR / "baseline.xml").read_text(encoding="utf-8"), encoding="utf-8")
    run2.write_text((TESTS_DIR / "current.xml").read_text(encoding="utf-8"), encoding="utf-8")

    result = load_and_average_timings(str(tmp_path / "baseline*.xml"))

    assert result["num_runs"] == 2
    assert result["test_count"] == 10
    assert result["tests"]["tests.test_complex::test_complex_one"]["duration"] == pytest.approx((1.527 + 1.694) / 2)
    assert result["tests"]["tests.test_simple::test_simple_three"]["runs"] == 1
    assert result["tests"]["tests.test_simple::test_simple_six"]["runs"] == 1


def test_load_and_average_timings_missing_files_raises() -> None:
    with pytest.raises(FileNotFoundError, match="No files match pattern"):
        load_and_average_timings(str(TESTS_DIR / "does-not-exist*.xml"))


def test_compare_timings_reports_changes(capsys: pytest.CaptureFixture[str]) -> None:
    baseline = load_junit_timings(TESTS_DIR / "baseline.xml")
    current = load_junit_timings(TESTS_DIR / "current.xml")

    exit_code = compare_timings(baseline, current, threshold=1.10, min_threshold_seconds=0.01)

    assert exit_code == 1
    output = capsys.readouterr().out
    assert "SLOWER TESTS (2 tests)" in output
    assert "FASTER TESTS (1 test)" in output
    assert "NEW TESTS (1 test" in output
    assert "REMOVED TESTS (1 test" in output
    assert "⚠ WARNING: Tests common to both runs are slower: 3.51s -> 3.69s (+5.0%)!" in output


def test_compare_timings_reports_both_overall_scopes(
    capsys: pytest.CaptureFixture[str],
) -> None:
    baseline = load_junit_timings(TESTS_DIR / "baseline.xml")
    current = load_junit_timings(TESTS_DIR / "current.xml")

    compare_timings(baseline, current)

    lines = capsys.readouterr().out.splitlines()
    all_row = next(line for line in lines if line.startswith("All tests"))
    common_row = next(line for line in lines if line.startswith("Common tests ("))

    # All 9 tests of each run: 3.512s -> 3.692s
    assert all_row.startswith("All tests (9 -> 9)")
    assert all_row.endswith("3.51s      3.69s     +0.18s    +5.1%")
    # Only the 8 tests present in both runs: 3.512s -> 3.688s
    assert common_row.startswith("Common tests (8)")
    assert common_row.endswith("3.51s      3.69s     +0.18s    +5.0%")


def test_compare_timings_ignores_new_tests_for_the_verdict(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A slow new test inflates the suite total but says nothing about the existing code."""
    baseline = timings(existing=1.0)
    current = timings(existing=1.0, added=5.0)

    exit_code = compare_timings(baseline, current)

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "✓ No significant performance regressions detected!" in output
    assert "ℹ The whole test suite changed by +500.0%, new and removed tests included" in output


def test_compare_timings_detects_regression_hidden_by_removed_tests(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Deleting a slow test makes the suite total drop even though the remaining test got slower."""
    baseline = timings(kept=1.0, deleted=10.0)
    current = timings(kept=1.5)

    exit_code = compare_timings(baseline, current)

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "⚠ WARNING: Tests common to both runs are slower: 1.00s -> 1.50s (+50.0%)!" in output
    assert "ℹ The whole test suite changed by -86.4%, new and removed tests included" in output


def test_compare_timings_without_common_tests_is_inconclusive(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = compare_timings(timings(only_baseline=1.0), timings(only_current=9.0))

    assert exit_code == 0
    assert "⚠ WARNING: Baseline and current runs have no tests in common!" in capsys.readouterr().out


def test_compare_timings_returns_failure_for_large_regression(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = compare_timings(timings(**{"suite::case": 1.0}), timings(**{"suite::case": 1.2}))

    assert exit_code == 1
    assert "⚠ WARNING: Tests common to both runs are slower: 1.00s -> 1.20s (+20.0%)!" in capsys.readouterr().out


def test_compare_timings_honors_overall_threshold(capsys: pytest.CaptureFixture[str]) -> None:
    baseline = timings(case=1.0)
    current = timings(case=1.2)

    assert compare_timings(baseline, current, overall_threshold=25.0) == 0
    assert (
        "ℹ INFO: Some tests got slower, but tests common to both runs changed only 1.00s -> 1.20s (+20.0%)"
        in capsys.readouterr().out
    )
    assert compare_timings(baseline, current, overall_threshold=15.0) == 1


def test_compare_timings_reports_undefined_percentages_as_not_available(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A test that took no measurable time in the baseline has no meaningful percentage change."""
    exit_code = compare_timings(timings(case=0.0), timings(case=0.5))

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "SLOWER TESTS (1 test)" in output
    assert "0.000s     0.500s    +0.500s      n/a" in output
    assert "⚠ WARNING: Tests common to both runs are slower: 0.00s -> 0.50s (n/a)!" in output


def test_compare_timings_ignores_large_changes_below_the_ratio_threshold(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A third of a second is a lot in absolute terms, but 3% of a ten second test is still noise."""
    exit_code = compare_timings(timings(case=10.0), timings(case=10.3), threshold=1.10)

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "SLOWER TESTS" not in output
    assert "✓ No significant performance regressions detected!" in output


def test_compare_timings_truncates_long_sections(capsys: pytest.CaptureFixture[str]) -> None:
    prefix = "tests.a_module_with_a_very_long_name::TestSomeClassWithALongName::test_"
    baseline = timings(**{f"{prefix}{index:02d}": 1.0 for index in range(25)})
    current = timings(**{f"{prefix}{index:02d}": 2.0 for index in range(25)})
    current["tests"].update({f"new_{index}": {"duration": 1.0, "outcome": "passed"} for index in range(15)})
    current["test_count"] = len(current["tests"])
    current["total_duration"] = sum(test["duration"] for test in current["tests"].values())

    compare_timings(baseline, current)

    output = capsys.readouterr().out
    assert "SLOWER TESTS (25 tests)" in output
    assert "... and 5 more" in output  # only the top 20 slower tests are listed
    assert "NEW TESTS (15 tests" in output
    assert "... and 5 more" in output  # only the top 10 new tests are listed
    # Long test ids are left-truncated to the width of the test column
    truncated = [line for line in output.splitlines() if line.startswith("...") and line.endswith("+100.0%")]
    assert len(truncated) == 20
    assert all(len(line.split()[0]) == 58 for line in truncated)


def test_compare_timings_reports_the_number_of_averaged_runs(
    capsys: pytest.CaptureFixture[str],
) -> None:
    baseline = dict(timings(case=1.0), num_runs=3)
    current = dict(timings(case=1.0), num_runs=5)

    compare_timings(baseline, current)

    output = capsys.readouterr().out
    assert "Baseline: 1 test, 1.00s total (averaged over 3 run(s))" in output
    assert "Current:  1 test, 1.00s total (averaged over 5 run(s))" in output


def test_percent_change_and_format_percent() -> None:
    assert percent_change(2.0, 3.0) == pytest.approx(50.0)
    assert percent_change(0.0, 0.0) == 0.0
    assert percent_change(0.0, 1.0) == float("inf")
    assert format_percent(50.0) == "  +50.0%"
    assert format_percent(float("inf")) == "     n/a"


def test_main_reports_regression_for_sample_files(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main([str(TESTS_DIR / "baseline.xml"), str(TESTS_DIR / "current.xml")])

    assert exit_code == 1
    output = capsys.readouterr().out
    assert "TEST TIMING COMPARISON REPORT" in output
    assert "Loading 1 file(s)" in output


def test_main_overall_threshold_downgrades_the_verdict(
    capsys: pytest.CaptureFixture[str],
) -> None:
    argv = [str(TESTS_DIR / "baseline.xml"), str(TESTS_DIR / "current.xml")]

    assert main(argv + ["--overall-threshold", "10"]) == 0
    assert "ℹ INFO: Some tests got slower" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["--threshold", "0.9"], "--threshold must be greater than 1"),
        (["--min-diff", "-1"], "--min-diff must not be negative"),
    ],
)
def test_main_rejects_invalid_options(argv: list[str], message: str, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as ex:
        main([str(TESTS_DIR / "baseline.xml"), str(TESTS_DIR / "current.xml")] + argv)

    assert ex.value.code == 2
    assert message in capsys.readouterr().err


def test_main_returns_one_and_prints_error_for_missing_file(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main([str(TESTS_DIR / "missing.xml"), str(TESTS_DIR / "current.xml")])

    assert exit_code == 1
    assert "Error: No files match pattern" in capsys.readouterr().err


def test_main_help_exits_with_usage(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as ex:
        main(["--help"])

    assert ex.value.code == 0
    assert "usage: junit-time-diff" in capsys.readouterr().out


def test_main_version_exits_with_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as ex:
        main(["--version"])

    assert ex.value.code == 0
    assert capsys.readouterr().out.strip() == f"junit-time-diff {__version__}"
