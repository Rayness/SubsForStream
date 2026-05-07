"""
SubForStream Launcher — нативный запускатель.

Движок: tkinter (встроен в Python, без дополнительных зависимостей).

Режимы запуска:
  python launcher.py              — нативное окно + трей
  python launcher.py --browser    — только трей, панель в браузере
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk
import webbrowser

from PIL import Image, ImageTk
import pystray

from server import SubtitleServer

# ─── Config ───────────────────────────────────────────────────────────────────

CONFIG_FILE = "config.json"


def _resource(name: str) -> str:
    """Путь к файлу ресурса — корректно работает и в .py, и в PyInstaller exe."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)

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

# ─── Цвета темы ───────────────────────────────────────────────────────────────

BG       = "#0f0f13"
CARD     = "#18181f"
BORDER   = "#2a2a35"
ACCENT   = "#3a86ff"
ACCENT2  = "#2563eb"
SUCCESS  = "#22c55e"
TEXT     = "#e0e0e0"
TEXT_DIM = "#888888"
TEXT_URL = "#a0c4ff"


# ─── Helpers ──────────────────────────────────────────────────────────────────

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
    try:
        return Image.open(_resource("icon.png")).resize((64, 64), Image.LANCZOS).convert("RGBA")
    except Exception:
        size = 64
        img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        from PIL import ImageDraw
        draw = ImageDraw.Draw(img)
        draw.ellipse((4, 4, size - 4, size - 4), fill=(58, 134, 255, 255))
        cx = size // 2
        draw.rectangle((cx - 6, 14, cx + 6, 36), fill=(255, 255, 255, 255))
        draw.arc((cx - 12, 26, cx + 12, 46), start=0, end=180, fill=(255, 255, 255, 255), width=3)
        draw.line((cx, 46, cx, 52), fill=(255, 255, 255, 255), width=3)
        return img


def _find_browser_exe() -> str | None:
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


def _open_app(url: str, browser_exe: str | None) -> None:
    if browser_exe:
        subprocess.Popen([browser_exe, f"--app={url}", "--window-size=1100,680", "--disable-extensions"])
    else:
        webbrowser.open(url)


# ─── Нативное окно (tkinter) ──────────────────────────────────────────────────

