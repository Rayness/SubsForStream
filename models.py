"""Download official streaming models once, with cancellation and atomic install."""
import os
from pathlib import Path
import tarfile
import tempfile
import zipfile
import threading

_DOWNLOAD_LOCKS = {}
_DOWNLOAD_GUARD = threading.Lock()

TONE_NAME = 'sherpa-onnx-streaming-t-one-russian-2025-09-08'
TONE_URL = f'https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/{TONE_NAME}.tar.bz2'
MODEL_CACHE = Path(os.environ.get('LOCALAPPDATA', Path.home() / '.cache')) / 'SubForStream' / 'models'


def tone_model(on_status, stop):
    return _download_model(TONE_NAME, TONE_URL, ('model.onnx', 'tokens.txt'), on_status, stop)


def vosk_model(name, on_status, stop):
    import vosk
    for directory in getattr(vosk, 'MODEL_DIRS', []):
        if directory and (Path(directory) / name / 'am' / 'final.mdl').is_file():
            return Path(directory) / name
    return _download_model(name, f'https://alphacephei.com/vosk/models/{name}.zip',
                           ('am/final.mdl', 'conf/model.conf'), on_status, stop)


def _download_model(name, url, required, on_status, stop):
    with _DOWNLOAD_GUARD:
        lock = _DOWNLOAD_LOCKS.setdefault(name, threading.Lock())
    while not lock.acquire(timeout=.1):
        if stop.is_set():
            raise InterruptedError('Загрузка отменена')
    try:
        return _download_model_unlocked(name, url, required, on_status, stop)
    finally:
        lock.release()


def _download_model_unlocked(name, url, required, on_status, stop):
    import requests
    target = MODEL_CACHE / name
    if all((target / file).is_file() for file in required):
        return target
    if target.exists():
        raise ValueError(f'Неполная модель в {target}. Переместите эту папку и повторите загрузку.')
    MODEL_CACHE.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.download-', dir=MODEL_CACHE) as work:
        archive = Path(work) / 'model.tar.bz2'
        with requests.get(url, stream=True, timeout=(10, 30)) as response:
            response.raise_for_status()
            total = int(response.headers.get('Content-Length', 0))
            downloaded = 0
            with archive.open('wb') as output:
                for chunk in response.iter_content(1024 * 1024):
                    if stop.is_set():
                        raise InterruptedError('Загрузка отменена')
                    output.write(chunk)
                    downloaded += len(chunk)
                    suffix = f' / {total // 1048576} МБ' if total else ' МБ'
                    on_status(f'Скачивание {name}: {downloaded // 1048576}{suffix}')
        on_status('Распаковка модели…')
        if url.endswith('.zip'):
            with zipfile.ZipFile(archive) as source:
                root = Path(work).resolve()
                for member in source.infolist():
                    if stop.is_set():
                        raise InterruptedError('Загрузка отменена')
                    if not (root / member.filename).resolve().is_relative_to(root):
                        raise ValueError('Некорректный путь в архиве модели')
                    source.extract(member, work)
        else:
            with tarfile.open(archive) as source:
                source.extractall(work, filter='data')
        unpacked = Path(work) / name
        if not all((unpacked / file).is_file() for file in required):
            raise ValueError('В архиве отсутствуют файлы модели')
        if stop.is_set():
            raise InterruptedError('Загрузка отменена')
        unpacked.rename(target)
    return target


class ToneDecoder:
    """Small adapter sharing the same 20 ms input loop with Vosk."""
    def __init__(self, model=None, shared=None):
        import sherpa_onnx
        self.recognizer = shared or sherpa_onnx.OnlineRecognizer.from_t_one_ctc(
            tokens=str(model / 'tokens.txt'), model=str(model / 'model.onnx'),
            num_threads=2, sample_rate=8000, provider='cpu',
            enable_endpoint_detection=True, rule2_min_trailing_silence=0.5,
            rule3_min_utterance_length=20,
        )
        self.stream = self.recognizer.create_stream()
        self.result = ''

    def AcceptWaveform(self, data):
        import numpy as np
        samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768
        # sherpa resamples 16 kHz microphone audio internally to the model's 8 kHz.
        self.stream.accept_waveform(16000, samples)
        while self.recognizer.is_ready(self.stream):
            self.recognizer.decode_stream(self.stream)
        self.result = self.recognizer.get_result(self.stream).strip()
        final = self.recognizer.is_endpoint(self.stream)
        if final:
            self.recognizer.reset(self.stream)
        return final

    def PartialResult(self):
        import json
        return json.dumps({'partial': self.result}, ensure_ascii=False)

    def Result(self):
        import json
        return json.dumps({'text': self.result}, ensure_ascii=False)

    def FinalResult(self):
        import json
        import numpy as np
        # Flush the model's buffered context immediately (no wall-clock sleep).
        self.stream.accept_waveform(16000, np.zeros(16000, dtype=np.float32))
        self.stream.input_finished()
        while self.recognizer.is_ready(self.stream):
            self.recognizer.decode_stream(self.stream)
        return json.dumps({'text': self.recognizer.get_result(self.stream)}, ensure_ascii=False)

    def Reset(self):
        self.stream = self.recognizer.create_stream()
        self.result = ''


class DecoderFactory:
    """Share model weights between Discord speakers, but never decoding state."""
    def __init__(self, config, status, stop):
        import threading
        self.lock = threading.RLock()
        self.engine = config.get('engine', 'vosk')
        if self.engine == 'tone':
            if config.get('language', 'ru') != 'ru':
                raise ValueError('Для T-one выберите русский язык')
            self.model = ToneDecoder(tone_model(status, stop)).recognizer
        else:
            from vosk import Model, SetLogLevel
            from recognizer import VOSK_MODELS
            SetLogLevel(-1)
            name = VOSK_MODELS[(config.get('language', 'ru'), config.get('native_model', 'small'))]
            self.model = Model(str(vosk_model(name, status, stop)))

    def create(self):
        if self.engine == 'tone':
            with self.lock:
                return _LockedDecoder(ToneDecoder(shared=self.model), self.lock)
        from vosk import KaldiRecognizer
        return KaldiRecognizer(self.model, 16000)


class _LockedDecoder:
    def __init__(self, decoder, lock):
        self.decoder, self.lock = decoder, lock

    def __getattr__(self, name):
        method = getattr(self.decoder, name)
        def call(*args):
            with self.lock:
                return method(*args)
        return call
