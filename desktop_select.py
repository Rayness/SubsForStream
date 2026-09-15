"""Themed, searchable select menus contained within the application window."""
import tkinter as tk
import customtkinter as ctk


class Select(ctk.CTkButton):
    def __init__(self, master, variable, values, **kwargs):
        self.variable = variable
        self.values = list(values)
        self.popup = None
        self._root_binding = None
        super().__init__(master, textvariable=variable, command=self.open_popup,
                         height=38, anchor='w', corner_radius=9, border_width=1,
                         fg_color='#0f1520', hover_color='#202b3e', border_color='#34415a',
                         text_color='#edf2fa', font=('Segoe UI', 13), **kwargs)
        self.arrow = ctk.CTkLabel(self, text='⌄', width=30, height=26,
                                 fg_color='#0f1520', text_color='#b5aaff', font=('Segoe UI', 18))
        self.arrow.place(relx=1, rely=.5, x=-7, anchor='e')
        self.arrow.bind('<Button-1>', lambda _: self.open_popup())
        self.bind('<Return>', lambda _: self.open_popup())
        self.bind('<space>', lambda _: self.open_popup())
        self.bind('<Down>', lambda _: self.open_popup())

    def configure(self, **kwargs):
        if 'values' in kwargs:
            self.values = list(kwargs.pop('values'))
            self.close_popup()
        return super().configure(**kwargs)

    def open_popup(self):
        if self.popup:
            self.close_popup()
            return
        owner = self.winfo_toplevel()
        other = getattr(owner, '_active_select', None)
        if other and other is not self:
            other.close_popup()
        owner._active_select = self
        owner.update_idletasks()
        scale = self._get_widget_scaling()
        row_height = round(38 * scale)
        root_top = owner.winfo_rooty() + 8
        root_bottom = owner.winfo_rooty() + owner.winfo_height() - 8
        below = root_bottom - (self.winfo_rooty() + self.winfo_height() + 6)
        above = self.winfo_rooty() - root_top - 6
        searchable = len(self.values) > 7
        wanted = min(len(self.values), 6) * row_height + round((87 if searchable else 20)*scale)
        downward = below >= wanted or below >= above
        height = max(60, min(wanted, below if downward else above))
        width = min(self.winfo_width(), owner.winfo_width()-16)
        x = max(owner.winfo_rootx()+8, min(self.winfo_rootx(), owner.winfo_rootx()+owner.winfo_width()-width-8))
        y = self.winfo_rooty()+self.winfo_height()+6 if downward else self.winfo_rooty()-height-6
        popup = self.popup = tk.Toplevel(owner)
        popup.withdraw()
        popup.overrideredirect(True)
        popup.transient(owner)
        popup.configure(bg='#34415a')
        popup.geometry(f'{width}x{height}+{x}+{y}')
        shell = ctk.CTkFrame(popup, fg_color='#192231', corner_radius=0)
        shell.pack(fill='both', expand=True, padx=1, pady=1)
        self.search = tk.StringVar(master=popup)
        if searchable:
            ctk.CTkLabel(shell, text='Поиск по списку', text_color='#93a1b7', height=18,
                         font=('Segoe UI', 11)).pack(anchor='w', padx=11, pady=(8, 0))
            entry = ctk.CTkEntry(shell, textvariable=self.search, height=34,
                                 fg_color='#0f1520', border_color='#34415a', font=('Segoe UI', 13))
            entry.pack(fill='x', padx=9, pady=(4, 4))
        self.list_frame = ctk.CTkScrollableFrame(shell, fg_color='transparent', corner_radius=0,
                                                scrollbar_button_color='#34415a', scrollbar_button_hover_color='#8175f5')
        self.list_frame.pack(fill='both', expand=True, padx=5, pady=5)
        self.search.trace_add('write', lambda *_: self._render())
        self._render()
        popup.bind('<Escape>', lambda _: self.close_popup())
        popup.bind('<Tab>', lambda _: self.close_popup())
        popup.bind('<Down>', lambda _: self._move(1))
        popup.bind('<Up>', lambda _: self._move(-1))
        popup.bind('<Return>', lambda _: self._choose_active())
        popup.bind('<Button-1>', self._outside, add='+')
        popup.bind('<FocusOut>', lambda _: popup.after_idle(self._check_focus))
        self._root_binding = owner.bind('<Configure>', self._owner_changed, add='+')
        popup.deiconify()
        popup.lift()
        popup.update_idletasks()
        popup.grab_set()
        popup.focus_force()
        (entry if searchable else popup).focus_set()
        self.configure(border_color='#8175f5')

    def _render(self):
        for child in self.list_frame.winfo_children():
            child.destroy()
        term = self.search.get().casefold().strip()
        self.filtered = [value for value in self.values if term in value.casefold()]
        self.active = self.filtered.index(self.variable.get()) if self.variable.get() in self.filtered else 0
        self.rows = []
        for i, value in enumerate(self.filtered):
            button = ctk.CTkButton(self.list_frame, text=('✓   ' if value == self.variable.get() else '     ') + value,
                                   command=lambda v=value: self.choose(v), anchor='w', height=34, corner_radius=7,
                                   fg_color='transparent', hover_color='#303c54', text_color='#edf2fa',
                                   font=('Segoe UI', 13))
            button.pack(fill='x', pady=2)
            self.rows.append(button)
        if not self.filtered:
            ctk.CTkLabel(self.list_frame, text='Ничего не найдено', text_color='#93a1b7').pack(pady=12)
        self._highlight()

    def _highlight(self):
        for i, row in enumerate(self.rows):
            row.configure(fg_color='#363056' if i == self.active else 'transparent')
        self.list_frame.update_idletasks()
        if self.rows:
            canvas = self.list_frame._parent_canvas
            row = self.rows[self.active]
            top, bottom = row.winfo_y(), row.winfo_y()+row.winfo_height()
            visible_top = canvas.canvasy(0)
            if top < visible_top:
                canvas.yview_moveto(top / max(1, self.list_frame.winfo_height()))
            elif bottom > visible_top + canvas.winfo_height():
                canvas.yview_moveto((bottom-canvas.winfo_height()) / max(1, self.list_frame.winfo_height()))

    def _move(self, delta):
        if self.filtered:
            self.active = (self.active + delta) % len(self.filtered)
            self._highlight()
        return 'break'

    def _choose_active(self):
        if self.filtered:
            self.choose(self.filtered[self.active])
        return 'break'

    def choose(self, value):
        if value in self.values:
            self.variable.set(value)
        self.close_popup()
        self.focus_set()

    def _outside(self, event):
        popup = self.popup
        if popup and not (popup.winfo_rootx() <= event.x_root < popup.winfo_rootx()+popup.winfo_width()
                          and popup.winfo_rooty() <= event.y_root < popup.winfo_rooty()+popup.winfo_height()):
            self.close_popup()

    def _check_focus(self):
        if self.popup and self.popup.focus_get() is None:
            self.close_popup()

    def _owner_changed(self, event):
        if event.widget == self.winfo_toplevel():
            self.close_popup()

    def close_popup(self):
        popup, self.popup = self.popup, None
        if popup:
            owner = self.winfo_toplevel()
            if self._root_binding:
                owner.unbind('<Configure>', self._root_binding)
                self._root_binding = None
            if getattr(owner, '_active_select', None) is self:
                owner._active_select = None
            popup.grab_release()
            popup.destroy()
            self.configure(border_color='#34415a')

    def destroy(self):
        self.close_popup()
        super().destroy()
