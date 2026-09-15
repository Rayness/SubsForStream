"""A local Discord bot bridge feeding independent streaming recognizers."""
import base64
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading

from models import DecoderFactory
from recognizer import SpeechRecognizer


class DiscordCapture:
    def __init__(self, server, on_status):
        self.server, self.on_status = server, on_status
        self._stop = threading.Event()
        self._lock = threading.RLock()
        self._thread = None
        self._process = None
        self._speakers = {}
        self._factory = None
        self._last_error = ''

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self, token, channel, ignore, config):
        if not token.strip() or not re.fullmatch(r'\d{15,22}', channel):
            raise ValueError('Введите токен бота и ID голосового канала')
        if ignore and not re.fullmatch(r'\d{15,22}', ignore):
            raise ValueError('Ваш Discord ID должен состоять из цифр')
        with self._lock:
            if self.running:
                return False
            self._stop.clear()
            self._last_error = ''
            self._thread = threading.Thread(target=self._run, args=(token, channel, ignore, dict(config)), daemon=True)
            self._thread.start()
        return True

    def stop(self):
        self._stop.set()
        with self._lock:
            for item in self._speakers.values():
                item['recognizer'].stop()
            process = self._process
        if process:
            try:
                process.stdin.close()
            except (OSError, ValueError):
                pass
            def reap():
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.terminate()
            threading.Thread(target=reap, daemon=True).start()

    def participants(self):
        with self._lock:
            return [(key, item['name'], item['recognizer'].dropped_chunks) for key, item in self._speakers.items()]

    def _handle(self, message, config):
        event = message.get('event')
        if event in ('status', 'error'):
            text = str(message.get('message', 'Ошибка Discord'))[:300]
            if event == 'error':
                self._last_error = text
            self.on_status(text)
            return
        user = message.get('id', '')
        if not isinstance(user, str) or not re.fullmatch(r'\d{15,22}', user):
            return
        source = f'discord:{user}'
        with self._lock:
            if event == 'speaker':
                name = str(message.get('name', 'Discord'))[:40]
                if source in self._speakers:
                    self._speakers[source]['name'] = name
                    self.server.register_speaker(source, name)
                    return
                if len(self._speakers) >= config.get('discord_limit', 6):
                    return
                if not self.server.register_speaker(source, name):
                    return
                recognizer = SpeechRecognizer(
                    lambda text, final, key=source: self.server.submit_transcript(text, final, source=key),
                    lambda status, who=name: self.on_status(f'{who}: {status}') if status.startswith('Ошибка') else None,
                )
                self._speakers[source] = {'name': name, 'recognizer': recognizer, 'remainder': b''}
                recognizer.start(config, decoder_factory=self._factory.create)
            elif event == 'leave':
                self._remove(source)
            elif event == 'audio' and source in self._speakers:
                encoded = message.get('pcm')
                if not isinstance(encoded, str) or len(encoded) > 16000:
                    return
                try:
                    pcm = base64.b64decode(encoded, validate=True)
                except ValueError:
                    return
                if not pcm or len(pcm) % 2:
                    return
                item = self._speakers[source]
                if message.get('gap'):
                    item['remainder'] = b''
                pcm = item['remainder'] + pcm
                count = len(pcm) // 640
                for i in range(count):
                    item['recognizer'].feed_audio(pcm[i*640:(i+1)*640], gap=bool(message.get('gap')) and i == 0)
                item['remainder'] = pcm[count*640:]

    def _remove(self, source):
        item = self._speakers.pop(source, None)
        if item:
            item['recognizer'].stop()
            self.server.remove_speaker(source)

    def _run(self, token, channel, ignore, config):
        process = None
        try:
            base = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent)) / 'discord_bridge'
            bundled_node = base / 'node.exe'
            node = str(bundled_node) if bundled_node.exists() else shutil.which('node')
            if not node or not (base / 'node_modules' / '@discordjs' / 'voice').exists():
                raise RuntimeError('Компонент Discord не установлен. Используйте полную сборку приложения.')
            self.on_status('Подготовка модели для участников Discord…')
            self._factory = DecoderFactory(config, self.on_status, self._stop)
            if self._stop.is_set():
                return
            process = subprocess.Popen([node, str(base / 'bridge.cjs')], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding='utf-8',
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), bufsize=1)
            with self._lock:
                self._process = process
            # Token travels only through an anonymous pipe, never argv, config or log.
            process.stdin.write(json.dumps({'token': token, 'channel': channel, 'ignore': ignore,
                                             'limit': config.get('discord_limit', 6)}) + '\n')
            process.stdin.flush()
            token = ''
            self.on_status('Подключение к Discord…')
            while not self._stop.is_set():
                line = process.stdout.readline(32768)
                if not line:
                    break
                if len(line) >= 32768:
                    raise RuntimeError('Некорректный пакет Discord-моста')
                message = json.loads(line)
                if isinstance(message, dict):
                    self._handle(message, config)
            if not self._stop.is_set():
                self.on_status(self._last_error or 'Discord отключён. Проверьте токен и доступ бота к каналу, затем подключитесь снова.')
        except Exception as exc:
            self.on_status(f'Ошибка Discord: {str(exc)[:250]}')
        finally:
            token = ''
            with self._lock:
                for source in list(self._speakers):
                    self._remove(source)
                self._process = None
            if process:
                if process.poll() is None:
                    process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                for pipe in (process.stdin, process.stdout):
                    if pipe:
                        try:
                            pipe.close()
                        except OSError:
                            pass
            self._factory = None
            if self._stop.is_set():
                self.on_status('Discord отключён')
