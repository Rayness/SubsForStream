"""
SubtitleServer — Flask + SocketIO сервер.
  /       — OBS Browser Source (overlay)
  /mic    — страница микрофона для Chrome (Web Speech API)
  /admin  — панель управления (открывается в браузере)
"""

import re
import socket
import sys
import time
from collections import deque
from functools import lru_cache
import threading
import logging
from typing import Callable, Optional
from settings import DEFAULT_CONFIG, validate_config
from werkzeug.serving import ThreadedWSGIServer

from flask import Flask, request, jsonify, send_from_directory
from flask_socketio import SocketIO

logging.getLogger("werkzeug").setLevel(logging.ERROR)

LANG_CODES = {"ru": "ru-RU", "en": "en-US"}

# ─── Цензура ──────────────────────────────────────────────────────────────────

from censor import censor as _censor


# ─── Overlay HTML (OBS Browser Source) ───────────────────────────────────────

# ─── Mic HTML (открывается в Chrome) ──────────────────────────────────────────

_MIC = """\
<!DOCTYPE html><html><head><meta charset="UTF-8">
<title>SubForStream — Микрофон</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box }}
body {{
  background: #141414; color: #eee;
  font-family: 'Segoe UI', Arial, sans-serif;
  display: flex; flex-direction: column;
  align-items: center; justify-content: center;
  min-height: 100vh; gap: 20px; padding: 30px;
}}
h2 {{ font-size: 20px; font-weight: 600; color: #aaa }}
#status {{
  display: flex; align-items: center; gap: 8px;
  font-size: 14px; color: #888;
}}
#dot {{
  width: 10px; height: 10px; border-radius: 50%; background: #444;
  transition: background .3s;
}}
#dot.listening {{ background: #55ff55; animation: pulse 1.2s infinite }}
#dot.error     {{ background: #ff5555 }}
@keyframes pulse {{ 0%,100% {{ opacity:1 }} 50% {{ opacity:.3 }} }}
#partial {{
  font-size: 18px; text-align: center; max-width: 640px;
  min-height: 54px; color: #ccc; line-height: 1.5;
}}
#partial.final {{ color: #55ff55 }}
button {{
  padding: 12px 32px; font-size: 15px; font-weight: 600;
  background: #1e5c1e; color: white; border: none;
  border-radius: 8px; cursor: pointer; letter-spacing: .5px;
}}
button:hover {{ background: #266026 }}
button.stop {{ background: #5c1e1e }}
button.stop:hover {{ background: #7a2a2a }}
#ws-status {{ font-size: 12px; color: #555; margin-top: 10px }}
</style></head><body>
<h2>SubForStream</h2>
<div id="status"><div id="dot"></div><span id="status-text">Нажмите Start</span></div>
<button id="btn" onclick="toggle()">▶ &nbsp;Start</button>
<div id="partial"></div>
<div id="ws-status">WebSocket: подключение...</div>

<script src="/static/socket.io.min.js"></script>
<script src="/static/speech.js"></script>
<script>
const dot         = document.getElementById('dot');
const statusText  = document.getElementById('status-text');
const btn         = document.getElementById('btn');
const partialEl   = document.getElementById('partial');
const wsStatus    = document.getElementById('ws-status');

const lang = '{lang_code}';

// ── WebSocket ──────────────────────────────────────────────────────────
const socket = io({{ transports: ['websocket'] }});
socket.on('connect',    () => {{ wsStatus.textContent = 'WebSocket: подключено'; }});
socket.on('disconnect', () => {{ wsStatus.textContent = 'WebSocket: разрыв — переподключение...'; }});

const speech = new LiveSpeech({{
  socket, language: () => lang,
  state: (state, message) => {{
    btn.textContent = state === 'idle' || state === 'error' ? '▶ Start' : '■ Stop';
    btn.className = state === 'listening' ? 'stop' : '';
    setStatus(message, state === 'listening' ? 'listening' : state === 'error' ? 'error' : '');
  }},
  text: (text, final) => {{ partialEl.textContent = text; partialEl.className = final ? 'final' : ''; }}
}});
function setStatus(text, state) {{ statusText.textContent = text; dot.className = state || ''; }}
function toggle() {{ speech.toggle(); }}
</script></body></html>"""


# ─── Admin HTML (панель управления) ──────────────────────────────────────────