class LauncherWindow:
    def __init__(self, cfg: dict, server: SubtitleServer, browser_exe: str | None):
        self._cfg         = cfg
        self._server      = server
        self._browser_exe = browser_exe

        self._root = tk.Tk()
        self._root.title("SubForStream")
        self._root.configure(bg=BG)
        self._root.resizable(True, True)
        self._root.geometry("620x760")
        self._root.minsize(480, 520)
        self._root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Иконка окна
        try:
            icon_img = Image.open(_resource("icon.png")).resize((32, 32), Image.LANCZOS)
            self._tk_icon = ImageTk.PhotoImage(icon_img)
            self._root.iconphoto(True, self._tk_icon)
        except Exception:
            pass

        # Скрыть в трей при закрытии — иконка управляет через tray
        self._hidden = False

        self._build()
        self._center()

    # ── Построение UI ─────────────────────────────────────────────────────────

    def _build(self) -> None:
        root = self._root

        # ── Скроллируемый контейнер ──
        wrapper = tk.Frame(root, bg=BG)
        wrapper.pack(fill="both", expand=True)

        self._canvas = tk.Canvas(wrapper, bg=BG, highlightthickness=0, bd=0)
        scrollbar = ttk.Scrollbar(wrapper, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)

        self._scroll_frame = tk.Frame(self._canvas, bg=BG)
        self._scroll_win = self._canvas.create_window((0, 0), window=self._scroll_frame, anchor="nw")

        self._scroll_frame.bind("<Configure>", self._on_frame_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)
        self._canvas.bind_all("<MouseWheel>", self._on_mousewheel)

        # ── Содержимое ──
        self._build_content(self._scroll_frame)

    def _build_content(self, root: tk.Frame) -> None:
        # ── Заголовок ──
        hdr = tk.Frame(root, bg=BG)
        hdr.pack(fill="x", padx=28, pady=(28, 0))

        try:
            raw = Image.open(_resource("icon.png")).resize((48, 48), Image.LANCZOS)
            self._hdr_icon = ImageTk.PhotoImage(raw)
            tk.Label(hdr, image=self._hdr_icon, bg=BG).pack(side="left")
        except Exception:
            tk.Label(hdr, text="🎤", font=("Segoe UI", 28), bg=BG).pack(side="left")

        title_frame = tk.Frame(hdr, bg=BG)
        title_frame.pack(side="left", padx=(12, 0))
        tk.Label(title_frame, text="SubForStream", font=("Segoe UI", 20, "bold"),
                 fg=TEXT, bg=BG).pack(anchor="w")
        tk.Label(title_frame, text="Субтитры для OBS в реальном времени",
                 font=("Segoe UI", 11), fg=TEXT_DIM, bg=BG).pack(anchor="w")

        # ── Карточка: подключение ──
        self._card("Адреса подключения", self._build_urls, pady_top=20)

        # ── Карточка: порт ──
        self._card("Порт сервера", self._build_port, pady_top=12)

        # ── Карточка: инструкция OBS ──
        self._card("Инструкция по установке в OBS", self._build_steps, pady_top=12)

        # ── Кнопки запуска ──
        btn_frame = tk.Frame(root, bg=BG)
        btn_frame.pack(fill="x", padx=28, pady=(16, 28))
        self._make_btn(btn_frame, "  Открыть панель управления",
                       self._open_admin, accent=True).pack(fill="x", pady=(0, 8))
        self._make_btn(btn_frame, "  Открыть в браузере",
                       self._open_browser).pack(fill="x")

    def _on_frame_configure(self, _event=None) -> None:
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_configure(self, event) -> None:
        self._canvas.itemconfig(self._scroll_win, width=event.width)
        # Обновить wraplength для описаний шагов
        wrap = max(200, event.width - 120)
        for lbl in self._step_labels:
            lbl.configure(wraplength=wrap)

    def _on_mousewheel(self, event) -> None:
        self._canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _card(self, title: str, builder, pady_top: int = 12) -> None:
        outer = tk.Frame(self._scroll_frame, bg=BG)
        outer.pack(fill="x", padx=28, pady=(pady_top, 0))

        tk.Label(outer, text=title, font=("Segoe UI", 11, "bold"),
                 fg=TEXT, bg=BG).pack(anchor="w", pady=(0, 8))

        card = tk.Frame(outer, bg=CARD, highlightbackground=BORDER,
                        highlightthickness=1, bd=0)
        card.pack(fill="x")

        inner = tk.Frame(card, bg=CARD)
        inner.pack(fill="x", padx=16, pady=14)
        builder(inner)

    def _build_urls(self, parent: tk.Frame) -> None:
        obs_url   = self._server.admin_url.replace("/admin", "/")
        admin_url = self._server.admin_url
        self._url_row(parent, "Overlay для OBS Browser Source", obs_url)
        sep = tk.Frame(parent, bg=BORDER, height=1)
        sep.pack(fill="x", pady=10)
        self._url_row(parent, "Панель управления", admin_url)

    def _url_row(self, parent: tk.Frame, label: str, url: str) -> None:
        tk.Label(parent, text=label, font=("Segoe UI", 10),
                 fg=TEXT_DIM, bg=CARD).pack(anchor="w")
        row = tk.Frame(parent, bg=CARD)
        row.pack(fill="x", pady=(4, 0))

        var = tk.StringVar(value=url)
        entry = tk.Entry(row, textvariable=var, state="readonly",
                         font=("Consolas", 11), fg=TEXT_URL, bg="#0f0f13",
                         readonlybackground="#0f0f13",
                         relief="flat", bd=0,
                         highlightbackground=BORDER, highlightthickness=1)
        entry.pack(side="left", fill="x", expand=True, ipady=7, ipadx=8)

        btn = self._make_btn(row, "Копировать", lambda u=url: self._copy(u, btn))
        btn.pack(side="left", padx=(8, 0))

    def _build_port(self, parent: tk.Frame) -> None:
        row = tk.Frame(parent, bg=CARD)
        row.pack(fill="x")

        self._port_var = tk.StringVar(value=str(self._cfg.get("port", 5000)))
        entry = tk.Entry(row, textvariable=self._port_var, width=8,
                         font=("Segoe UI", 13), fg=TEXT, bg="#0f0f13",
                         insertbackground=TEXT, relief="flat", bd=0,
                         highlightbackground=BORDER, highlightthickness=1)
        entry.pack(side="left", ipady=7, ipadx=8)

        self._make_btn(row, "Сохранить", self._save_port, accent=True).pack(side="left", padx=(10, 0))

        self._port_note = tk.Label(row, text="", font=("Segoe UI", 10),
                                   fg=TEXT_DIM, bg=CARD)
        self._port_note.pack(side="left", padx=(12, 0))

    def _build_steps(self, parent: tk.Frame) -> None:
        self._step_labels: list[tk.Label] = []
        steps = [
            ("Запусти SubForStream",
             "Убедись что приложение запущено — иконка есть в системном трее."),
            ("OBS → Источники → \"+\"",
             "Внизу панели «Источники» нажми + и выбери «Браузер»."),
            ("Вставь URL Overlay",
             "В поле URL вставь адрес «Overlay для OBS Browser Source» выше."),
            ("Установи размеры",
             "Ширина: 1920, Высота: 1080 (должно совпадать с разрешением сцены)."),
            ("Нажми OK и растяни на весь экран",
             "Источник появится в сцене. Alt+перетаскивание для обрезки краёв."),
            ("Открой панель и начни запись",
             "Нажми «Открыть панель управления», кликни «Начать» — субтитры появятся в OBS."),
        ]
        for i, (title, desc) in enumerate(steps):
            self._step(parent, i + 1, title, desc)

    def _step(self, parent: tk.Frame, num: int, title: str, desc: str) -> None:
        row = tk.Frame(parent, bg=CARD)
        row.pack(fill="x", pady=(0, 10))

        num_canvas = tk.Canvas(row, width=28, height=28, bg=CARD, highlightthickness=0)
        num_canvas.create_oval(1, 1, 27, 27, outline=ACCENT, width=1)
        num_canvas.create_text(14, 14, text=str(num), fill=ACCENT,
                               font=("Segoe UI", 10, "bold"))
        num_canvas.pack(side="left", anchor="n", pady=2)

        body = tk.Frame(row, bg=CARD)
        body.pack(side="left", fill="x", expand=True, padx=(10, 0))
        tk.Label(body, text=title, font=("Segoe UI", 11, "bold"),
                 fg=TEXT, bg=CARD, anchor="w").pack(fill="x")
        lbl = tk.Label(body, text=desc, font=("Segoe UI", 10),
                       fg=TEXT_DIM, bg=CARD, anchor="w", wraplength=420, justify="left")
        lbl.pack(fill="x")
        self._step_labels.append(lbl)

    # ── Кнопки / утилиты ──────────────────────────────────────────────────────

    def _make_btn(self, parent, text: str, command, accent: bool = False) -> tk.Label:
        """Кнопка на базе tk.Label с hover-эффектом."""
        bg_normal = ACCENT if accent else CARD
        bg_hover  = ACCENT2 if accent else BORDER
        fg_normal = "#fff" if accent else TEXT_DIM

        btn = tk.Label(parent, text=text,
                       font=("Segoe UI", 10, "bold" if accent else "normal"),
                       fg=fg_normal, bg=bg_normal,
                       padx=14, pady=8, cursor="hand2")
        btn.bind("<Button-1>", lambda _: command())
        btn.bind("<Enter>",    lambda _: btn.configure(bg=bg_hover, fg="#fff"))
        btn.bind("<Leave>",    lambda _: btn.configure(bg=bg_normal, fg=fg_normal))
        return btn

    def _copy(self, text: str, btn: tk.Label) -> None:
        self._root.clipboard_clear()
        self._root.clipboard_append(text)
        old_text = btn.cget("text")
        btn.configure(text="Скопировано!", bg=SUCCESS)
        self._root.after(2000, lambda: btn.configure(text=old_text, bg=CARD))

    def _save_port(self) -> None:
        try:
            port = int(self._port_var.get())
            assert 1024 <= port <= 65535
        except Exception:
            self._port_note.configure(text="Неверный порт (1024–65535)", fg="#ef4444")
            return
        self._cfg["port"] = port
        _save_config(self._cfg)
        self._port_note.configure(
            text="Сохранено. Перезапусти приложение.", fg=TEXT_DIM)

    def _open_admin(self) -> None:
        _open_app(self._server.admin_url, self._browser_exe)

    def _open_browser(self) -> None:
        webbrowser.open(self._server.admin_url)

    def _center(self) -> None:
        self._root.update_idletasks()
        w = self._root.winfo_width()
        h = self._root.winfo_height()
        sw = self._root.winfo_screenwidth()
        sh = self._root.winfo_screenheight()
        self._root.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

    def _on_close(self) -> None:
        self._root.withdraw()
        self._hidden = True

    def show(self) -> None:
        self._root.deiconify()
        self._root.lift()
        self._hidden = False

    def destroy(self) -> None:
        try:
            self._root.destroy()
        except Exception:
            pass

    def run(self) -> None:
        self._root.mainloop()


