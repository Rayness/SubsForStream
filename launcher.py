"""SubForStream: native control panel and optional browser recognition."""
import argparse
from collections import deque
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import colorchooser, messagebox
import customtkinter as ctk
from desktop_ui import DesktopUI, THEMES, CHOICES, BG, CARD, TEXT, DIM, ACCENT, GREEN
import webbrowser

from PIL import Image
import pystray
from recognizer import SpeechRecognizer
from discord_capture import DiscordCapture
from models import MODEL_CACHE, delete_model, download_model, installed_models
from server import SubtitleServer
from settings import BASE_DIR, CONFIG_FILE, load_config, save_config
from single_instance import SingleInstance
from version import VERSION, is_newer, latest_release



def resource(name):
    return Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent)) / name


def format_size(size):
    if size >= 1024 ** 3:
        return f'{size / 1024 ** 3:.1f} ГБ'
    return f'{size / 1024 ** 2:.0f} МБ'


def open_browser(url):
    candidates = [Path(os.environ.get('PROGRAMFILES', 'C:/Program Files')) / 'Google/Chrome/Application/chrome.exe',
                  Path(os.environ.get('LOCALAPPDATA', '.')) / 'Google/Chrome/Application/chrome.exe',
                  Path(os.environ.get('PROGRAMFILES(X86)', 'C:/Program Files (x86)')) / 'Microsoft/Edge/Application/msedge.exe']
    browser = next((str(p) for p in candidates if p.exists()), None) or shutil.which('chrome') or shutil.which('msedge')
    if browser:
        subprocess.Popen([browser, f'--app={url}', '--window-size=1100,760'])
    else:
        webbrowser.open(url)


