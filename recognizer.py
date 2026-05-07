"""
SpeechRecognizer — Vosk потоковая транскрипция.

Partial-результаты каждые ~40мс прямо во время речи.
Final-результат когда Vosk обнаруживает конец фразы.
"""

import json
import threading
import queue
from typing import Callable, Optional

import numpy as np
import sounddevice as sd
from vosk import Model, KaldiRecognizer, SetLogLevel

SetLogLevel(-1)   # Отключить лог Vosk

SAMPLE_RATE   = 16000
CHUNK_MS      = 40             # 40мс — быстрый отклик
CHUNK_SAMPLES = int(SAMPLE_RATE * CHUNK_MS / 1000)

# Имена моделей для авто-загрузки (vosk скачает в ~/.cache/vosk/ при первом запуске)
VOSK_MODELS = {
    ("ru", "small"): "vosk-model-small-ru-0.22",   # ~45MB
    ("ru", "large"): "vosk-model-ru-0.42",          # ~1.8GB
    ("en", "small"): "vosk-model-small-en-us-0.15", # ~40MB
    ("en", "large"): "vosk-model-en-us-0.42",       # ~1.8GB
}


class SpeechRecognizer:
    def __init__(
        self,
        on_text: Callable[[str, bool], None],
        on_status: Callable[[str], None],
    ):
        self._on_text   = on_text     # on_text(text, final)
        self._on_status = on_status
        self._model: Optional[Model] = None
        self._loaded_key: Optional[str] = None
        self._audio_q   = queue.Queue()
        self._stop_event = threading.Event()

    # ── Публичные методы ──────────────────────────────────────────────────

    def load_model(self, model_size: str, language: str, on_ready: Callable = None) -> None:
        key        = f"{language}_{model_size}"
        model_name = VOSK_MODELS.get((language, model_size), VOSK_MODELS[("ru", "small")])
        self._on_status(f"Загрузка {model_name}...")

        def _load():
            try:
                self._model      = Model(model_name=model_name)
                self._loaded_key = key
                self._on_status("Готово")
                if on_ready:
                    on_ready()
            except Exception as exc:
                self._on_status(f"Ошибка загрузки модели: {exc}")

        threading.Thread(target=_load, daemon=True).start()

    def start(self, config: dict) -> None:
        if self._model is None:
            self._on_status("Ошибка: модель не загружена")
            return
        self._stop_event.clear()
        threading.Thread(target=self._loop, args=(config,), daemon=True).start()
        self._on_status("Слушаю...")

    def stop(self) -> None:
        self._stop_event.set()
        self._on_status("Остановлено")

    @property
    def loaded_model_size(self) -> Optional[str]:
        """Ключ загруженной модели, формат: '<lang>_<size>'."""
        return self._loaded_key

    # ── Основной цикл ─────────────────────────────────────────────────────

    def _audio_callback(self, indata, frames, time_info, status):
        if not self._stop_event.is_set():
            # Vosk ожидает int16 bytes
            pcm = (indata[:, 0] * 32767).astype(np.int16)
            self._audio_q.put(bytes(pcm))

    def _loop(self, config: dict) -> None:
        threshold = config.get("threshold", 0.015)
        mic_index = config.get("mic_index")

        rec = KaldiRecognizer(self._model, SAMPLE_RATE)
        rec.SetWords(True)

        last_partial = ""

        try:
            with sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
                blocksize=CHUNK_SAMPLES,
                callback=self._audio_callback,
                device=mic_index,
            ):
                while not self._stop_event.is_set():
                    try:
                        data = self._audio_q.get(timeout=0.5)
                    except queue.Empty:
                        continue

                    # Простой RMS-гейт: не гоним тишину в Vosk
                    rms = np.sqrt(np.mean(np.frombuffer(data, dtype=np.int16).astype(np.float32) ** 2)) / 32767
                    if rms < threshold * 0.5:
                        continue

                    if rec.AcceptWaveform(data):
                        # Финальный результат фразы
                        result = json.loads(rec.Result())
                        text = result.get("text", "").strip()
                        if text:
                            self._on_text(text, True)
                        last_partial = ""
                    else:
                        # Частичный результат (обновляется каждые ~40мс)
                        partial = json.loads(rec.PartialResult())
                        text = partial.get("partial", "").strip()
                        if text and text != last_partial:
                            self._on_text(text, False)
                            last_partial = text

        except Exception as exc:
            self._on_status(f"Ошибка микрофона: {exc}")