# ─── Системный трей ───────────────────────────────────────────────────────────

def _run_with_window(cfg: dict, server: SubtitleServer) -> None:
    browser_exe = _find_browser_exe()
    win = LauncherWindow(cfg, server, browser_exe)

    def open_launcher(*_):
        win.show()

    def open_admin(*_):
        _open_app(server.admin_url, browser_exe)

    def clear_subtitle(*_):
        server.emit_clear()

    def quit_app(icon, _):
        _save_config(cfg)
        icon.stop()
        win.destroy()
        os._exit(0)

    menu = pystray.Menu(
        pystray.MenuItem("Открыть SubForStream", open_launcher),
        pystray.MenuItem("Панель управления", open_admin),
        pystray.MenuItem("Очистить субтитр", clear_subtitle),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Выход", quit_app),
    )
    icon = pystray.Icon("SubForStream", _make_icon(), "SubForStream", menu)
    threading.Thread(target=icon.run, daemon=True).start()

    win.run()  # блокирует главный поток (tkinter mainloop)


def _run_browser_only(cfg: dict, server: SubtitleServer) -> None:
    browser_exe = _find_browser_exe()

    def open_admin(*_):
        _open_app(server.admin_url, browser_exe)

    def clear_subtitle(*_):
        server.emit_clear()

    def quit_app(icon, _):
        _save_config(cfg)
        icon.stop()
        os._exit(0)

    menu = pystray.Menu(
        pystray.MenuItem("Открыть SubForStream", open_admin),
        pystray.MenuItem("Очистить субтитр", clear_subtitle),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Выход", quit_app),
    )
    icon = pystray.Icon("SubForStream", _make_icon(), "SubForStream", menu)
    threading.Timer(0.5, open_admin).start()
    icon.run()  # блокирует главный поток


