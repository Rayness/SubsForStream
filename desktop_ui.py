"""Native desktop presentation; audio and server work stay in LauncherWindow."""
import tkinter as tk
from tkinter import ttk
import webbrowser
import customtkinter as ctk
from desktop_select import Select

BG, CARD, TEXT, DIM, ACCENT = '#0c1018', '#151c28', '#edf2fa', '#93a1b7', '#8175f5'
EDGE, INPUT, GREEN = '#293347', '#0f1520', '#59d9ad'
DONATION_URL = 'https://boosty.to/rayness'
THEMES = {'Классика': 'classic', 'Диалоговые облачка': 'dialogue', 'Стекло': 'glass', 'Неон': 'neon', 'Комикс': 'comic', 'Минимализм': 'minimal'}
CHOICES = {
    'engine': {'Vosk': 'vosk', 'T-one': 'tone'},
    'language': {'Русский': 'ru', 'English': 'en'},
    'native_model': {'Компактная · small': 'small', 'Полная · large': 'large'},
    'anim_type': {'Без анимации': 'none', 'Плавное исчезновение': 'fade', 'Сдвиг влево': 'slide-left', 'Сдвиг вправо': 'slide-right'},
    'position': {'Сверху': 'top', 'По центру': 'center', 'Снизу': 'bottom'},
    'text_align': {'Слева': 'left', 'По центру': 'center', 'Справа': 'right'},
}


