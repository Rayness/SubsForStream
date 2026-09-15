"""Local streaming recognition. Audio callback never waits for inference or UI."""
import json
import queue
import threading
import time
from contextlib import nullcontext

SAMPLE_RATE = 16000
CHUNK_MS = 20
CHUNK_SAMPLES = SAMPLE_RATE * CHUNK_MS // 1000
VOSK_MODELS = {
    ('ru', 'small'): 'vosk-model-small-ru-0.22',
    ('ru', 'large'): 'vosk-model-ru-0.42',
    ('en', 'small'): 'vosk-model-small-en-us-0.15',
    ('en', 'large'): 'vosk-model-en-us-0.42',
}


class SpeechRecognizer:
    def __init__(self, on_text, on_status):
        self._on_text = on_text
        self._on_status = on_status
        self._model = None
        self._loaded_key = None
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._worker = None
        self._audio_q = queue.Queue(maxsize=10)
        self._discontinuity = threading.Event()
        self.dropped_chunks = 0
        self.queue_ms = 0.0
        self.decode_ms = 0.0

    @property
    def running(self):
        return self._worker is not None and self._worker.is_alive()

    @property
    def loaded_model_size(self):
        return self._loaded_key

    def start(self, config, decoder_factory=None):
        with self._lock:
            if self.running:
                return False
            self._stop_event.clear()
            self._discontinuity.clear()
            self._audio_q = queue.Queue(maxsize=10)
            self.dropped_chunks = 0
            self._decoder_factory = decoder_factory
            self._last_audio_at = 0.0
            self._worker = threading.Thread(target=self._run, args=(dict(config),), daemon=True)
            self._worker.start()
        return True

    def stop(self):
        self._stop_event.set()

    def _audio_callback(self, indata, frames, time_info, status):
        if self._stop_event.is_set():
            return
        if status:
            self._discontinuity.set()
        packet = (time.perf_counter(), bytes(indata))
        self._last_audio_at = packet[0]
        try:
            self._audio_q.put_nowait(packet)

        except queue.Full:
            try:
                self._audio_q.get_nowait()
            except queue.Empty:
                pass
            self.dropped_chunks += 1
            self._discontinuity.set()
            self._audio_q.put_nowait(packet)

    def feed_audio(self, pcm, gap=False):
        if gap:
            self._discontinuity.set()
        self._audio_callback(pcm, len(pcm) // 2, None, False)

    def _run(self, config):
        try:
            import sounddevice as sd
            external = self._decoder_factory is not None
            if external:
                rec = self._decoder_factory()
            elif config.get('engine', 'vosk') == 'tone':
                if config.get('language', 'ru') != 'ru':
                    raise ValueError('T-one поддерживает русский. Для английского выберите Vosk.')
                from models import tone_model, ToneDecoder
                if self._loaded_key != 'tone':
                    path = tone_model(self._on_status, self._stop_event)
                    self._on_status('Загрузка T-one в память…')
                    self._model = ToneDecoder(path)
                    self._loaded_key = 'tone'
                rec = self._model
                rec.Reset()
            else:
                from vosk import Model, KaldiRecognizer, SetLogLevel
                SetLogLevel(-1)
                key = (config.get('language', 'ru'), config.get('native_model', 'small'))
                if key != self._loaded_key:
                    self._on_status('Загрузка Vosk (при первом запуске нужен интернет)…')
                    from models import vosk_model
                    path = vosk_model(VOSK_MODELS[key], self._on_status, self._stop_event)
                    self._model = Model(model_path=str(path))
                    self._loaded_key = key
                rec = KaldiRecognizer(self._model, SAMPLE_RATE)
            if self._stop_event.is_set():
                return
            last_partial = ''
            capture = nullcontext() if external else sd.RawInputStream(samplerate=SAMPLE_RATE, channels=1, dtype='int16',
                                   blocksize=CHUNK_SAMPLES, latency='low',
                                   device=config.get('mic_index'), callback=self._audio_callback)
            with capture:
                self._on_status('Слушаю • локально')
                while not self._stop_event.is_set():
                    try:
                        captured, data = self._audio_q.get(timeout=0.02 if external else 0.1)
                    except queue.Empty:
                        # Discord omits silence packets. Feed a short tail for endpoints,
                        # then idle without repeatedly running inference on silent users.
                        if not external or time.perf_counter() - self._last_audio_at > 2.0:
                            continue
                        captured, data = time.perf_counter(), bytes(CHUNK_SAMPLES * 2)
                    self.queue_ms = (time.perf_counter() - captured) * 1000
                    if self._discontinuity.is_set():
                        self._discontinuity.clear()
                        rec.Reset()
                        last_partial = ''
                    began = time.perf_counter()
                    # Silence is required for endpoint detection; never discard it.
                    final = rec.AcceptWaveform(data)
                    result = json.loads(rec.Result() if final else rec.PartialResult())
                    self.decode_ms = (time.perf_counter() - began) * 1000
                    text = result.get('text' if final else 'partial', '').strip()
                    if text and (final or text != last_partial):
                        self._on_text(text, bool(final))
                    last_partial = '' if final else text
                tail = json.loads(rec.FinalResult()).get('text', '').strip()
                if tail:
                    self._on_text(tail, True)
            self._on_status('Остановлено')
        except Exception as exc:
            self._on_status(f'Ошибка: {exc}')
        finally:
            if self._stop_event.is_set():
                self._on_status('Остановлено')
