from pathlib import Path
import json
import wave
import pytest
from models import MODEL_CACHE, TONE_NAME, ToneDecoder
from server import SubtitleServer


def test_native_window_build_and_thread_dispatch(monkeypatch):
    import customtkinter as ctk
    from launcher import LauncherWindow
    root = ctk.CTk()
    root.withdraw()
    monkeypatch.setattr(ctk, 'CTk', lambda: root)
    monkeypatch.setattr(LauncherWindow, '_create_tray', lambda _: None)
    monkeypatch.setattr(LauncherWindow, '_devices', lambda _: None)
    window = LauncherWindow(SubtitleServer())
    try:
        root.update_idletasks()
        assert {'engine', 'language', 'font_size', 'port', 'censor'} <= window.config_vars.keys()
        window._on_transcript('проверка интерфейса', True)
        window._poll()
        assert window.preview.get() == 'проверка интерфейса'
        assert 'проверка интерфейса' in window.log.get('1.0', 'end')
        called = []
        window.actions.put(lambda: called.append(True))
        window._poll()
        assert called == [True]
        for page in ('discord', 'look', 'obs', 'live'):
            window._show_page(page)
            root.update_idletasks()
            assert window.active_page == page
        window._select_theme('Неон')
        assert window._apply()
        assert window.server.config['subtitle_theme'] == 'neon'
        import desktop_ui
        urls = []
        monkeypatch.setattr(desktop_ui.webbrowser, 'open', lambda url: urls.append(url))
        window.donate_button.invoke()
        assert urls == ['https://boosty.to/rayness']
    finally:
        window.closed = True
        root.destroy()


def test_select_search_keyboard_bounds_and_cleanup():
    import tkinter as tk
    import customtkinter as ctk
    from desktop_select import Select
    root = ctk.CTk()
    root.geometry('600x400+30+30')
    var = tk.StringVar(root, value='Шрифт 9')
    select = Select(root, variable=var, values=[f'Шрифт {i}' for i in range(12)])
    select.place(x=25, y=340, relwidth=.8)
    try:
        root.update()
        select.open_popup()
        root.update()
        assert select.popup is not None
        assert select.popup.winfo_width() == select.winfo_width()
        assert select.popup.winfo_rooty() >= root.winfo_rooty()
        assert select.popup.winfo_rooty()+select.popup.winfo_height() < select.winfo_rooty()
        select.search.set('Шрифт 1')
        assert select.filtered == ['Шрифт 1', 'Шрифт 10', 'Шрифт 11']
        select._move(1)
        select._choose_active()
        assert var.get() == 'Шрифт 10'
        assert root.grab_current() is None
        select.open_popup()
        select.search.set('нет совпадений')
        select._choose_active()
        assert var.get() == 'Шрифт 10'
        select.configure(values=['Новый микрофон'])
        assert select.popup is None
        select.open_popup()
        root.update()
        select.popup.event_generate('<Escape>')
        root.update()
        assert select.popup is None
    finally:
        select.close_popup()
        root.destroy()


def test_real_tone_stream_and_flush():
    model = MODEL_CACHE / TONE_NAME
    if not (model / '0.wav').exists():
        pytest.skip('Optional integration test requires the cached T-one model')
    import numpy as np
    decoder = ToneDecoder(model)
    with wave.open(str(model / '0.wav')) as audio:
        assert audio.getframerate() == 8000
        pcm = np.repeat(np.frombuffer(audio.readframes(audio.getnframes()), dtype=np.int16), 2)
    phrases, partials = [], []
    for offset in range(0, len(pcm), 320):
        final = decoder.AcceptWaveform(pcm[offset:offset+320].tobytes())
        result = json.loads(decoder.Result() if final else decoder.PartialResult())
        (phrases if final else partials).append(result.get('text' if final else 'partial', ''))
    phrases.append(json.loads(decoder.FinalResult()).get('text', ''))
    assert any(partials), 'Must publish text before endpoint detection'
    assert 'бригада' in ' '.join(phrases)
    assert 'жду' in ' '.join(phrases), 'Stopping must flush the final buffered word'
