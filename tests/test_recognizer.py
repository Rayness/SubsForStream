import json
import sys
import threading
import types
from recognizer import SpeechRecognizer


def test_audio_queue_drops_oldest_and_stop_ignores_callbacks():
    rec = SpeechRecognizer(lambda *_: None, lambda *_: None)
    for i in range(15):
        rec._audio_callback(bytes([i]), 1, None, False)
    assert rec._audio_q.qsize() == 10
    assert rec.dropped_chunks == 5
    assert rec._discontinuity.is_set()
    assert rec._audio_q.get_nowait()[1] == bytes([5])
    rec.stop()
    rec._audio_callback(b'ignored', 1, None, False)
    assert rec._audio_q.qsize() == 9


def test_silence_reaches_decoder_and_partial_is_immediate(monkeypatch):
    monkeypatch.setattr('models.vosk_model', lambda *_: 'fake-model')
    texts, chunks, statuses = [], [], []
    recognizer = SpeechRecognizer(lambda text, final: texts.append((text, final)), statuses.append)
    silence = bytes(640)
    class Decoder:
        def __init__(self, *_):
            pass
        def AcceptWaveform(self, data):
            chunks.append(data)
            if len(chunks) == 2:
                recognizer.stop()
                return True
            return False
        def PartialResult(self):
            return json.dumps({'partial': 'hello'})
        def Result(self):
            return json.dumps({'text': 'hello world'})
        def FinalResult(self):
            return '{}'
    class Stream:
        def __init__(self, **kwargs):
            assert kwargs['dtype'] == 'int16'
            assert kwargs['blocksize'] == 320
            self.callback = kwargs['callback']
        def __enter__(self):
            self.callback(b'voice', 320, None, False)
            self.callback(silence, 320, None, False)
        def __exit__(self, *_):
            pass
    monkeypatch.setitem(sys.modules, 'vosk', types.SimpleNamespace(Model=lambda **_: object(), KaldiRecognizer=Decoder, SetLogLevel=lambda _: None))
    monkeypatch.setitem(sys.modules, 'sounddevice', types.SimpleNamespace(RawInputStream=Stream))
    assert recognizer.start({'language': 'en'})
    recognizer._worker.join(2)
    assert not recognizer.running
    assert chunks == [b'voice', silence]
    assert texts == [('hello', False), ('hello world', True)]
    assert statuses[-1] == 'Остановлено'


def test_start_cannot_overlap_even_after_stop_request(monkeypatch):
    ready, finish = threading.Event(), threading.Event()
    recognizer = SpeechRecognizer(lambda *_: None, lambda *_: None)
    def run(_):
        ready.set()
        finish.wait(2)
    monkeypatch.setattr(recognizer, '_run', run)
    assert recognizer.start({})
    assert ready.wait(1)
    recognizer.stop()
    assert not recognizer.start({})
    finish.set()
    recognizer._worker.join(2)
    assert recognizer.start({})
    recognizer._worker.join(2)