_ADMIN = """<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8">
<title>SubForStream</title>
<style>
:root{--bg:#0d0d0d;--sur:#161616;--sur2:#1e1e1e;--brd:#252525;--acc:#3a86ff;--grn:#22c55e;--red:#ef4444;--txt:#e2e2e2;--dim:#888;--muted:#555}
*{margin:0;padding:0;box-sizing:border-box}
body{background:var(--bg);color:var(--txt);font-family:'Segoe UI',system-ui,Arial,sans-serif;height:100vh;display:flex;flex-direction:column;overflow:hidden}
/* ── Header ── */
.hdr{display:flex;align-items:center;gap:12px;padding:11px 18px;background:var(--sur);border-bottom:1px solid var(--brd);flex-shrink:0}
.logo{font-size:15px;font-weight:700;background:linear-gradient(135deg,#3a86ff,#8b5cf6);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.ws-badge{display:flex;align-items:center;gap:5px;font-size:11px;color:var(--muted)}
.ws-dot{width:7px;height:7px;border-radius:50%;background:#333;transition:background .3s}
.ws-dot.on{background:var(--grn)}.ws-dot.err{background:var(--red)}
.hdr-right{margin-left:auto;display:flex;align-items:center;gap:8px}
.url-chip{display:flex;align-items:center;gap:6px;background:var(--sur2);border:1px solid var(--brd);border-radius:8px;padding:5px 10px}
.url-chip span{font-size:10px;color:var(--muted)}
.url-chip input{background:none;border:none;color:var(--dim);font-size:11px;width:155px;outline:none}
.url-chip button{background:none;border:1px solid var(--brd);color:var(--muted);border-radius:5px;padding:2px 8px;font-size:10px;cursor:pointer;transition:all .15s}
.url-chip button:hover{border-color:var(--acc);color:var(--acc)}
.clr-btn{background:#3d1212;border:1px solid #5c1e1e;color:#f87171;border-radius:8px;padding:5px 12px;font-size:12px;cursor:pointer;transition:background .15s;font-weight:600}
.clr-btn:hover{background:#5c1e1e}
/* ── Layout ── */
.main{display:flex;flex:1;overflow:hidden}
/* ── Left ── */
.left{flex:1;display:flex;flex-direction:column;padding:20px;gap:16px;overflow:hidden;min-width:0}
/* ── Mic card ── */
.mic-card{background:var(--sur);border:1px solid var(--brd);border-radius:16px;padding:28px 20px;display:flex;flex-direction:column;align-items:center;gap:14px;flex-shrink:0}
.mic-wrap{position:relative;display:flex;align-items:center;justify-content:center}
.ring{position:absolute;border-radius:50%;border:2px solid var(--grn);opacity:0;inset:-10px}
.ring:nth-child(2){inset:-20px}
.listening .ring{animation:ripple 1.6s ease-out infinite}
.listening .ring:nth-child(2){animation-delay:.5s}
@keyframes ripple{0%{opacity:.5;transform:scale(.8)}100%{opacity:0;transform:scale(1.15)}}
.mic-btn{width:68px;height:68px;border-radius:50%;border:none;background:linear-gradient(145deg,#1a6b2a,#166534);color:#fff;font-size:26px;cursor:pointer;position:relative;z-index:1;transition:transform .15s,box-shadow .15s;box-shadow:0 4px 20px rgba(34,197,94,.18)}
.mic-btn:hover{transform:scale(1.06)}
.mic-btn.stop{background:linear-gradient(145deg,#6b1a1a,#7f1d1d);box-shadow:0 4px 20px rgba(239,68,68,.18)}
.wave{display:flex;align-items:center;gap:3px;height:28px}
.bar{width:3px;border-radius:2px;background:var(--acc);height:5px}
.listening .bar{animation:wv 1s ease-in-out infinite}
.listening .bar:nth-child(1){animation-delay:0s}.listening .bar:nth-child(2){animation-delay:.1s}
.listening .bar:nth-child(3){animation-delay:.2s}.listening .bar:nth-child(4){animation-delay:.3s}
.listening .bar:nth-child(5){animation-delay:.4s}.listening .bar:nth-child(6){animation-delay:.3s}
.listening .bar:nth-child(7){animation-delay:.2s}.listening .bar:nth-child(8){animation-delay:.1s}
.listening .bar:nth-child(9){animation-delay:0s}
@keyframes wv{0%,100%{height:5px}50%{height:24px}}
.mic-status{font-size:12px;color:var(--muted)}.mic-status.on{color:var(--grn)}.mic-status.err{color:var(--red)}
.partial{font-size:19px;color:var(--dim);text-align:center;min-height:50px;line-height:1.5;max-width:640px;transition:color .25s}
.partial.final{color:var(--grn)}
/* ── Log ── */
.log-wrap{flex:1;display:flex;flex-direction:column;gap:6px;overflow:hidden;min-height:0}
.log-lbl{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em}
.log{flex:1;background:var(--sur);border:1px solid var(--brd);border-radius:12px;padding:10px 14px;overflow-y:auto;font-size:12px;font-family:monospace;color:#666}
.log .entry{display:flex;gap:8px;padding:4px 0;border-bottom:1px solid #1a1a1a;animation:fi .25s ease}
@keyframes fi{from{opacity:0;transform:translateY(3px)}to{opacity:1;transform:none}}
.log .ts{color:#3a3a3a;flex-shrink:0}.log .ltxt{color:#999}
.log .cens{color:#fb923c;background:#1c0d00;border-radius:3px;padding:1px 3px;font-weight:700}
/* ── Right ── */
.right{width:292px;display:flex;flex-direction:column;border-left:1px solid var(--brd);background:var(--sur);flex-shrink:0}
.tabs{display:flex;padding:10px 10px 0;gap:2px;border-bottom:1px solid var(--brd)}
.tb{flex:1;background:none;border:none;color:var(--muted);padding:8px 4px;font-size:12px;cursor:pointer;border-bottom:2px solid transparent;margin-bottom:-1px;transition:all .15s}
.tb.on{color:var(--acc);border-bottom-color:var(--acc)}
.tp{display:none;flex-direction:column;gap:10px;padding:14px;flex:1;overflow-y:auto}
.tp.on{display:flex}
.fld{display:flex;flex-direction:column;gap:4px}
.fld>label{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}
select,input[type=number]{background:#111;color:var(--txt);border:1px solid var(--brd);border-radius:8px;padding:7px 10px;font-size:13px;outline:none;width:100%;transition:border-color .15s;cursor:pointer}
select:focus,input[type=number]:focus{border-color:var(--acc)}
.rrow{display:flex;align-items:center;gap:8px}
.rrow input[type=range]{flex:1;accent-color:var(--acc);cursor:pointer}
.rval{font-size:11px;color:var(--dim);width:34px;text-align:right;flex-shrink:0}
.crow{display:flex;align-items:center;gap:10px}
.crow label{font-size:10px;color:var(--muted);flex:1;text-transform:uppercase;letter-spacing:.05em}
input[type=color]{width:34px;height:28px;border:1px solid var(--brd);border-radius:6px;padding:2px;background:#111;cursor:pointer}
.chks{display:flex;flex-wrap:wrap;gap:10px}
.chks label{display:flex;align-items:center;gap:5px;font-size:13px;cursor:pointer}
.chks input[type=checkbox]{accent-color:var(--acc);cursor:pointer}
.seg{display:flex;gap:4px}
.seg button{flex:1;background:#111;border:1px solid var(--brd);color:var(--muted);border-radius:8px;padding:7px 4px;font-size:12px;cursor:pointer;transition:all .15s}
.seg button.on{background:var(--acc);border-color:var(--acc);color:#fff}
.apply{background:linear-gradient(145deg,#1a6b2a,#166534);border:none;color:#fff;border-radius:10px;padding:12px;font-size:13px;font-weight:700;cursor:pointer;margin:10px;margin-top:auto;transition:opacity .15s;letter-spacing:.02em}
.apply:hover{opacity:.85}
::-webkit-scrollbar{width:5px}::-webkit-scrollbar-track{background:transparent}::-webkit-scrollbar-thumb{background:#2a2a2a;border-radius:3px}
</style></head><body>
<div class="hdr">
  <div class="logo">SubForStream</div>
  <div class="ws-badge"><div class="ws-dot" id="wsd"></div><span id="wst">подключение...</span></div>
  <div class="hdr-right">
    <div class="url-chip"><span>OBS</span><input id="obs-url" readonly><button onclick="cp('obs-url')">Копировать</button></div>
    <div class="url-chip"><span>Панель</span><input id="adm-url" readonly><button onclick="cp('adm-url')">Копировать</button></div>
    <button class="clr-btn" onclick="clearSub()">✕ Очистить</button>
  </div>
</div>
<div class="main">
  <div class="left">
    <div class="mic-card">
      <div class="mic-wrap" id="mwrap">
        <div class="ring"></div><div class="ring"></div>
        <button class="mic-btn" id="mbtn" onclick="toggle()">🎤</button>
      </div>
      <div class="wave" id="wave">
        <div class="bar"></div><div class="bar"></div><div class="bar"></div>
        <div class="bar"></div><div class="bar"></div><div class="bar"></div>
        <div class="bar"></div><div class="bar"></div><div class="bar"></div>
      </div>
      <div class="mic-status" id="mst">Нажмите, чтобы начать распознавание</div>
      <div class="partial" id="partial"></div>
    </div>
    <div class="log-wrap">
      <div class="log-lbl">Транскрипции</div>
      <div class="log" id="log"></div>
    </div>
  </div>
  <div class="right">
    <div class="tabs">
      <button class="tb on" onclick="tab(this,'font')">Шрифт</button>
      <button class="tb" onclick="tab(this,'view')">Вид</button>
      <button class="tb" onclick="tab(this,'cfg')">Настройки</button>
    </div>
    <div id="tab-font" class="tp on">
      <div class="fld"><label>Семейство шрифта</label>
        <select id="font_family">
          <option>Segoe UI</option><option>Arial</option><option>Verdana</option>
          <option>Tahoma</option><option>Impact</option><option>Times New Roman</option>
          <option>Georgia</option><option>Courier New</option><option>Comic Sans MS</option>
        </select></div>
      <div class="fld"><label>Размер</label>
        <div class="rrow"><input type="range" id="font_size" min="20" max="80" oninput="upd(this,'fz')"><span class="rval" id="fz">44px</span></div></div>
      <div class="crow"><label>Цвет шрифта</label><input type="color" id="font_color"></div>
      <div class="fld"><label>Начертание</label>
        <div class="chks">
          <label><input type="checkbox" id="font_bold"> Жирный</label>
          <label><input type="checkbox" id="font_italic"> Курсив</label>
          <label><input type="checkbox" id="font_underline"> Подчёрк.</label>
        </div></div>
      <div class="chks"><label><input type="checkbox" id="text_shadow" checked> Тень текста</label></div>
    </div>
    <div id="tab-view" class="tp">
      <div class="crow"><label>Цвет фона</label><input type="color" id="bg_color"></div>
      <div class="fld"><label>Прозрачность фона</label>
        <div class="rrow"><input type="range" id="bg_opacity" min="0" max="100" oninput="upd(this,'bo')"><span class="rval" id="bo">35%</span></div></div>
      <div class="fld"><label>Анимация субтитра</label>
        <div class="seg" id="anim_type">
          <button onclick="seg(this,'anim_type')">none</button>
          <button class="on" onclick="seg(this,'anim_type')">fade</button>
          <button onclick="seg(this,'anim_type')">slide-left</button>
          <button onclick="seg(this,'anim_type')">slide-right</button>
        </div></div>
      <div class="chks"><label><input type="checkbox" id="bubble_style"> Стиль «облачко»</label></div>
      <div class="fld"><label>Положение субтитра</label>
        <div class="seg" id="position">
          <button onclick="seg(this,'position')">top</button>
          <button onclick="seg(this,'position')">center</button>
          <button class="on" onclick="seg(this,'position')">bottom</button>
        </div></div>
      <div class="fld"><label>Выравнивание текста</label>
        <div class="seg" id="text_align">
          <button onclick="seg(this,'text_align')">left</button>
          <button class="on" onclick="seg(this,'text_align')">center</button>
          <button onclick="seg(this,'text_align')">right</button>
        </div></div>
      <div class="fld"><label>Макс. ширина субтитра</label>
        <div class="rrow"><input type="range" id="max_width" min="30" max="100" oninput="upd(this,'mw')"><span class="rval" id="mw">90%</span></div></div>
    </div>
    <div id="tab-cfg" class="tp">
      <div class="fld"><label>Язык распознавания</label>
        <div class="seg" id="language">
          <button class="on" onclick="seg(this,'language')">ru</button>
          <button onclick="seg(this,'language')">en</button>
        </div></div>
      <div class="fld"><label>Автоскрытие субтитра (сек)</label>
        <div class="rrow"><input type="range" id="fade_delay" min="1" max="30" oninput="upd(this,'fd')"><span class="rval" id="fd">5s</span></div></div>
      <div class="chks"><label><input type="checkbox" id="censor"> Цензура</label></div>
      <div class="fld"><label>Порт сервера (требует перезапуск)</label>
        <input type="number" id="port" min="1024" max="65535"></div>
    </div>
    <button class="apply" onclick="applySettings()">Применить настройки</button>
  </div>
</div>
<script src="/static/socket.io.min.js"></script>
<script src="/static/speech.js"></script>
<script>
// ── Socket ──────────────────────────────────────────────────────────────
const socket = io({ transports: ['websocket'], upgrade: false });
socket.on('connect', () => { wsd.className='ws-dot on'; wst.textContent='подключено'; });
socket.on('disconnect', () => { wsd.className='ws-dot err'; wst.textContent='разрыв'; });
socket.on('log', ({text,speaker}) => addLog(speaker ? speaker.name + ': ' + text : text));
const wsd = document.getElementById('wsd'), wst = document.getElementById('wst');

let lang = 'ru-RU';
const mwrap = document.getElementById('mwrap'), mbtn = document.getElementById('mbtn');
const wave = document.getElementById('wave'), mst = document.getElementById('mst');
const partEl = document.getElementById('partial');
const speech = new LiveSpeech({
  socket, language: () => lang,
  state: (state, message) => {
    const listening = state === 'listening';
    mbtn.textContent = state === 'idle' || state === 'error' ? '🎤' : '■';
    mbtn.className = 'mic-btn' + (listening ? ' stop' : '');
    mwrap.className = 'mic-wrap' + (listening ? ' listening' : '');
    wave.className = 'wave' + (listening ? ' listening' : '');
    mst.className = 'mic-status ' + (listening ? 'on' : state === 'error' ? 'err' : '');
    mst.textContent = message;
  },
  text: (text, final) => { partEl.textContent = text; partEl.className = 'partial' + (final ? ' final' : ''); }
});
function toggle() { speech.toggle(); }

// ── Log ─────────────────────────────────────────────────────────────────
function escHtml(s) { return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function addLog(text) {
  const log = document.getElementById('log');
  const d = document.createElement('div'); d.className = 'entry';
  const t = new Date().toLocaleTimeString('ru');
  const hi = escHtml(text).replace(/[!@#$%^&*]{2,}/g, m => '<span class="cens">'+m+'</span>');
  d.innerHTML = '<span class="ts">'+t+'</span><span class="ltxt">'+hi+'</span>';
  log.appendChild(d); while (log.children.length > 200) log.firstElementChild.remove(); log.scrollTop = log.scrollHeight;
}

// ── UI helpers ───────────────────────────────────────────────────────────
function upd(el,vid) { const v=el.value; const s=document.getElementById(vid); s.textContent=(vid==='bo'||vid==='mw')?v+'%':vid==='fd'?v+'s':v+'px'; }
function seg(btn,gid) { document.querySelectorAll('#'+gid+' button').forEach(b=>b.classList.remove('on')); btn.classList.add('on'); }
function tab(btn,id) { document.querySelectorAll('.tb').forEach(b=>b.classList.remove('on')); document.querySelectorAll('.tp').forEach(p=>p.classList.remove('on')); btn.classList.add('on'); document.getElementById('tab-'+id).classList.add('on'); }
function cp(id) { navigator.clipboard.writeText(document.getElementById(id).value); }
function clearSub() { fetch('/api/clear',{method:'POST'}); }
function segVal(gid) { const b=document.querySelector('#'+gid+' button.on'); return b?b.textContent:null; }
function setSegVal(gid,val) { document.querySelectorAll('#'+gid+' button').forEach(b=>b.classList.toggle('on',b.textContent===val)); }

// ── Load config ──────────────────────────────────────────────────────────
fetch('/api/config').then(r=>r.json()).then(cfg=>{
  const port = cfg.port||5000;
  document.getElementById('obs-url').value = window.location.origin;
  document.getElementById('adm-url').value = window.location.origin+'/admin';
  document.getElementById('font_family').value = cfg.font_family||'Segoe UI';
  const fs=document.getElementById('font_size'); fs.value=cfg.font_size||44; document.getElementById('fz').textContent=fs.value+'px';
  document.getElementById('font_color').value    = cfg.font_color||'#ffffff';
  document.getElementById('font_bold').checked    = !!cfg.font_bold;
  document.getElementById('font_italic').checked  = !!cfg.font_italic;
  document.getElementById('font_underline').checked = !!cfg.font_underline;
  document.getElementById('bg_color').value = cfg.bg_color||'#000000';
  const bo=document.getElementById('bg_opacity'); bo.value=cfg.bg_opacity??35; document.getElementById('bo').textContent=bo.value+'%';
  setSegVal('anim_type',cfg.anim_type||'fade');
  document.getElementById('bubble_style').checked = !!cfg.bubble_style;
  setSegVal('position',cfg.position||'bottom');
  setSegVal('text_align',cfg.text_align||'center');
  document.getElementById('text_shadow').checked = cfg.text_shadow!==false;
  const mw=document.getElementById('max_width'); mw.value=cfg.max_width??90; document.getElementById('mw').textContent=mw.value+'%';
  setSegVal('language',cfg.language||'ru');
  lang = cfg.language==='en'?'en-US':'ru-RU';
  const fd=document.getElementById('fade_delay'); fd.value=cfg.fade_delay||5; document.getElementById('fd').textContent=fd.value+'s';
  document.getElementById('censor').checked = !!cfg.censor;
  document.getElementById('port').value = port;
});

// ── Apply settings ───────────────────────────────────────────────────────
function applySettings() {
  const newLang = segVal('language');
  lang = newLang==='en'?'en-US':'ru-RU';
  const data = {
    font_family:    document.getElementById('font_family').value,
    font_size:      +document.getElementById('font_size').value,
    font_color:     document.getElementById('font_color').value,
    font_bold:      document.getElementById('font_bold').checked,
    font_italic:    document.getElementById('font_italic').checked,
    font_underline: document.getElementById('font_underline').checked,
    bg_color:       document.getElementById('bg_color').value,
    bg_opacity:     +document.getElementById('bg_opacity').value,
    anim_type:      segVal('anim_type'),
    bubble_style:   document.getElementById('bubble_style').checked,
    position:       segVal('position'),
    text_align:     segVal('text_align'),
    text_shadow:    document.getElementById('text_shadow').checked,
    max_width:      +document.getElementById('max_width').value,
    language:       newLang,
    fade_delay:     +document.getElementById('fade_delay').value,
    censor:         document.getElementById('censor').checked,
    port:           +document.getElementById('port').value,
  };
  fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)})
    .then(async r=>{ if(!r.ok) throw new Error((await r.json()).error || 'Ошибка сохранения'); speech.setLanguage(); const btn=document.querySelector('.apply'); btn.textContent='✓ Применено'; setTimeout(()=>btn.textContent='Применить настройки',2000); }).catch(e=>{ mst.textContent=e.message; mst.className='mic-status err'; });
}
</script></body></html>"""





