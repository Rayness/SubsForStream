"""Shared, validated settings and atomic persistence."""
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile

BASE_DIR = Path(sys.executable).parent if getattr(sys, 'frozen', False) or '__compiled__' in globals() else Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / 'config.json'
DEFAULT_CONFIG = {
    'language': 'ru', 'port': 5000, 'font_size': 44, 'fade_delay': 5,
    'font_family': 'Segoe UI', 'font_color': '#ffffff', 'font_bold': True,
    'font_italic': False, 'font_underline': False, 'bg_color': '#000000',
    'bg_opacity': 35, 'censor': False, 'anim_type': 'none', 'bubble_style': False,
    'position': 'bottom', 'text_align': 'center', 'text_shadow': True,
    'max_width': 90, 'native_model': 'small', 'mic_index': None, 'engine': 'vosk',
    'subtitle_theme': 'classic', 'show_speakers': True, 'speaker_name': 'Я',
    'custom_censor_words': '', 'max_speakers': 6,
    'discord_channel_id': '', 'discord_ignore_id': '', 'discord_limit': 6,
}
CHOICES = {
    'language': ('ru', 'en'), 'anim_type': ('none', 'fade', 'slide-left', 'slide-right'),
    'position': ('top', 'center', 'bottom'), 'text_align': ('left', 'center', 'right'),
    'native_model': ('small', 'large'),
    'engine': ('vosk', 'tone'),
    'subtitle_theme': ('classic', 'dialogue', 'glass', 'neon', 'comic', 'minimal'),
}
RANGES = {'port': (1024, 65535), 'font_size': (12, 160), 'fade_delay': (0.2, 60),
          'bg_opacity': (0, 100), 'max_width': (10, 100), 'max_speakers': (1, 8), 'discord_limit': (1, 8)}


def validate_config(data):
    if not isinstance(data, dict):
        raise ValueError('Настройки должны быть объектом')
    result = {}
    for key, value in data.items():
        if key not in DEFAULT_CONFIG:
            continue
        if key in CHOICES:
            valid = isinstance(value, str) and value in CHOICES[key]
        elif key in RANGES:
            lo, hi = RANGES[key]
            valid = type(value) in (int, float) and math.isfinite(value) and lo <= value <= hi
            if key in ('port', 'max_speakers', 'discord_limit'):
                valid = valid and type(value) is int
        elif key in ('font_color', 'bg_color'):
            valid = isinstance(value, str) and re.fullmatch(r'#[0-9a-fA-F]{6}', value)
        elif key == 'font_family':
            valid = isinstance(value, str) and 0 < len(value) <= 80 and re.fullmatch(r'[\w \-]+', value)
        elif key == 'mic_index':
            valid = value is None or (type(value) is int and value >= 0)
        elif key == 'speaker_name':
            valid = isinstance(value, str) and 0 < len(value.strip()) <= 40 and not any(ord(c) < 32 for c in value)
        elif key in ('discord_channel_id', 'discord_ignore_id'):
            valid = isinstance(value, str) and (not value or re.fullmatch(r'\d{15,22}', value))
        elif key == 'custom_censor_words':
            valid = isinstance(value, str) and len(value) <= 4000
        else:
            valid = type(value) is bool
        if not valid:
            raise ValueError(f'Некорректное значение: {key}')
        result[key] = value
    return result


def load_config():
    config = DEFAULT_CONFIG.copy()
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding='utf-8'))
        if isinstance(data, dict):
            for key, value in data.items():
                try:
                    config.update(validate_config({key: value}))
                except ValueError:
                    pass
    except (OSError, ValueError):
        pass
    return config


def save_config(config):
    data = {**DEFAULT_CONFIG, **validate_config(config)}
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=CONFIG_FILE.parent,
                                         prefix='.config-', suffix='.tmp', delete=False) as stream:
            name = stream.name
            json.dump(data, stream, ensure_ascii=False, indent=2)
        os.replace(name, CONFIG_FILE)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)
