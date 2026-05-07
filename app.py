"""
SubForStream — системный трей + панель управления для субтитров в OBS.

Режимы запуска:
  python app.py              — Chrome/Edge в app-режиме (без браузерного UI)
  python app.py --browser    — открывает браузер (Chrome / Edge / любой)
"""

import argparse
import json
import os
import shutil
import subprocess
import threading
import webbrowser

from PIL import Image, ImageDraw
import pystray

from server import SubtitleServer

# ─── Config ───────────────────────────────────────────────────────────────────

CONFIG_FILE = "config.json"

DEFAULT_CONFIG: dict = {
    "language":      "ru",
    "port":          5000,
    "font_size":     44,
    "fade_delay":    5,
    "font_family":   "Segoe UI",
    "font_color":    "#ffffff",
    "font_bold":     True,
    "font_italic":   False,
    "font_underline": False,
    "bg_color":      "#000000",
    "bg_opacity":    35,
    "censor":        False,
    "anim_type":     "fade",
    "bubble_style":  False,
    "position":      "bottom",
    "text_align":    "center",
    "text_shadow":   True,
    "max_width":     90,
}


def _load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                return {**DEFAULT_CONFIG, **json.load(f)}
        except Exception:
            pass
    return DEFAULT_CONFIG.copy()


def _save_config(cfg: dict) -> None:
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def _make_icon() -> Image.Image:
    """Создаёт PNG-иконку (синий круг с микрофоном) через Pillow."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((4, 4, size - 4, size - 4), fill=(58, 134, 255, 255))
    cx = size // 2
    draw.rectangle((cx - 6, 14, cx + 6, 36), fill=(255, 255, 255, 255))
    draw.arc((cx - 12, 26, cx + 12, 46), start=0, end=180, fill=(255, 255, 255, 255), width=3)
    draw.line((cx, 46, cx, 52), fill=(255, 255, 255, 255), width=3)
    return img


# ─── Режим: браузер ───────────────────────────────────────────────────────────

def _run_browser(cfg: dict, server: SubtitleServer) -> None:
    """Открывает панель в системном браузере, трей живёт в главном потоке."""

    def open_panel(*_):
        webbrowser.open(server.admin_url)

    def open_setup(*_):
        webbrowser.open(server.setup_url)

    def clear_subtitle(*_):
        server.emit_clear()

    def quit_app(icon, _):
        _save_config(cfg)
        icon.stop()
        os._exit(0)

    menu = pystray.Menu(
        pystray.MenuItem("Открыть SubForStream", open_panel),
        pystray.MenuItem("Подключение и OBS", open_setup),
        pystray.MenuItem("Очистить субтитр", clear_subtitle),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Выход", quit_app),
    )
    icon = pystray.Icon("SubForStream", _make_icon(), "SubForStream", menu)

    # Открыть панель при старте
    threading.Timer(0.5, open_panel).start()

    icon.run()  # блокирует главный поток


# ─── Режим: app-окно (Chrome/Edge без браузерного UI) ─────────────────────────

def _find_browser_exe() -> str | None:
    """Ищет Chrome или Edge на стандартных путях."""
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return shutil.which("chrome") or shutil.which("msedge")


def _run_app_mode(cfg: dict, server: SubtitleServer) -> None:
    """Открывает панель в Chrome/Edge --app (без адресной строки), трей в главном потоке."""

    browser_exe = _find_browser_exe()

    def _open_app(url: str) -> None:
        if browser_exe:
            subprocess.Popen([browser_exe, f"--app={url}", "--window-size=1100,680", "--disable-extensions"])
        else:
            webbrowser.open(url)

    def open_panel(*_):
        _open_app(server.admin_url)

    def open_setup(*_):
        _open_app(server.setup_url)

    def clear_subtitle(*_):
        server.emit_clear()

    def quit_app(icon, _):
        _save_config(cfg)
        icon.stop()
        os._exit(0)

    menu = pystray.Menu(
        pystray.MenuItem("Открыть SubForStream", open_panel),
        pystray.MenuItem("Подключение и OBS", open_setup),
        pystray.MenuItem("Очистить субтитр", clear_subtitle),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Выход", quit_app),
    )
    icon = pystray.Icon("SubForStream", _make_icon(), "SubForStream", menu)

    # Открыть панель при старте
    threading.Timer(0.5, open_panel).start()

    icon.run()  # блокирует главный поток


# ─── Entry point ──────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="SubForStream")
    parser.add_argument(
        "--browser", action="store_true",
        help="Открыть панель в браузере вместо встроенного окна",
    )
    args = parser.parse_args()

    cfg = _load_config()
    server = SubtitleServer(
        on_transcript=lambda *_: None,
        on_save=_save_config,
    )
    server.start(cfg["port"], cfg)

    if args.browser:
        _run_browser(cfg, server)
    else:
        _run_app_mode(cfg, server)


if __name__ == "__main__":
    main()
