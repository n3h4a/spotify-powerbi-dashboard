import pytest

from spotify_pipeline.cli import main


def test_cli_all_end_to_end(fixture_settings):
    s = fixture_settings
    code = main(
        [
            "build",
            "--raw",
            str(s.raw_csv),
            "--db",
            str(s.database),
        ]
    )
    assert code == 0
    # The fixture has 3 positions per day, so the 50-position rule must block.
    code = main(
        [
            "check",
            "--raw",
            str(s.raw_csv),
            "--db",
            str(s.database),
            "--report",
            str(s.quality_report),
        ]
    )
    assert code == 1
    assert "fifty_positions_per_snapshot" in s.quality_report.read_text()


def test_cli_rejects_missing_source(tmp_path):
    with pytest.raises(FileNotFoundError):
        main(["build", "--raw", str(tmp_path / "nope.csv"), "--db", str(tmp_path / "x.duckdb")])
