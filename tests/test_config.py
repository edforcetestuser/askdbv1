import pytest

from askdb.config import Settings


def test_defaults_match_the_spec():
    settings = Settings.from_env({})
    assert settings.query_timeout_seconds == 10
    assert settings.row_cap == 1000
    assert settings.busy_timeout_ms == 5000


def test_environment_overrides_defaults():
    settings = Settings.from_env(
        {
            "ASKDB_QUERY_TIMEOUT_SECONDS": "2.5",
            "ASKDB_ROW_CAP": "50",
            "ASKDB_BUSY_TIMEOUT_MS": "100",
        }
    )
    assert settings.query_timeout_seconds == 2.5
    assert settings.row_cap == 50
    assert settings.busy_timeout_ms == 100


@pytest.mark.parametrize("value", ["abc", "0", "-5", "1.5"])
def test_bad_row_cap_names_the_variable(value):
    with pytest.raises(ValueError, match="ASKDB_ROW_CAP"):
        Settings.from_env({"ASKDB_ROW_CAP": value})


def test_empty_value_falls_back_to_default():
    assert Settings.from_env({"ASKDB_ROW_CAP": ""}).row_cap == 1000
