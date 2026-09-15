import pytest
from server import SubtitleServer
from settings import DEFAULT_CONFIG, validate_config


@pytest.fixture
def server():
    return SubtitleServer()


def test_routes_and_assets(server):
    client = server._app.test_client()
    for path in ('/', '/mic', '/admin', '/setup', '/static/speech.js', '/static/socket.io.min.js'):
        assert client.get(path).status_code == 200
    assert b'https://cdn.socket.io' not in client.get('/').data


@pytest.mark.parametrize('bad', [{'bg_color': 'red'}, {'font_size': 'big'}, {'port': 1},
                                  {'fade_delay': float('nan')}, {'font_family': '</style>'},
                                  {'font_bold': 1}, ['invalid'], {'anim_type': []}])
def test_invalid_settings_leave_state_intact(server, bad):
    client = server._app.test_client()
    before = server.config
    assert client.post('/api/config', json=bad).status_code == 400
    assert server.config == before
    assert client.get('/').status_code == 200


def test_failed_persistence_leaves_state_intact():
    def fail(_):
        raise OSError('disk full')
    server = SubtitleServer(on_save=fail)
    before = server.config
    assert server._app.test_client().post('/api/config', json={'font_size': 60}).status_code == 500
    assert server.config == before


def test_partials_final_censor_and_single_source(server):
    source = server._sio.test_client(server._app)
    overlay = server._sio.test_client(server._app)
    other = server._sio.test_client(server._app)
    assert source.emit('claim', callback=True)['ok']
    assert not other.emit('claim', callback=True)['ok']
    source.emit('transcript', {'text': 'привет', 'final': False})
    source.emit('transcript', {'text': 'привет', 'final': False})
    events = overlay.get_received()
    assert [e['name'] for e in events] == ['subtitle']
    source.emit('transcript', {'text': 'привет', 'final': True})
    assert [e['name'] for e in overlay.get_received()] == ['log']
    source.disconnect()
    assert other.emit('claim', callback=True)['ok']
    server.save_settings({'censor': True})
    overlay.get_received()
    other.emit('transcript', {'text': 'сука', 'final': False})
    first = overlay.get_received()[0]['args'][0]['text']
    other.emit('transcript', {'text': 'сука опять', 'final': False})
    assert overlay.get_received()[0]['args'][0]['text'].startswith(first)


def test_clear_then_same_partial_is_delivered(server):
    receiver = server._sio.test_client(server._app)
    server.submit_transcript('hello')
    server.emit_clear()
    server.submit_transcript('hello')
    assert [e['args'][0]['text'] for e in receiver.get_received()] == ['hello', '', 'hello']


def test_malformed_transcript_and_metrics(server):
    client = server._sio.test_client(server._app)
    for data in [None, [], {'text': 42}, {'text': 'valid', 'final': 'yes'}]:
        client.emit('transcript', data)
    assert client.get_received() == []
    client.emit('transcript', {'text': 'valid', 'final': False})
    packet = client.get_received()[0]['args'][0]
    client.emit('rendered', {'seq': packet['seq']})
    metrics = server._app.test_client().get('/api/metrics').json
    assert metrics['samples'] == 1
    assert metrics['render_ack_p95_ms'] >= 0


def test_settings_valid_defaults():
    assert validate_config(DEFAULT_CONFIG) == DEFAULT_CONFIG
