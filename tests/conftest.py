import hashlib
import shutil
from pathlib import Path

import pytest

from askdb.config import Settings

SAMPLE_DB = Path(__file__).resolve().parents[1] / "data" / "cloudmetrics.db"


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """A throwaway copy of the sample database, so tests can never touch the real file."""
    target = tmp_path / "db" / "cloudmetrics.db"
    target.parent.mkdir()
    shutil.copyfile(SAMPLE_DB, target)
    return target


@pytest.fixture
def settings() -> Settings:
    return Settings()


@pytest.fixture
def sha256():
    def _sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    return _sha256
