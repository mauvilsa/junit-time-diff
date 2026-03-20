from pathlib import Path

import pytest

from junit_time_diff import (
    compare_timings,
    load_and_average_timings,
    load_junit_timings,
    main,
)

TESTS_DIR = Path(__file__).parent


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
  <testcase classname="suite" name="bad_time" time="oops"><skipped /></testcase>
</testsuite>
""",
        encoding="utf-8",
    )

    result = load_junit_timings(xml_path)

    assert result["test_count"] == 3
    assert result["total_duration"] == pytest.approx(0.3)
    assert result["tests"]["suite::failing"]["outcome"] == "failed"
    assert result["tests"]["suite::bad_time"]["duration"] == 0.0
    assert result["tests"]["suite::bad_time"]["outcome"] == "skipped"


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
    assert "FASTER TESTS (1 tests)" in output
    assert "NEW TESTS (1 tests" in output
    assert "REMOVED TESTS (1 tests)" in output
    assert "⚠ WARNING: Overall test suite is 5.1% slower!" in output


def test_compare_timings_returns_failure_for_large_regression(
    capsys: pytest.CaptureFixture[str],
) -> None:
    baseline = {
        "total_duration": 1.0,
        "test_count": 1,
        "tests": {"suite::case": {"duration": 1.0, "outcome": "passed"}},
    }
    current = {
        "total_duration": 1.2,
        "test_count": 1,
        "tests": {"suite::case": {"duration": 1.2, "outcome": "passed"}},
    }

    exit_code = compare_timings(baseline, current, threshold=1.10, min_threshold_seconds=0.01)

    assert exit_code == 1
    assert "⚠ WARNING: Overall test suite is 20.0% slower!" in capsys.readouterr().out


def test_main_returns_zero_for_sample_files(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main([str(TESTS_DIR / "baseline.xml"), str(TESTS_DIR / "current.xml")])

    assert exit_code == 1
    output = capsys.readouterr().out
    assert "TEST TIMING COMPARISON REPORT" in output
    assert "Loading 1 file(s)" in output


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