class LauncherWindow(DesktopUI):
    def __init__(self, server):
        self.server = server
        ctk.set_appearance_mode('dark')
        self.root = ctk.CTk()
        self.root.title(f'SubForStream {VERSION} — субтитры для OBS')
        self.root.geometry('1160x840')
        self.root.minsize(960, 680)
        self.root.configure(fg_color=BG)
        try:
            self.root.iconbitmap(str(resource('icon.ico')))
        except tk.TclError:
            pass
        self.root.protocol('WM_DELETE_WINDOW', self.root.withdraw)
        self.events = deque(maxlen=200)
        self.actions = queue.SimpleQueue()
        self.closed = False
        self.pending_text = None
        self.status = 'Готово • выберите микрофон и нажмите «Начать»'
        self.recognizer = SpeechRecognizer(self._on_text, self._on_status)
        server._on_caption = self._on_caption
        self.discord_status = 'Не подключён'
        self.discord = DiscordCapture(server, lambda message: setattr(self, 'discord_status', message))
        self.config_path = CONFIG_FILE
        self.models_path = MODEL_CACHE
        self.update_status = ''
        self.model_status = ''
        self.models = {}
        self.model_download = None
        self.model_stop = threading.Event()
        self._participant_text = {}
        self._participant_rows = None
        self._ui_running = None
        self.config_vars = {}
        self.devices = {'По умолчанию': None}
        self._style()
        self._build()
        self._create_tray()
        self.root.after(40, self._poll)
        threading.Thread(target=self._devices, daemon=True).start()







    def _color(self, key):
        color = colorchooser.askcolor(self.config_vars[key].get(), parent=self.root)[1]
        if color:
            self.config_vars[key].set(color)

    def _copy(self, text):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)

    def _apply(self):
        try:
            data = {key: var.get() for key, var in self.config_vars.items()}
            for key in ('port', 'font_size', 'bg_opacity', 'max_width', 'max_speakers', 'discord_limit'):
                data[key] = int(data[key])
            data['fade_delay'] = float(data['fade_delay'])
            data['subtitle_theme'] = THEMES[data['subtitle_theme']]
            for key, choices in CHOICES.items():
                data[key] = choices[data[key]]
            data['mic_index'] = self.devices[self.mic_var.get()]
            self.server.save_settings(data)
            self.settings_note.set('Сохранено ✓  Для смены модели перезапустите распознавание.')
            return True
        except (ValueError, OSError, tk.TclError, KeyError) as exc:
            messagebox.showerror('Настройки', str(exc), parent=self.root)
            return False

    def _devices(self):
        try:
            import sounddevice as sd
            devices = {f'{i}: {d["name"]}': i for i, d in enumerate(sd.query_devices()) if d['max_input_channels'] > 0}
            self.actions.put(lambda: self._set_devices(devices))
        except Exception as exc:
            self._on_status(f'Не удалось получить микрофоны: {exc}')

    def _set_devices(self, devices):
        self.devices.update(devices)
        self.mic.configure(values=list(self.devices))
        index = self.server.config.get('mic_index')
        self.mic_var.set(next((name for name, value in self.devices.items() if value == index), 'По умолчанию'))

    def _toggle(self):
        if self.recognizer.running:
            self.recognizer.stop()
            self._on_status('Остановка…')
        elif self._apply():
            if not self.server.claim_source('native'):
                self._on_status('Сначала остановите распознавание в браузере.')
                return
            self.recognizer.start(self.server.config)

    def _browser(self):
        if self.recognizer.running:
            self._on_status('Сначала остановите локальный микрофон, затем откройте браузерный режим.')
            return
        self.server.release_source('native')
        open_browser(self.server.admin_url)

    def _clear(self):
        self.server.emit_clear()
        self.preview.set('')


    def _toggle_discord(self):
        if self.discord.running:
            self.discord.stop()
            self.discord_status = 'Отключение Discord…'
        elif self._apply():
            try:
                cfg = self.server.config
                self.discord.start(self.discord_token.get(), cfg['discord_channel_id'], cfg['discord_ignore_id'], cfg)
            except ValueError as exc:
                messagebox.showerror('Discord', str(exc), parent=self.root)

    def _refresh_models(self):
        def scan():
            try:
                items = installed_models()
            except OSError as exc:
                self.model_status = f'Не удалось прочитать папку моделей: {exc}'
                return
            self.actions.put(lambda: self._render_models(items))
        threading.Thread(target=scan, daemon=True).start()

    def _render_models(self, items):
        self.models = {item['name']: item for item in items}
        busy = self.model_download is not None
        for item in items:
            state, button = self.model_rows[item['name']]
            if self.model_download == item['name']:
                text, color, action, enabled = 'Скачивается…', ACCENT, 'Отменить', True
            elif item['state'] == 'ready':
                text, color = f"Готова · {format_size(item['size'])}", GREEN
                action, enabled = ('Удалить', not busy) if item['removable'] else ('Папка Vosk', False)
            elif item['state'] == 'broken':
                text, color, action, enabled = 'Не докачана', '#f87171', 'Удалить', not busy
            else:
                text, color, action, enabled = 'Не скачана', DIM, 'Скачать', not busy
            state.configure(text=text, text_color=color)
            button.configure(text=action, state='normal' if enabled else 'disabled')
        total = sum(item['size'] for item in items if item['path'])
        self.models_total.set(f'Всего на диске: {format_size(total)}')

    def _model_action(self, name):
        item = self.models.get(name)
        if item is None:
            return
        if self.model_download == name:
            self.model_stop.set()
            self.model_status = 'Отмена загрузки…'
            return
        if self.model_download:
            return
        if item['state'] == 'missing':
            self.model_download = name
            self.model_stop = threading.Event()
            threading.Thread(target=self._download_model, args=(item,), daemon=True).start()
        elif self._delete_model(item):
            self.model_status = f"{item['title']}: удалена"
        self._refresh_models()

    def _download_model(self, item):
        try:
            download_model(item['name'], lambda message: setattr(self, 'model_status', message), self.model_stop)
            self.model_status = f"{item['title']}: скачана ✓"
        except InterruptedError:
            self.model_status = 'Загрузка отменена'
        except Exception as exc:
            self.model_status = f'Ошибка загрузки: {exc}'
        finally:
            self.actions.put(self._finish_download)

    def _finish_download(self):
        self.model_download = None
        self._refresh_models()

    def _delete_model(self, item):
        if self.recognizer.running or self.discord.running:
            messagebox.showinfo('Модели', 'Остановите микрофон и Discord, затем удалите модель.', parent=self.root)
            return False
        if not messagebox.askyesno('Удалить модель', f"Удалить «{item['title']}»?\nОсвободится {format_size(item['size'])}. "
                                   'Если снова выбрать эту модель, она скачается заново.', parent=self.root):
            return False
        try:
            delete_model(item['path'])
        except (OSError, ValueError) as exc:
            messagebox.showerror('Модели', f'Не удалось удалить модель: {exc}', parent=self.root)
            return False
        self.recognizer.unload()
        return True

    def _open_models(self):
        MODEL_CACHE.mkdir(parents=True, exist_ok=True)
        os.startfile(MODEL_CACHE)

    def _open_config_folder(self):
        os.startfile(CONFIG_FILE.parent)

    def _check_updates(self):
        self.update_button.configure(state='disabled')
        self.update_status = 'Проверка…'
        def check():
            try:
                latest = latest_release()
                self.update_status = (f'Доступна версия {latest}. Скачайте её на странице загрузки.' if is_newer(latest)
                                      else f'У вас последняя версия ({VERSION}).')
            except Exception:
                self.update_status = 'Не удалось проверить обновления. Проверьте интернет или откройте страницу загрузки.'
            finally:
                self.actions.put(lambda: self.update_button.configure(state='normal'))
        threading.Thread(target=check, daemon=True).start()

    def _demo(self):
        if not self._apply():
            return
        for key, name, color, text in [('self', self.server.config['speaker_name'], '#60a5fa', 'Проверяем субтитры — всем привет!'), ('preview:anna', 'Анна', '#a78bfa', 'Привет! Теперь видно, кто говорит.'), ('preview:max', 'Макс', '#34d399', 'А мой текст остаётся отдельным облачком.')]:
            self.server._sio.emit('subtitle', {'text': text, 'speaker': {'id': key, 'name': name, 'color': color}})

    def _on_caption(self, packet):
        speaker = packet['speaker']
        if speaker['id'] == 'self':
            self._on_transcript(packet['text'], False)
        else:
            self._participant_text[speaker['id']] = packet['text']
        if packet.get('final'):
            self.events.append(f"{speaker['name']}: {packet['text']}")

    def _on_text(self, text, final):
        self.server.submit_transcript(text, final)

    def _on_transcript(self, text, final):
        self.pending_text = text
        if final:
            self.events.append(text)

    def _on_status(self, message):
        self.status = message

    def _poll(self):
        if self.closed:
            return
        while not self.actions.empty():
            self.actions.get_nowait()()
            if self.closed:
                return
        if self.status_var.get() != self.status:
            self.status_var.set(self.status)
        if self.discord_status_var.get() != self.discord_status:
            self.discord_status_var.set(self.discord_status)
        if self.model_status_var.get() != self.model_status:
            self.model_status_var.set(self.model_status)
        if self.update_status_var.get() != self.update_status:
            self.update_status_var.set(self.update_status)
        rows = tuple((key, name, self._participant_text.get(key, ''), drops) for key, name, drops in self.discord.participants())
        if rows != self._participant_rows:
            for item in self.participant_table.get_children():
                self.participant_table.delete(item)
            for key, name, text, drops in rows:
                self.participant_table.insert('', 'end', iid=key, values=(name, text, drops))
            self._participant_rows = rows
        if not self.discord.running:
            self._participant_text.clear()
        if self.pending_text is not None:
            self.preview.set(self.pending_text)
            self.pending_text = None
        if self.events:
            self.log.configure(state='normal')
            while self.events:
                self.log.insert('end', self.events.popleft() + '\n')
            lines = int(self.log.index('end-1c').split('.')[0])
            if lines > 200:
                self.log.delete('1.0', f'{lines-200}.0')
            self.log.see('end')
            self.log.configure(state='disabled')
        running = self.recognizer.running
        ui_running = (running, self.discord.running)
        if ui_running != self._ui_running:
            self.start_button.configure(text='■ Остановить' if running else '▶ Начать',
                                        fg_color='#ab4562' if running else ACCENT)
            self.mic_badge.configure(text='●  Микрофон работает' if running else '●  Микрофон выключен',
                                     text_color=GREEN if running else DIM)
            self.discord_badge.configure(text='●  Discord запущен' if ui_running[1] else '●  Discord отключён',
                                         text_color=GREEN if ui_running[1] else DIM)
            self.discord_button.configure(text='Отключить бота' if ui_running[1] else 'Подключить бота')
            self._ui_running = ui_running
        if running:
            self.server.claim_source('native')
        else:
            self.server.release_source('native')
        with self.server._lock:
            values = sorted(self.server.render_ms)
        render = f'{values[min(len(values)-1, int(len(values)*.95))]:.1f} мс' if values else 'ожидание OBS'
        metrics = f'Очередь аудио: {self.recognizer.queue_ms:.1f} мс  •  Обработка блока: {self.recognizer.decode_ms:.1f} мс\nПодтверждение кадра OBS, p95: {render}  •  Пропущено блоков: {self.recognizer.dropped_chunks}'
        if self.metrics.get() != metrics:
            self.metrics.set(metrics)
        self.root.after(40, self._poll)

    def _create_tray(self):
        try:
            icon = Image.open(resource('icon.png')).convert('RGBA').resize((64, 64))
        except OSError:
            icon = Image.new('RGB', (64, 64), ACCENT)
        def show(*_):
            self.actions.put(self.show)
        def quit_app(*_):
            self.actions.put(self.close)
        self.tray = pystray.Icon('SubForStream', icon, 'SubForStream', pystray.Menu(
            pystray.MenuItem('Открыть', show, default=True),
            pystray.MenuItem('Очистить субтитры', lambda *_: self.server.emit_clear()),
            pystray.MenuItem('Выход', quit_app)))
        threading.Thread(target=self.tray.run, daemon=True).start()

    def show(self):
        self.root.deiconify()
        self.root.lift()
        # Windows refuses focus to background processes; a brief topmost brings the window forward.
        self.root.attributes('-topmost', True)
        self.root.after(200, lambda: None if self.closed else self.root.attributes('-topmost', False))
        self.root.focus_force()

    def close(self):
        self.closed = True
        self.model_stop.set()
        self.recognizer.stop()
        self.discord.stop()
        self.tray.stop()
        self.root.destroy()
        self.server.stop()

    def run(self):
        self.root.mainloop()


