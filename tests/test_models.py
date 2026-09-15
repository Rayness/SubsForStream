import threading
import pytest
import models
from single_instance import SingleInstance


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(models, 'MODEL_CACHE', tmp_path)
    monkeypatch.setattr(models, '_vosk_dirs', lambda: [])
    return tmp_path


def make_model(folder, files):
    for file in files:
        (folder / file).parent.mkdir(parents=True, exist_ok=True)
        (folder / file).write_bytes(b'x' * 1024)


def test_installed_models_reports_ready_broken_and_missing(cache):
    make_model(cache / 'vosk-model-small-ru-0.22', models.VOSK_FILES)
    (cache / models.TONE_NAME).mkdir()
    state = {item['name']: item for item in models.installed_models()}
    assert state['vosk-model-small-ru-0.22']['state'] == 'ready'
    assert state['vosk-model-small-ru-0.22']['size'] == 2048
    assert state['vosk-model-small-ru-0.22']['removable']
    assert state[models.TONE_NAME]['state'] == 'broken'
    assert state['vosk-model-en-us-0.42']['state'] == 'missing'
    assert state['vosk-model-en-us-0.42']['path'] is None


def test_model_in_vosk_folder_is_shown_but_not_removable(cache, tmp_path_factory, monkeypatch):
    external = tmp_path_factory.mktemp('vosk')
    make_model(external / 'vosk-model-small-en-us-0.15', models.VOSK_FILES)
    monkeypatch.setattr(models, '_vosk_dirs', lambda: [external])
    item = next(item for item in models.installed_models() if item['name'] == 'vosk-model-small-en-us-0.15')
    assert item['state'] == 'ready' and not item['removable']
    with pytest.raises(ValueError):
        models.delete_model(item['path'])
    assert item['path'].exists()


def test_delete_model_removes_folder_and_refuses_during_download(cache):
    target = cache / 'vosk-model-small-ru-0.22'
    make_model(target, models.VOSK_FILES)
    lock = models._DOWNLOAD_LOCKS.setdefault(target.name, threading.Lock())
    with lock:
        with pytest.raises(ValueError):
            models.delete_model(target)
    assert target.exists()
    models.delete_model(target)
    assert not target.exists()
    assert list(cache.iterdir()) == []


def test_second_instance_wakes_the_first():
    name = 'Local\\SubForStream-test-single-instance'
    first, second = SingleInstance(name), SingleInstance(name)
    woke = threading.Event()
    try:
        assert first.primary
        assert not second.primary
        first.listen(woke.set)
        second.notify()
        assert woke.wait(2)
    finally:
        second.close()
        first.close()
    assert SingleInstance(name).primary