# ─── Setup HTML (подключение + инструкция OBS) ───────────────────────────────

_SETUP = """<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8">
<title>SubForStream — Подключение</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0f0f13;color:#e0e0e0;font-family:'Segoe UI',Arial,sans-serif;min-height:100vh;display:flex;flex-direction:column;align-items:center;padding:40px 20px}
h1{font-size:28px;font-weight:700;color:#fff;margin-bottom:6px;letter-spacing:-.5px}
.subtitle{color:#888;font-size:14px;margin-bottom:36px}
.logo{display:flex;align-items:center;gap:12px;margin-bottom:8px}
.logo-icon{width:44px;height:44px;background:#3a86ff;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:22px}
.card{background:#18181f;border:1px solid #2a2a35;border-radius:16px;padding:28px 32px;width:100%;max-width:680px;margin-bottom:20px}
.card h2{font-size:16px;font-weight:600;color:#fff;margin-bottom:20px;display:flex;align-items:center;gap:8px}
.card h2 .icon{font-size:18px}
.url-row{display:flex;flex-direction:column;gap:6px;margin-bottom:16px}
.url-row:last-child{margin-bottom:0}
.url-label{font-size:12px;color:#888;font-weight:500;text-transform:uppercase;letter-spacing:.5px}
.url-box{display:flex;align-items:center;gap:8px}
.url-val{flex:1;background:#0f0f13;border:1px solid #2a2a35;border-radius:8px;padding:10px 14px;font-size:13px;color:#a0c4ff;font-family:monospace;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.copy-btn{background:#2a2a35;border:none;color:#aaa;padding:10px 14px;border-radius:8px;cursor:pointer;font-size:13px;white-space:nowrap;transition:background .15s,color .15s}
.copy-btn:hover{background:#3a86ff;color:#fff}
.copy-btn.ok{background:#22c55e;color:#fff}
.steps{display:flex;flex-direction:column;gap:16px}
.step{display:flex;gap:16px;align-items:flex-start}
.step-num{min-width:32px;height:32px;background:#3a86ff22;border:1px solid #3a86ff66;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:700;color:#3a86ff}
.step-body{flex:1;padding-top:4px}
.step-title{font-size:14px;font-weight:600;color:#fff;margin-bottom:4px}
.step-desc{font-size:13px;color:#888;line-height:1.6}
.step-desc code{background:#0f0f13;border:1px solid #2a2a35;border-radius:4px;padding:1px 6px;color:#a0c4ff;font-family:monospace;font-size:12px}
.port-row{display:flex;align-items:center;gap:12px;margin-top:12px}
.port-input{background:#0f0f13;border:1px solid #2a2a35;border-radius:8px;padding:9px 14px;font-size:14px;color:#fff;width:110px;outline:none;transition:border-color .15s}
.port-input:focus{border-color:#3a86ff}
.port-btn{background:#3a86ff;border:none;color:#fff;padding:9px 20px;border-radius:8px;cursor:pointer;font-size:13px;font-weight:600;transition:background .15s}
.port-btn:hover{background:#2563eb}
.port-note{font-size:12px;color:#666}
.admin-btn{display:inline-flex;align-items:center;gap:8px;background:#3a86ff;color:#fff;text-decoration:none;padding:12px 28px;border-radius:10px;font-size:14px;font-weight:600;margin-top:8px;transition:background .15s;border:none;cursor:pointer}
.admin-btn:hover{background:#2563eb}
.footer{margin-top:12px;display:flex;gap:12px}
</style></head><body>
<div class="logo">
  <div class="logo-icon">🎤</div>
  <div>
    <h1>SubForStream</h1>
    <div class="subtitle">Панель подключения и настройки OBS</div>
  </div>
</div>

<div class="card">
  <h2><span class="icon">🔗</span> Адреса подключения</h2>
  <div class="url-row">
    <div class="url-label">Overlay для OBS Browser Source</div>
    <div class="url-box">
      <div class="url-val" id="obs-url">—</div>
      <button class="copy-btn" onclick="copyUrl('obs-url',this)">Копировать</button>
    </div>
  </div>
  <div class="url-row">
    <div class="url-label">Панель управления</div>
    <div class="url-box">
      <div class="url-val" id="admin-url">—</div>
      <button class="copy-btn" onclick="copyUrl('admin-url',this)">Копировать</button>
    </div>
  </div>
</div>

<div class="card">
  <h2><span class="icon">⚙️</span> Порт сервера</h2>
  <div class="port-row">
    <input class="port-input" type="number" id="port-input" min="1024" max="65535">
    <button class="port-btn" onclick="savePort()">Сохранить</button>
    <div class="port-note">Потребуется перезапуск приложения</div>
  </div>
</div>

<div class="card">
  <h2><span class="icon">📺</span> Инструкция по установке в OBS</h2>
  <div class="steps">
    <div class="step">
      <div class="step-num">1</div>
      <div class="step-body">
        <div class="step-title">Запусти SubForStream</div>
        <div class="step-desc">Убедись что приложение запущено и иконка есть в системном трее.</div>
      </div>
    </div>
    <div class="step">
      <div class="step-num">2</div>
      <div class="step-body">
        <div class="step-title">Открой OBS → Источники → "+"</div>
        <div class="step-desc">Внизу панели "Источники" нажми кнопку <code>+</code> и выбери <code>Браузер</code>.</div>
      </div>
    </div>
    <div class="step">
      <div class="step-num">3</div>
      <div class="step-body">
        <div class="step-title">Вставь URL Overlay</div>
        <div class="step-desc">В поле URL вставь адрес из блока "Overlay для OBS Browser Source" выше.</div>
      </div>
    </div>
    <div class="step">
      <div class="step-num">4</div>
      <div class="step-body">
        <div class="step-title">Установи размеры</div>
        <div class="step-desc">Ширина: <code>1920</code>, Высота: <code>1080</code>. Это должно совпадать с разрешением твоей сцены.</div>
      </div>
    </div>
    <div class="step">
      <div class="step-num">5</div>
      <div class="step-body">
        <div class="step-title">Нажми OK и растяни на весь экран</div>
        <div class="step-desc">Источник появится в сцене. Растяни его чтобы он занимал весь экран сцены (Alt+перетаскивание для обрезки).</div>
      </div>
    </div>
    <div class="step">
      <div class="step-num">6</div>
      <div class="step-body">
        <div class="step-title">Открой панель управления и начни запись речи</div>
        <div class="step-desc">Перейди в панель управления, нажми "Начать" — субтитры появятся в OBS в реальном времени.</div>
      </div>
    </div>
  </div>
</div>

<div class="footer">
  <button class="admin-btn" onclick="window.location='/admin'">🎛 Открыть панель управления</button>
</div>

<script>
const base = window.location.origin;
document.getElementById('obs-url').textContent   = base + '/';
document.getElementById('admin-url').textContent = base + '/admin';

fetch('/api/config').then(r=>r.json()).then(cfg=>{
  document.getElementById('port-input').value = cfg.port || 5000;
});

function copyUrl(id, btn) {
  const text = document.getElementById(id).textContent;
  navigator.clipboard.writeText(text).then(()=>{
    btn.textContent = 'Скопировано!'; btn.classList.add('ok');
    setTimeout(()=>{ btn.textContent='Копировать'; btn.classList.remove('ok'); }, 2000);
  });
}

function savePort() {
  const port = parseInt(document.getElementById('port-input').value);
  if (!port || port < 1024 || port > 65535) return;
  fetch('/api/config', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({port})})
    .then(()=>{ document.querySelector('.port-note').textContent = 'Сохранено. Перезапусти приложение для применения.'; });
}
</script></body></html>"""