# ─── Entry point ──────────────────────────────────────────────────────────────

def _is_frozen() -> bool:
    return getattr(sys, "frozen", False) or "__compiled__" in dir(sys.modules.get("__main__", object()))


def _hide_console() -> None:
    """Скрыть консольное окно exe — работает даже если Nuitka не убрал его флагом."""
    if not _is_frozen():
        return
    try:
        import ctypes
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)  # SW_HIDE
            ctypes.windll.kernel32.FreeConsole()
    except Exception:
        pass


def _fix_stdio() -> None:
    """В windowed exe stdout/stderr = None, что ломает Flask/werkzeug. Редиректим в лог."""
    if not _is_frozen():
        return
    if sys.stdout is not None:
        return
    log_path = os.path.join(os.path.dirname(sys.executable), "SubForStream.log")
    log = open(log_path, "w", encoding="utf-8", buffering=1)
    sys.stdout = log
    sys.stderr = log


def main() -> None:
    _hide_console()
    _fix_stdio()
    parser = argparse.ArgumentParser(description="SubForStream Launcher")
    parser.add_argument(
        "--browser", action="store_true",
        help="Только трей + браузер, без нативного окна",
    )
    args = parser.parse_args()

    cfg = _load_config()
    server = SubtitleServer(
        on_transcript=lambda *_: None,
        on_save=_save_config,
    )
    server.start(cfg["port"], cfg)

    if args.browser:
        _run_browser_only(cfg, server)
    else:
        _run_with_window(cfg, server)


if __name__ == "__main__":
    main()
