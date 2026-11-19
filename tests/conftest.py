import os

import pytest

from reelpress.config import load_settings


@pytest.fixture
def settings(tmp_path, monkeypatch):
    data = tmp_path / "data"
    monkeypatch.chdir(tmp_path)
    for key in list(os.environ):
        if key.startswith("REELPRESS_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("REELPRESS_DATA_DIR", str(data))
    loaded = load_settings()
    loaded.video_preset = "ultrafast"
    loaded.video_crf = 32
    loaded.video_width = 320
    loaded.video_height = 568
    loaded.video_fps = 12
    loaded.clip_seconds = 1.2
    loaded.login_timeout = 3
    return loaded


@pytest.fixture
def client(settings):
    from fastapi.testclient import TestClient

    from reelpress.web.app import create_app

    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client
