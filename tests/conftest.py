import pytest

from aiqa.secrets import ENV_NAMES


@pytest.fixture(autouse=True)
def isolate_access_sources(monkeypatch):
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("aiqa.secrets.shutil.which", lambda name: None)