def _bg_css(config: dict) -> str:
    """Генерирует CSS значение background из цвета и прозрачности."""
    color = config.get("bg_color", "#000000")
    opacity = config.get("bg_opacity", 35)  # 0-100
    # hex → rgba
    color = color.lstrip("#")
    r, g, b = int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)
    a = round(opacity / 100, 2)
    return f"rgba({r},{g},{b},{a})"


class _ExclusiveServer(ThreadedWSGIServer):
    """На Windows SO_REUSEADDR позволяет нескольким копиям слушать один порт,
    и OBS подключается к случайной (часто старой) копии приложения."""
    allow_reuse_address = sys.platform != 'win32'

    def server_bind(self):
        if sys.platform == 'win32':
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class SubtitleServer:
    def __init__(
        self,
        on_transcript: Optional[Callable[[str, bool], None]] = None,
        on_save: Optional[Callable[[dict], None]] = None,
    ):
        self._on_transcript = on_transcript
        self._on_save = on_save
        self._app  = Flask(__name__)
        self._sio  = SocketIO(self._app, async_mode="threading", async_handlers=False, max_http_buffer_size=16384)
        self._config = DEFAULT_CONFIG.copy()
        self._lock = threading.RLock()
        self._http = None
        self._sequence = 0
        self._probes = {}
        self.render_ms = deque(maxlen=120)
        self._last_text = {}
        self._speakers = {}
        self._captions = {}
        self._on_caption = None
        self._source = None
        self._source_seen = 0.0
        self._port: Optional[int] = None
        self._setup_routes()

    # ── Публичные методы ───────────────────────────────────────────────────

    def start(self, port: int, config: dict) -> None:
        self._config.update(validate_config(config))
        self._port = port
        # Bind synchronously so an occupied port fails before opening the UI.
        self._http = _ExclusiveServer('127.0.0.1', port, self._app)
        self._port = self._http.server_port
        threading.Thread(target=self._http.serve_forever, daemon=True).start()

    def stop(self):
        if self._http:
            self._http.shutdown()
            self._http.server_close()

    @property
    def config(self):
        with self._lock:
            return self._config.copy()

    def save_settings(self, data):
        patch = validate_config(data)
        with self._lock:
            config = {**self._config, **patch}
            if self._on_save:
                self._on_save(config)
            self.update_config(config)
        return config

    def claim_source(self, source):
        with self._lock:
            now = time.monotonic()
            if self._source not in (None, source):
                return False
            self._source, self._source_seen = source, now
            return True

    def release_source(self, source):
        with self._lock:
            if self._source == source:
                self._source = None

    def register_speaker(self, source, name):
        if not isinstance(source, str) or not source.startswith('discord:'):
            raise ValueError('Invalid Discord source')
        with self._lock:
            if source not in self._speakers and len(self._speakers) >= 8:
                return False
            palette = ['#a78bfa', '#34d399', '#fb923c', '#f472b6', '#facc15', '#22d3ee', '#f87171', '#a3e635']
            old = self._speakers.get(source)
            self._speakers[source] = {'id': source, 'name': str(name).strip()[:40] or 'Discord',
                                      'color': old['color'] if old else next((color for color in palette if color not in {item['color'] for item in self._speakers.values()}), palette[0])}
            return True

    def remove_speaker(self, source):
        with self._lock:
            self.emit_clear(source)
            self._speakers.pop(source, None)

    def submit_transcript(self, text, final=False, source='native'):
        if not isinstance(text, str) or type(final) is not bool:
            return False
        text = text.strip()[:4000]
        if not text:
            return False
        with self._lock:
            if source in self._speakers:
                speaker = self._speakers[source]
            else:
                if source.startswith('discord:') or not self.claim_source(source):
                    return False
                speaker = {'id': 'self', 'name': self._config.get('speaker_name', 'Я'), 'color': '#60a5fa'}
            key = speaker['id']
            if self._config.get('censor'):
                text = _censor(text, self._config.get('custom_censor_words', '').replace(',', ' ').split())
            packet = {'text': text, 'speaker': speaker, 'final': final}
            if text != self._last_text.get(key):
                self._sequence += 1
                seq = self._sequence
                probe = seq % 10 == 1
                if probe:
                    self._probes[seq] = time.perf_counter()
                    if len(self._probes) > 120:
                        del self._probes[next(iter(self._probes))]
                packet.update(seq=seq, probe=probe)
                self._sio.emit('subtitle', packet)
                self._last_text[key] = text
                self._captions[key] = (time.monotonic(), packet.copy())
            if final:
                self._sio.emit('log', packet)
                self._last_text.pop(key, None)
            if self._on_transcript:
                self._on_transcript(text, final)
            if self._on_caption:
                self._on_caption(packet)
        return True

    def emit_text(self, text: str) -> None:
        self._sio.emit('subtitle', {'text': text, 'speaker': {'id': 'self', 'name': self._config.get('speaker_name', 'Я'), 'color': '#60a5fa'}})

    def emit_clear(self, source=None) -> None:
        with self._lock:
            if source is None:
                self._last_text.clear()
                self._captions.clear()
                self._sio.emit('subtitle', {'text': '', 'clear': True})
            else:
                self._last_text.pop(source, None)
                self._captions.pop(source, None)
                self._sio.emit('subtitle', {'text': '', 'speaker': {'id': source}})

    def update_config(self, config: dict) -> None:
        self._config.update(config)
        self._sio.emit("settings", {
            "font_size":       config["font_size"],
            "font_color":      config.get("font_color", "#ffffff"),
            "font_weight":     "bold" if config.get("font_bold", True) else "normal",
            "font_style":      "italic" if config.get("font_italic", False) else "normal",
            "text_decoration": "underline" if config.get("font_underline", False) else "none",
            "font_family":     config.get("font_family", "Segoe UI"),
            "bg_css":          _bg_css(config),
            "fade_delay":      config["fade_delay"] * 1000,
            "anim_type":       config.get("anim_type", "fade"),
            "bubble_style":    config.get("bubble_style", False),
            "text_align":      config.get("text_align", "center"),
            "position":        config.get("position", "bottom"),
            "text_shadow":     config.get("text_shadow", True),
            "max_width":       config.get("max_width", 90),
            "subtitle_theme": config.get("subtitle_theme", "classic"),
            "show_speakers": config.get("show_speakers", True),
            "max_speakers": config.get("max_speakers", 6),
            "speaker_name": config.get("speaker_name", "Я"),
        })

    @property
    def url(self) -> str:
        return f"http://localhost:{self._port}" if self._port else ""

    @property
    def mic_url(self) -> str:
        return f"http://localhost:{self._port}/mic" if self._port else ""

    @property
    def admin_url(self) -> str:
        return f"http://localhost:{self._port}/admin" if self._port else ""

    @property
    def setup_url(self) -> str:
        return f"http://localhost:{self._port}/setup" if self._port else ""

    # ── Приватные методы ───────────────────────────────────────────────────

    def _setup_routes(self) -> None:
        @self._app.route("/")
        def overlay():
            return send_from_directory(self._app.static_folder, 'overlay.html')

        @self._sio.on('overlay_ready')
        def overlay_ready():
            with self._lock:
                now = time.monotonic()
                self._sio.emit('config_snapshot', self.config, to=request.sid)
                for seen, packet in self._captions.values():
                    remaining = self._config['fade_delay'] - (now - seen)
                    if remaining > 0:
                        self._sio.emit('subtitle', {**packet, 'probe': False, 'remaining_ms': remaining * 1000}, to=request.sid)

        @self._app.route("/mic")
        def mic():
            lang_code = LANG_CODES.get(self._config.get("language", "ru"), "ru-RU")
            return _MIC.format(lang_code=lang_code)

        @self._app.route("/admin")
        def admin():
            return _ADMIN

        @self._app.route("/setup")
        def setup():
            return _SETUP

        @self._app.route("/api/config", methods=["GET"])
        def get_config():
            return jsonify(self.config)

        @self._app.route("/api/config", methods=["POST"])
        def post_config():
            try:
                self.save_settings(request.get_json())
            except ValueError as exc:
                return jsonify({'error': str(exc)}), 400
            except OSError:
                return jsonify({'error': 'Не удалось сохранить настройки'}), 500
            return jsonify({'ok': True})

        @self._app.route('/api/metrics')
        def metrics():
            values = sorted(self.render_ms)
            return jsonify(samples=len(values),
                           render_ack_p95_ms=values[min(len(values)-1, int(len(values)*0.95))] if values else None)

        @self._app.route("/api/clear", methods=["POST"])
        def api_clear():
            self.emit_clear()
            return jsonify({"ok": True})

        @self._sio.on('claim')
        def claim():
            return {'ok': self.claim_source(request.sid)}

        @self._sio.on('release')
        def release():
            self.release_source(request.sid)

        @self._sio.on('disconnect')
        def disconnect(reason=None):
            self.release_source(request.sid)

        @self._sio.on('rendered')
        def rendered(data):
            if isinstance(data, dict) and type(data.get('seq')) is int:
                with self._lock:
                    start = self._probes.pop(data['seq'], None)
                    if start is not None:
                        self.render_ms.append((time.perf_counter() - start) * 1000)

        @self._sio.on('transcript')
        def handle_transcript(data):
            if isinstance(data, dict):
                self.submit_transcript(data.get('text'), data.get('final', True), source=request.sid)
