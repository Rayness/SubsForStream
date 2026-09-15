import base64
import json
from pathlib import Path
import subprocess
import threading
import time
import wave

import pytest
from discord_capture import DiscordCapture
from server import SubtitleServer


def test_independent_speakers_and_microphone():
    server = SubtitleServer()
    client = server._sio.test_client(server._app)
    server.register_speaker('discord:111111111111111', 'Анна')
    server.register_speaker('discord:222222222222222', 'Макс')
    assert server.submit_transcript('одинаковые слова', source='discord:111111111111111')
    assert server.submit_transcript('одинаковые слова', source='discord:222222222222222')
    assert server.submit_transcript('мой микрофон')
    packets = [event['args'][0] for event in client.get_received()]
    assert {p['speaker']['id'] for p in packets} == {'self', 'discord:111111111111111', 'discord:222222222222222'}
    server.emit_clear('discord:111111111111111')
    assert 'discord:222222222222222' in server._captions
    assert 'self' in server._captions
    server.remove_speaker('discord:111111111111111')
    assert not server.submit_transcript('старый поток', source='discord:111111111111111')


def test_bridge_routes_audio_and_rejects_invalid_packets(monkeypatch):
    instances = []
    class Recognizer:
        dropped_chunks = 0
        def __init__(self, on_text, on_status):
            self.audio = []
            self.stopped = False
            self.on_text = on_text
            instances.append(self)
        def start(self, *args, **kwargs):
            pass
        def feed_audio(self, pcm, gap=False):
            self.audio.append((pcm, gap))
        def stop(self):
            self.stopped = True
    monkeypatch.setattr('discord_capture.SpeechRecognizer', Recognizer)
    server = SubtitleServer()
    bridge = DiscordCapture(server, lambda _: None)
    bridge._factory = type('Factory', (), {'create': lambda _: None})()
    cfg = {'discord_limit': 2}
    ids = ['111111111111111', '222222222222222']
    for id in ids:
        bridge._handle({'event': 'speaker', 'id': id, 'name': id[-3:]}, cfg)
    bridge._handle({'event': 'audio', 'id': ids[0], 'pcm': base64.b64encode(b'\x01\x00' * 640).decode(), 'gap': True}, cfg)
    bridge._handle({'event': 'audio', 'id': ids[1], 'pcm': base64.b64encode(b'\x02\x00' * 320).decode()}, cfg)
    assert len(instances[0].audio) == 2
    assert instances[0].audio[0][1]
    assert instances[1].audio == [(b'\x02\x00' * 320, False)]
    bridge._handle({'event': 'audio', 'id': ids[0], 'pcm': 'invalid$$'}, cfg)
    assert len(instances[0].audio) == 2
    bridge._handle({'event': 'leave', 'id': ids[0]}, cfg)
    assert instances[0].stopped
    assert not instances[1].stopped


def test_real_external_streams_receive_silence_and_final_words():
    from models import MODEL_CACHE, TONE_NAME, DecoderFactory
    if not (MODEL_CACHE / 'vosk-model-small-ru-0.22').exists() or not (MODEL_CACHE / TONE_NAME / '0.wav').exists():
        pytest.skip('Requires cached test models/audio')
    import numpy as np
    server = SubtitleServer()
    received = []
    server._on_caption = received.append
    bridge = DiscordCapture(server, lambda _: None)
    cfg = {'engine': 'vosk', 'language': 'ru', 'native_model': 'small', 'discord_limit': 2}
    bridge._factory = DecoderFactory(cfg, lambda _: None, threading.Event())
    ids = ['111111111111111', '222222222222222']
    for id in ids:
        bridge._handle({'event': 'speaker', 'id': id, 'name': id}, cfg)
    with wave.open(str(MODEL_CACHE / TONE_NAME / '0.wav')) as audio:
        pcm = np.repeat(np.frombuffer(audio.readframes(audio.getnframes()), dtype=np.int16), 2)
    try:
        for offset in range(0, len(pcm), 320):
            data = base64.b64encode(pcm[offset:offset+320].tobytes()).decode()
            for id in ids:
                bridge._handle({'event': 'audio', 'id': id, 'pcm': data}, cfg)
            time.sleep(.02)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and len({p['speaker']['id'] for p in received if p.get('final')}) < 2:
            time.sleep(.02)
        assert {p['speaker']['id'] for p in received if p.get('final')} == {f'discord:{id}' for id in ids}
        assert any(not p.get('final') for p in received)
    finally:
        bridge.stop()
        for item in bridge._speakers.values():
            item['recognizer']._worker.join(2)


def test_discord_node_codec_without_network():
    import shutil
    root = Path(__file__).resolve().parents[1]
    node = shutil.which('node')
    if not node or not (root / 'discord_bridge/node_modules').exists():
        pytest.skip('Run npm ci in discord_bridge first')
    process = subprocess.run([node, str(root / 'discord_bridge/bridge.cjs'), '--check'], capture_output=True, text=True, timeout=20)
    assert process.returncode == 0, process.stderr
    assert json.loads(process.stdout)['pcm_bytes'] == 640