def main():
    if getattr(sys, 'frozen', False) and sys.stdout is None:
        log = open(BASE_DIR / 'SubForStream.log', 'a', encoding='utf-8', buffering=1)
        sys.stdout = sys.stderr = log
    parser = argparse.ArgumentParser(description='SubForStream')
    parser.add_argument('--browser', action='store_true', help='Также открыть браузерное распознавание')
    parser.add_argument('--check', action='store_true', help='Проверить установку без включения микрофона')
    args = parser.parse_args()
    if args.check:
        import json
        import sounddevice
        import vosk
        import sherpa_onnx
        ctk.set_appearance_mode('dark')
        root = ctk.CTk()
        root.withdraw()
        ctk.CTkButton(root, text='Проверка интерфейса').pack()
        root.update_idletasks()
        root.destroy()
        check_server = SubtitleServer()
        client = check_server._app.test_client()
        for path in ('/', '/mic', '/admin', '/static/socket.io.min.js', '/static/speech.js'):
            if client.get(path).status_code != 200:
                raise RuntimeError(f'Проверка страницы не пройдена: {path}')
        bridge_dir = resource('discord_bridge')
        node = str(bridge_dir / 'node.exe') if (bridge_dir / 'node.exe').exists() else shutil.which('node')
        if not node:
            raise RuntimeError('Компонент Discord не найден')
        bridge_check = subprocess.run([node, str(bridge_dir / 'bridge.cjs'), '--check'],
                                      capture_output=True, text=True, timeout=20,
                                      creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if bridge_check.returncode or not json.loads(bridge_check.stdout).get('ok'):
            raise RuntimeError('Компонент Discord не прошёл проверку')
        print(json.dumps({'ok': True, 'version': VERSION, 'engines': ['vosk', 'tone'], 'ui': 'customtkinter', 'discord': True}, ensure_ascii=False))
        return
    instance = SingleInstance()
    if not instance.primary:
        instance.notify()
        return
    server = SubtitleServer(on_save=save_config)
    config = load_config()
    try:
        server.start(config['port'], config)
    except (OSError, SystemExit) as exc:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror('SubForStream', f'Не удалось запустить сервер на порту {config["port"]}. Возможно, приложение уже открыто.\n{exc}')
        root.destroy()
        return
    window = LauncherWindow(server)
    instance.listen(lambda: window.actions.put(window.show))
    if args.browser:
        open_browser(server.admin_url)
    window.run()


if __name__ == '__main__':
    main()