class DesktopUI:
    def _label(self, parent, text='', size=14, color=TEXT, bold=False, **kwargs):
        return ctk.CTkLabel(parent, text=text, text_color=color,
                            font=('Segoe UI', size, 'bold' if bold else 'normal'), **kwargs)

    def _button(self, parent, text, command, primary=False, **kwargs):
        return ctk.CTkButton(parent, text=text, command=command, height=40,
                             corner_radius=10, font=('Segoe UI', 13, 'bold'),
                             fg_color=ACCENT if primary else EDGE,
                             hover_color='#9589ff' if primary else '#35425a',
                             text_color=TEXT, **kwargs)

    def _card(self, parent, title, subtitle=None, **pack):
        outer = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=16, border_width=1, border_color=EDGE)
        outer.pack(fill='x', pady=(0, 16), **pack)
        body = ctk.CTkFrame(outer, fg_color='transparent')
        body.pack(fill='both', expand=True, padx=22, pady=20)
        self._label(body, title, 17, bold=True).pack(anchor='w', pady=(0, 4))
        if subtitle:
            self._label(body, subtitle, 12, DIM, justify='left', wraplength=630).pack(anchor='w', pady=(0, 12))
        return body

    def _style(self):
        style = ttk.Style(self.root)
        style.theme_use('clam')
        style.configure('Treeview', background=CARD, fieldbackground=CARD, foreground=TEXT,
                        borderwidth=0, rowheight=40, font=('Segoe UI', 10))
        style.configure('Treeview.Heading', background=INPUT, foreground=DIM,
                        relief='flat', padding=10, font=('Segoe UI', 10))
        style.map('Treeview', background=[('selected', '#353253')])
        style.map('Treeview.Heading', background=[('active', EDGE)])

    def _build(self):
        self.root.grid_columnconfigure(1, weight=1)
        self.root.grid_rowconfigure(0, weight=1)
        side = ctk.CTkFrame(self.root, width=208, corner_radius=0, fg_color='#101622')
        side.grid(row=0, column=0, sticky='nsew')
        side.grid_propagate(False)
        side.grid_columnconfigure(0, weight=1)
        side.grid_rowconfigure(7, weight=1)
        brand = ctk.CTkFrame(side, fg_color='transparent')
        brand.grid(row=0, column=0, sticky='ew', padx=22, pady=(30, 32))
        self._label(brand, 'S / S', 26, ACCENT, True).pack(anchor='w')
        self._label(brand, 'SubForStream', 19, bold=True).pack(anchor='w', pady=(8, 0))
        self._label(brand, 'Голос становится текстом', 11, DIM).pack(anchor='w')
        self._label(side, 'РАБОЧЕЕ ПРОСТРАНСТВО', 10, DIM, True).grid(row=1, column=0, sticky='w', padx=22, pady=(0, 12))
        titles = [('live', '◉   Микрофон', 'Микрофон', 'Ваш голос — в субтитрах, прямо во время разговора.'),
                  ('discord', '◎   Discord', 'Участники Discord', 'Отдельный голос. Отдельная реплика. Свой цвет.'),
                  ('look', '▧   Оформление', 'Оформление субтитров', 'Подберите стиль, который подходит вашему стриму.'),
                  ('obs', '↗   Подключение OBS', 'Подключение OBS', 'Один источник браузера для всех ваших субтитров.')]
        self.nav_buttons, self.pages = {}, {}
        main = ctk.CTkFrame(self.root, fg_color=BG, corner_radius=0)
        main.grid(row=0, column=1, sticky='nsew')
        header = ctk.CTkFrame(main, fg_color='transparent')
        header.pack(fill='x', padx=28, pady=(26, 20))
        self.page_title = self._label(header, size=28, bold=True)
        self.page_title.pack(anchor='w')
        self.page_subtitle = self._label(header, size=13, color=DIM)
        self.page_subtitle.pack(anchor='w', pady=(3, 0))
        footer = ctk.CTkFrame(main, fg_color='#101622', height=72, corner_radius=0)
        footer.pack(side='bottom', fill='x')
        self._button(footer, 'Сохранить настройки', self._apply, True, width=180).pack(side='right', padx=28, pady=16)
        self.settings_note = tk.StringVar(value='Настройки применяются к субтитрам в OBS')
        self._label(footer, textvariable=self.settings_note, size=12, color=DIM,
                    wraplength=450, justify='left').pack(side='left', padx=28, pady=12)
        self.page_host = ctk.CTkFrame(main, fg_color='transparent')
        self.page_host.pack(fill='both', expand=True, padx=(22, 16))
        self.page_host.grid_columnconfigure(0, weight=1)
        self.page_host.grid_rowconfigure(0, weight=1)
        self.page_info = {}
        for i, (key, nav, title, subtitle) in enumerate(titles):
            button = self._button(side, nav, lambda k=key: self._show_page(k), width=180, anchor='w')
            button.grid(row=i+2, column=0, padx=14, pady=4)
            self.nav_buttons[key] = button
            page = ctk.CTkScrollableFrame(self.page_host, fg_color=BG, corner_radius=0,
                                         scrollbar_button_color=EDGE, scrollbar_button_hover_color=DIM)
            self.pages[key] = page
            self.page_info[key] = (title, subtitle)
        self.mic_badge = self._label(side, '●  Микрофон выключен', 12, DIM)
        self.mic_badge.grid(row=8, column=0, sticky='w', padx=22, pady=5)
        self.discord_badge = self._label(side, '●  Discord отключён', 12, DIM)
        self.discord_badge.grid(row=9, column=0, sticky='w', padx=22, pady=5)
        self.donate_button = self._button(side, '♡  Поддержать проект', lambda: webbrowser.open(DONATION_URL), width=180)
        self.donate_button.configure(fg_color='#332821', hover_color='#4a3528', text_color='#ffc698')
        self.donate_button.grid(row=10, column=0, padx=14, pady=(18, 0))
        self._label(side, 'Локально · Без подписки', 11, DIM).grid(row=11, column=0, sticky='w', padx=22, pady=(12, 20))
        self._build_live(self.pages['live'])
        self._build_discord(self.pages['discord'])
        self._build_settings(self.pages['look'])
        self._build_connect(self.pages['obs'])
        self._show_page('live')

    def _show_page(self, key):
        select = getattr(self.root, '_active_select', None)
        if select:
            select.close_popup()
        for name, page in self.pages.items():
            page.grid_forget()
            self.nav_buttons[name].configure(fg_color='#302c50' if name == key else 'transparent',
                                             text_color='#c7bfff' if name == key else DIM)
        self.pages[key].grid(row=0, column=0, sticky='nsew')
        self.page_title.configure(text=self.page_info[key][0])
        self.page_subtitle.configure(text=self.page_info[key][1])
        self.active_page = key

    def _field(self, parent, row, label, key, values=None, limits=None):
        parent.grid_columnconfigure(1, weight=1)
        self._label(parent, label, 13, DIM).grid(row=row, column=0, sticky='w', padx=(0, 20), pady=8)
        cfg = self.server.config
        value = next((name for name, code in THEMES.items() if code == cfg[key]), 'Классика') if key == 'subtitle_theme' else str(cfg[key])
        if key in CHOICES:
            values = tuple(CHOICES[key])
            value = next(name for name, code in CHOICES[key].items() if code == cfg[key])
        var = tk.StringVar(value=value)
        self.config_vars[key] = var
        if values:
            widget = Select(parent, variable=var, values=values)
        else:
            widget = ctk.CTkEntry(parent, textvariable=var, height=36, fg_color=INPUT, border_color=EDGE, text_color=TEXT)
        widget.grid(row=row, column=1, sticky='ew', pady=8)
        return widget

    def _fields(self, parent):
        fields = ctk.CTkFrame(parent, fg_color='transparent')
        fields.pack(fill='x', pady=(8, 0))
        return fields

    def _build_live(self, page):
        preview = self._card(page, 'Текущая реплика', 'Текст появится здесь, когда вы начнёте говорить')
        self.preview = tk.StringVar(value='Ваш голос. Ваши субтитры.')
        self.preview_label = self._label(preview, textvariable=self.preview, size=26, bold=True,
                                         wraplength=700, justify='left', anchor='w')
        self.preview_label.pack(fill='x', pady=(14, 20))
        preview.bind('<Configure>', lambda e: self.preview_label.configure(wraplength=max(200, e.width-10)))
        action = ctk.CTkFrame(preview, fg_color='transparent')
        action.pack(fill='x')
        self.start_button = self._button(action, '▶ Начать', self._toggle, True, width=160)
        self.start_button.pack(side='left')
        self._button(action, 'Очистить', self._clear, width=110).pack(side='left', padx=10)
        self.status_var = tk.StringVar(value=self.status)
        self._label(preview, textvariable=self.status_var, size=12, color=DIM, wraplength=700,
                    justify='left').pack(anchor='w', pady=(12, 0))
        controls = self._card(page, 'Источник и распознавание')
        fields = self._fields(controls)
        self._label(fields, 'Микрофон', 13, DIM).grid(row=0, column=0, sticky='w', padx=(0, 20), pady=8)
        self.mic_var = tk.StringVar(value='По умолчанию')
        self.mic = Select(fields, variable=self.mic_var, values=list(self.devices))
        self.mic.grid(row=0, column=1, sticky='ew', pady=8)
        self._field(fields, 1, 'Движок', 'engine', ('vosk', 'tone'))
        self._field(fields, 2, 'Язык', 'language', ('ru', 'en'))
        self._field(fields, 3, 'Модель Vosk', 'native_model', ('small', 'large'))
        self._label(controls, 'Vosk small — лёгкий вариант. T-one — для русской речи.\nМодель скачивается один раз; затем распознавание работает локально.',
                    12, DIM, justify='left').pack(anchor='w', pady=(14, 12))
        self._button(controls, 'Открыть распознавание Chrome / Edge ↗', self._browser, width=300).pack(anchor='w')
        diagnostics = self._card(page, 'Активность', 'Показатели обработки и история завершённых реплик')
        self.metrics = tk.StringVar(value='Показатели появятся после запуска')
        self._label(diagnostics, textvariable=self.metrics, size=12, color=DIM, justify='left',
                    wraplength=700).pack(anchor='w', pady=(4, 14))
        self.log = ctk.CTkTextbox(diagnostics, height=140, fg_color=INPUT, text_color=DIM,
                                  font=('Segoe UI', 13), corner_radius=10, wrap='word', state='disabled')
        self.log.pack(fill='x')

    def _build_discord(self, page):
        setup = self._card(page, 'Подключение бота', 'Добавьте бота в голосовой канал своего сервера, затем заполните эти поля.')
        fields = self._fields(setup)
        self._label(fields, 'Токен бота', 13, DIM).grid(row=0, column=0, sticky='w', padx=(0, 20), pady=8)
        self.discord_token = tk.StringVar()
        ctk.CTkEntry(fields, textvariable=self.discord_token, show='•', height=36, fg_color=INPUT,
                      border_color=EDGE).grid(row=0, column=1, sticky='ew', pady=8)
        self._field(fields, 1, 'ID голосового канала', 'discord_channel_id')
        self._field(fields, 2, 'Мой Discord ID', 'discord_ignore_id')
        self._field(fields, 3, 'Лимит участников · 1–8', 'discord_limit', limits=(1, 8, 1))
        self._label(setup, 'Свой ID можно пропустить. Укажите его, чтобы исключить повтор вашего микрофона.\nТокен хранится только до закрытия приложения. Движок выбирается в «Микрофоне».',
                    12, DIM, wraplength=680, justify='left').pack(anchor='w', pady=14)
        buttons = ctk.CTkFrame(setup, fg_color='transparent')
        buttons.pack(fill='x')
        self.discord_button = self._button(buttons, 'Подключить бота', self._toggle_discord, True, width=180)
        self.discord_button.pack(side='left')
        self._button(buttons, 'Создать бота ↗', lambda: webbrowser.open('https://discord.com/developers/applications'),
                      width=150).pack(side='left', padx=10)
        self.discord_status_var = tk.StringVar(value=self.discord_status)
        self._label(setup, textvariable=self.discord_status_var, size=12, color=DIM, wraplength=680,
                    justify='left').pack(anchor='w', pady=(14, 0))
        people = self._card(page, 'Голоса в канале', 'Участники появятся, когда начнут говорить. Их реплики выводятся независимо.')
        self.participant_table = ttk.Treeview(people, columns=('name', 'text', 'drops'), show='headings', height=5)
        for key, label, width in [('name', 'Участник', 130), ('text', 'Последняя реплика', 350), ('drops', 'Пропуски', 85)]:
            self.participant_table.heading(key, text=label)
            self.participant_table.column(key, width=width, minwidth=50)
        self.participant_table.pack(fill='x', pady=(8, 0))

    def _build_settings(self, page):
        gallery = self._card(page, 'Выберите настроение', 'Миниатюры показывают характер стиля. Точный вид проверяйте в OBS.')
        self.config_vars['subtitle_theme'] = tk.StringVar(value=next(name for name, code in THEMES.items()
                                                                     if code == self.server.config['subtitle_theme']))
        tiles = self._fields(gallery)
        self.theme_tiles = {}
        samples = [('Классика', '#0a0d14', TEXT, 3), ('Диалоговые облачка', '#302e50', '#ddd6fe', 16),
                   ('Стекло', '#263649', '#a5d8ee', 12), ('Неон', '#14132b', '#bca5ff', 8),
                   ('Комикс', '#f3d681', '#191d28', 5), ('Минимализм', CARD, TEXT, 0)]
        for i, (name, background, color, radius) in enumerate(samples):
            tiles.grid_columnconfigure(i % 3, weight=1, uniform='theme')
            tile = ctk.CTkFrame(tiles, fg_color=INPUT, corner_radius=12, border_width=2, border_color=EDGE)
            tile.grid(row=i//3, column=i%3, sticky='nsew', padx=5, pady=5)
            sample = ctk.CTkLabel(tile, text='Привет, стрим!', height=55, fg_color=background,
                                  text_color=color, corner_radius=radius, font=('Segoe UI', 15, 'bold'))
            sample.pack(fill='x', padx=13, pady=(15, 8))
            button = self._button(tile, name, lambda n=name: self._select_theme(n), width=100)
            button.configure(fg_color='transparent', font=('Segoe UI', 12))
            button.pack(fill='x', padx=5, pady=(0, 6))
            sample.bind('<Button-1>', lambda _, n=name: self._select_theme(n))
            tile.bind('<Button-1>', lambda _, n=name: self._select_theme(n))
            self.theme_tiles[name] = tile
        self._select_theme(self.config_vars['subtitle_theme'].get())
        self._button(gallery, 'Показать пример в OBS ↗', self._demo, width=220).pack(anchor='w', pady=(14, 0))
        text = self._card(page, 'Текст и цвет')
        fields = self._fields(text)
        self._field(fields, 0, 'Шрифт', 'font_family', ('Segoe UI', 'Arial', 'Verdana', 'Tahoma', 'Impact', 'Times New Roman', 'Georgia', 'Courier New', 'Comic Sans MS'))
        self._field(fields, 1, 'Размер · 12–160 px', 'font_size', limits=(12, 160, 1))
        for row, key, title in [(2, 'font_color', 'Цвет текста'), (3, 'bg_color', 'Цвет фона')]:
            self._field(fields, row, title, key)
            self._button(fields, 'Палитра', lambda k=key: self._color(k), width=85).grid(row=row, column=2, padx=(10, 0))
        self._field(fields, 4, 'Непрозрачность · 0–100 %', 'bg_opacity', limits=(0, 100, 1))
        self._switches(text, [('font_bold', 'Жирный'), ('font_italic', 'Курсив'), ('font_underline', 'Подчёркивание'), ('text_shadow', 'Тень')])
        layout = self._card(page, 'Расположение и участники')
        fields = self._fields(layout)
        for row, label, key, values in [(0, 'Подпись микрофона', 'speaker_name', None),
                                        (1, 'Видимых собеседников · 1–8', 'max_speakers', None),
                                        (2, 'Ширина · 10–100 %', 'max_width', None),
                                        (3, 'Скрывать через · 0.2–60 сек', 'fade_delay', None),
                                        (4, 'Анимация скрытия', 'anim_type', ('none', 'fade', 'slide-left', 'slide-right')),
                                        (5, 'Положение', 'position', ('top', 'center', 'bottom')),
                                        (6, 'Выравнивание', 'text_align', ('left', 'center', 'right'))]:
            self._field(fields, row, label, key, values)
        self._switches(layout, [('bubble_style', 'Облачко'), ('show_speakers', 'Имена участников')])
        censor = self._card(page, 'Фильтр слов', 'Основной словарь уже включает ругательства и их словоформы.')
        self._switches(censor, [('censor', 'Цензурировать текст')])
        self._field(self._fields(censor), 0, 'Ваши дополнительные слова', 'custom_censor_words')
        self._label(censor, 'Перечислите через запятую. Собственные словоформы добавляйте отдельно.', 12, DIM,
                    wraplength=680).pack(anchor='w', pady=(10, 0))

    def _select_theme(self, name):
        self.config_vars['subtitle_theme'].set(name)
        for title, tile in self.theme_tiles.items():
            tile.configure(border_color=ACCENT if title == name else EDGE)

    def _switches(self, parent, entries):
        frame = self._fields(parent)
        for i, (key, title) in enumerate(entries):
            var = tk.BooleanVar(value=self.server.config[key])
            self.config_vars[key] = var
            ctk.CTkSwitch(frame, text=title, variable=var, progress_color=ACCENT, fg_color=EDGE,
                           button_color=TEXT, font=('Segoe UI', 13)).grid(row=i//2, column=i%2, sticky='w', padx=(0, 35), pady=10)

    def _build_connect(self, page):
        source = self._card(page, 'Адрес вашего оверлея', 'Вставьте его в источник «Браузер» в OBS Studio.')
        self.obs_url = tk.StringVar(value=self.server.url)
        ctk.CTkEntry(source, textvariable=self.obs_url, state='readonly', height=50,
                      fg_color=INPUT, border_color=EDGE, font=('Consolas', 19)).pack(fill='x', pady=(8, 14))
        self.copy_button = self._button(source, 'Копировать адрес', self._copy_obs, True, width=180)
        self.copy_button.pack(anchor='w')
        steps = self._card(page, 'Три шага до эфира')
        for number, title, detail in [('01', 'Добавьте источник', 'OBS → Источники → «+» → Браузер.'),
                                      ('02', 'Настройте сцену', 'Вставьте адрес. Размер источника — например, 1920 × 1080.'),
                                      ('03', 'Включите голос', 'Запустите микрофон или подключите Discord в приложении.')]:
            row = ctk.CTkFrame(steps, fg_color='transparent')
            row.pack(fill='x', pady=12)
            self._label(row, number, 22, ACCENT, True, width=48).pack(side='left', padx=(0, 14))
            words = ctk.CTkFrame(row, fg_color='transparent')
            words.pack(side='left', fill='x', expand=True)
            self._label(words, title, 14, bold=True).pack(anchor='w')
            self._label(words, detail, 12, DIM, wraplength=620, justify='left').pack(anchor='w')
        advanced = self._card(page, 'Параметры подключения')
        self._field(self._fields(advanced), 0, 'Порт после перезапуска', 'port', limits=(1024, 65535, 1))
        self._label(advanced, 'Закрытие окна сворачивает приложение в трей.\nЧтобы завершить работу, выберите «Выход» в меню значка.',
                    12, DIM, justify='left').pack(anchor='w', pady=(14, 0))

    def _copy_obs(self):
        self._copy(self.server.url)
        self.copy_button.configure(text='Адрес скопирован ✓')
        self.root.after(1800, lambda: self.copy_button.configure(text='Копировать адрес') if not self.closed else None)
