"""
SubtitleServer — Flask + SocketIO сервер.
  /       — OBS Browser Source (overlay)
  /mic    — страница микрофона для Chrome (Web Speech API)
  /admin  — панель управления (открывается в браузере)
"""

import re
import random
import threading
import logging
from typing import Callable, Optional

from flask import Flask, request, jsonify
from flask_socketio import SocketIO

logging.getLogger("werkzeug").setLevel(logging.ERROR)

LANG_CODES = {"ru": "ru-RU", "en": "en-US"}

# ─── Цензура ──────────────────────────────────────────────────────────────────

_CENSOR_SYMBOLS = "!@#$%^&*"

# Список русских нецензурных слов (корни, охватывают словоформы)
_PROFANITY_PATTERNS = re.compile(
    r"\b("
    r"[хx][уy][йeёяию][а-яё]*|[хx][уy][яию]|[хx][уy][её]б[а-яё]*|[хx][уy][её][вw][иыьъ]?[нн]?[аяе]*"
    r"|о[хx][уy][еёяию][а-яё]*"
    r"|[бb][лl][яiy][дд]?[ьъ]?[а-яё]*"
    r"|[пp][иi][зz3][дд][аеёиыьъю]?[а-яё]*"
    r"|[пp][иi][дd][оoаa][рp][а-яё]*"
    r"|[еeё][бb][аеёиыоуьъ]?[нт]?[ьъ]?[а-яё]*|[её][бb][л][а-яё]*"
    r"|[мm][уу][дд][аеёиыьъ]?[кк]?[а-яё]*"
    r"|[сs][уу][кk][аеёиыь]?[а-яё]*"
    r"|[бb][лl][яiy][дд]?[ьъ]?"
    r"|[гg][аоа][вw][нn][аеёиыоуьъ]?[а-яё]*"
    r"|[зz][аa][лl][уy][пp][аеёиы]?[а-яё]*"
    r"|негр[а-яё]*"
    r"|даун[а-яё]*"
    r")\b",
    re.IGNORECASE | re.UNICODE,
)


def _censor(text: str) -> str:
    def replace(m):
        length = max(3, len(m.group()))
        return "".join(random.choices(_CENSOR_SYMBOLS, k=length))
    return _PROFANITY_PATTERNS.sub(replace, text)


# ─── Overlay HTML (OBS Browser Source) ───────────────────────────────────────

_OVERLAY = """\
<!DOCTYPE html><html><head><meta charset="UTF-8">
<style>
:root {{ --bubble-bg: {bubble_bg}; }}
* {{ margin:0; padding:0; box-sizing:border-box }}
body {{
  background: transparent;
  display: flex; align-items: {align_items}; justify-content: center;
  min-height: 100vh; padding: 30px 40px;
  font-family: '{font_family}', 'Segoe UI', Arial, sans-serif;
  overflow: hidden;
}}
#sub {{
  color: {font_color};
  font-size: {font_size}px;
  font-weight: {font_weight};
  font-style: {font_style};
  text-decoration: {text_decoration};
  text-align: {text_align};
  text-shadow: {text_shadow_css};
  max-width: {max_width}%; line-height: 1.4; padding: 12px 24px;
  border-radius: 10px;
  background: {bg_css};
  position: relative;
}}
/* ── Стиль облачко ── */
#sub.bubble {{ border-radius: 24px; }}
#sub.bubble::after {{
  content: '';
  position: absolute;
  bottom: -17px; left: 50%;
  transform: translateX(-50%);
  border: 9px solid transparent;
  border-top: 10px solid var(--bubble-bg);
}}
/* ── Fade (по умолчанию) ── */
body[data-anim="fade"] #sub {{ transition: opacity .6s ease; }}
body[data-anim="fade"] #sub.out {{ opacity: 0; }}
/* ── Slide-left: влетает справа, улетает влево ── */
@keyframes fromRight {{ from {{ transform:translateX(110%); opacity:0 }} to {{ transform:translateX(0); opacity:1 }} }}
@keyframes toLeft    {{ from {{ transform:translateX(0); opacity:1 }} to {{ transform:translateX(-110%); opacity:0 }} }}
/* ── Slide-right: влетает слева, улетает вправо ── */
@keyframes fromLeft  {{ from {{ transform:translateX(-110%); opacity:0 }} to {{ transform:translateX(0); opacity:1 }} }}
@keyframes toRight   {{ from {{ transform:translateX(0); opacity:1 }} to {{ transform:translateX(110%); opacity:0 }} }}
body[data-anim="slide-left"]  #sub.entering {{ animation: fromRight .35s ease forwards }}
body[data-anim="slide-left"]  #sub.out      {{ animation: toLeft    .35s ease forwards }}
body[data-anim="slide-right"] #sub.entering {{ animation: fromLeft  .35s ease forwards }}
body[data-anim="slide-right"] #sub.out      {{ animation: toRight   .35s ease forwards }}
#dbg {{
  position: fixed; top: 6px; left: 8px;
  font-size: 12px; color: #ff5555; font-family: monospace;
  text-shadow: 1px 1px 0 #000; pointer-events: none;
}}
</style></head><body data-anim="{anim_type}">
<div id="dbg">socket: connecting...</div>
<div id="sub" class="{bubble_class}out"></div>
<script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script>
<script>
const el  = document.getElementById('sub');
const dbg = document.getElementById('dbg');
let fadeDelay = {fade_ms}, timer = null;
const socket = io();
socket.on('connect',    () => {{ dbg.style.color='#55ff55'; dbg.textContent='socket: OK'; setTimeout(()=>dbg.remove(),5000); }});
socket.on('disconnect', () => {{ dbg.style.color='#ff5555'; dbg.textContent='socket: DISCONNECTED'; }});
function show(text) {{
  clearTimeout(timer);
  if (!text) {{ hide(); return; }}
  el.classList.remove('out', 'entering');
  void el.offsetWidth;
  el.textContent = text;
  el.classList.add('entering');
  timer = setTimeout(hide, fadeDelay);
}}
function hide() {{
  el.classList.remove('entering');
  void el.offsetWidth;
  el.classList.add('out');
}}
socket.on('subtitle', ({{ text }}) => show(text));
socket.on('settings', d => {{
  if (d.font_size)       el.style.fontSize       = d.font_size + 'px';
  if (d.font_color)      el.style.color          = d.font_color;
  if (d.font_weight)     el.style.fontWeight     = d.font_weight;
  if (d.font_style)      el.style.fontStyle      = d.font_style;
  if (d.text_decoration) el.style.textDecoration = d.text_decoration;
  if (d.font_family)     el.style.fontFamily     = d.font_family;
  if (d.bg_css) {{
    el.style.background = d.bg_css;
    document.documentElement.style.setProperty('--bubble-bg', d.bg_css);
  }}
  if (d.fade_delay)            fadeDelay = d.fade_delay;
  if (d.anim_type)             document.body.setAttribute('data-anim', d.anim_type);
  if ('bubble_style' in d)     el.classList.toggle('bubble', d.bubble_style);
  if (d.text_align)            el.style.textAlign = d.text_align;
  if (d.max_width)             el.style.maxWidth  = d.max_width + '%';
  if (d.position) {{ const m={{top:'flex-start',center:'center',bottom:'flex-end'}}; document.body.style.alignItems = m[d.position]||'flex-end'; }}
  if ('text_shadow' in d)      el.style.textShadow = d.text_shadow ? '2px 2px 0 #000,-2px 2px 0 #000,2px -2px 0 #000,-2px -2px 0 #000,0 4px 8px rgba(0,0,0,.9)' : 'none';
}});
</script></body></html>"""

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

<script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script>
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

// ── Speech Recognition ────────────────────────────────────────────────
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
let rec = null, active = false;

function setStatus(text, state) {{
  statusText.textContent = text;
  dot.className = state || '';
}}

function toggle() {{
  if (active) stopRec(); else startRec();
}}

function startRec() {{
  if (!SR) {{
    setStatus('Нужен Chrome или Edge', 'error');
    return;
  }}
  rec = new SR();
  rec.continuous      = true;
  rec.interimResults  = true;
  rec.lang            = lang;
  rec.maxAlternatives = 1;

  rec.onstart = () => {{
    active = true;
    btn.textContent = '■  Stop'; btn.className = 'stop';
    setStatus('Слушаю...', 'listening');
  }};

  rec.onresult = (e) => {{
    let interim = '', final = '';
    for (let i = e.resultIndex; i < e.results.length; i++) {{
      const t = e.results[i][0].transcript;
      if (e.results[i].isFinal) final += t; else interim += t;
    }}
    if (interim) {{
      partialEl.className = '';
      partialEl.textContent = interim;
      socket.emit('transcript', {{ text: interim, final: false }});
    }}
    if (final) {{
      const f = final.trim();
      partialEl.className = 'final';
      partialEl.textContent = f;
      socket.emit('transcript', {{ text: f, final: true }});
    }}
  }};

  rec.onerror = (e) => {{
    if (e.error === 'no-speech') return;
    if (e.error === 'not-allowed') {{
      setStatus('Нет доступа к микрофону', 'error');
      active = false; return;
    }}
    setStatus('Ошибка: ' + e.error, 'error');
  }};

  rec.onend = () => {{
    if (active) setTimeout(() => {{ if (active) rec.start(); }}, 200);
    else setStatus('Остановлено', '');
  }};

  rec.start();
}}

function stopRec() {{
  active = false;
  if (rec) rec.stop();
  btn.textContent = '▶  Start'; btn.className = '';
  setStatus('Остановлено', '');
  partialEl.textContent = '';
}}

// Авто-старт
startRec();
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
<script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script>
<script>
// ── Socket ──────────────────────────────────────────────────────────────
const socket = io();
socket.on('connect', () => { wsd.className='ws-dot on'; wst.textContent='подключено'; });
socket.on('disconnect', () => { wsd.className='ws-dot err'; wst.textContent='разрыв'; });
socket.on('log', ({text}) => addLog(text));
const wsd = document.getElementById('wsd'), wst = document.getElementById('wst');

// ── Speech recognition ──────────────────────────────────────────────────
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
let rec = null, active = false, lang = 'ru-RU';
const mwrap = document.getElementById('mwrap'), mbtn = document.getElementById('mbtn');
const wave  = document.getElementById('wave'),  mst  = document.getElementById('mst');
const partEl= document.getElementById('partial');

function setMicState(listening) {
  if (listening) {
    mbtn.textContent = '■'; mbtn.className = 'mic-btn stop';
    mwrap.className = 'mic-wrap listening'; wave.className = 'wave listening';
    mst.className = 'mic-status on'; mst.textContent = 'Слушаю...';
  } else {
    mbtn.textContent = '🎤'; mbtn.className = 'mic-btn';
    mwrap.className = 'mic-wrap'; wave.className = 'wave';
    mst.className = 'mic-status'; mst.textContent = 'Нажмите, чтобы начать распознавание';
    partEl.textContent = ''; partEl.className = 'partial';
  }
}
function toggle() { if (active) stopRec(); else startRec(); }
function startRec() {
  if (!SR) { mst.className='mic-status err'; mst.textContent='Нужен Chrome или Edge'; return; }
  rec = new SR();
  rec.continuous = true; rec.interimResults = true; rec.lang = lang; rec.maxAlternatives = 1;
  rec.onstart = () => { active = true; setMicState(true); };
  rec.onresult = (e) => {
    let interim = '', final = '';
    for (let i = e.resultIndex; i < e.results.length; i++) {
      const t = e.results[i][0].transcript;
      if (e.results[i].isFinal) final += t; else interim += t;
    }
    if (interim) { partEl.className='partial'; partEl.textContent=interim; socket.emit('transcript',{text:interim,final:false}); }
    if (final)   { const f=final.trim(); partEl.className='partial final'; partEl.textContent=f; socket.emit('transcript',{text:f,final:true}); }
  };
  rec.onerror = (e) => {
    if (e.error==='no-speech') return;
    if (e.error==='not-allowed') { mst.className='mic-status err'; mst.textContent='Нет доступа к микрофону'; active=false; return; }
    mst.className='mic-status err'; mst.textContent='Ошибка: '+e.error;
  };
  rec.onend = () => { if (active) setTimeout(()=>{ if(active) rec.start(); },200); else setMicState(false); };
  rec.start();
}
function stopRec() { active=false; if(rec) rec.stop(); setMicState(false); }

// ── Log ─────────────────────────────────────────────────────────────────
function escHtml(s) { return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function addLog(text) {
  const log = document.getElementById('log');
  const d = document.createElement('div'); d.className = 'entry';
  const t = new Date().toLocaleTimeString('ru');
  const hi = escHtml(text).replace(/[!@#$%^&*]{2,}/g, m => '<span class="cens">'+m+'</span>');
  d.innerHTML = '<span class="ts">'+t+'</span><span class="ltxt">'+hi+'</span>';
  log.appendChild(d); log.scrollTop = log.scrollHeight;
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
  document.getElementById('obs-url').value = 'http://localhost:'+port;
  document.getElementById('adm-url').value = 'http://localhost:'+port+'/admin';
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
    .then(()=>{ const btn=document.querySelector('.apply'); btn.textContent='✓ Применено'; setTimeout(()=>btn.textContent='Применить настройки',2000); });
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


class SubtitleServer:
    def __init__(
        self,
        on_transcript: Optional[Callable[[str, bool], None]] = None,
        on_save: Optional[Callable[[dict], None]] = None,
    ):
        self._on_transcript = on_transcript
        self._on_save = on_save
        self._app  = Flask(__name__)
        self._sio  = SocketIO(self._app, cors_allowed_origins="*", async_mode="threading")
        self._config: dict = {
            "font_size": 44, "fade_delay": 5, "language": "ru",
            "font_family": "Segoe UI", "font_color": "#ffffff",
            "font_bold": True, "font_italic": False, "font_underline": False,
            "bg_color": "#000000", "bg_opacity": 35,
            "censor": False, "anim_type": "fade", "bubble_style": False,
            "position": "bottom", "text_align": "center", "text_shadow": True, "max_width": 90,
        }
        self._port: Optional[int] = None
        self._setup_routes()

    # ── Публичные методы ───────────────────────────────────────────────────

    def start(self, port: int, config: dict) -> None:
        self._config = config
        self._port   = port
        threading.Thread(
            target=lambda: self._sio.run(
                self._app, host="0.0.0.0", port=port, use_reloader=False,
                allow_unsafe_werkzeug=True
            ),
            daemon=True,
        ).start()

    def emit_text(self, text: str) -> None:
        self._sio.emit("subtitle", {"text": text})

    def emit_clear(self) -> None:
        self._sio.emit("subtitle", {"text": ""})

    def update_config(self, config: dict) -> None:
        self._config = config
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
            cfg = self._config
            bubble_class = "bubble " if cfg.get("bubble_style", False) else ""
            return _OVERLAY.format(
                font_size=cfg["font_size"],
                fade_ms=cfg["fade_delay"] * 1000,
                font_family=cfg.get("font_family", "Segoe UI"),
                font_color=cfg.get("font_color", "#ffffff"),
                font_weight="bold" if cfg.get("font_bold", True) else "normal",
                font_style="italic" if cfg.get("font_italic", False) else "normal",
                text_decoration="underline" if cfg.get("font_underline", False) else "none",
                bg_css=_bg_css(cfg),
                anim_type=cfg.get("anim_type", "fade"),
                bubble_class=bubble_class,
                bubble_bg=_bg_css(cfg),
                align_items={"top": "flex-start", "center": "center", "bottom": "flex-end"}.get(cfg.get("position", "bottom"), "flex-end"),
                text_align=cfg.get("text_align", "center"),
                text_shadow_css="2px 2px 0 #000,-2px 2px 0 #000,2px -2px 0 #000,-2px -2px 0 #000,0 4px 8px rgba(0,0,0,.9)" if cfg.get("text_shadow", True) else "none",
                max_width=cfg.get("max_width", 90),
            )

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
            return jsonify(self._config)

        @self._app.route("/api/config", methods=["POST"])
        def post_config():
            data = request.json or {}
            self._config.update(data)
            self.update_config(self._config)
            if self._on_save:
                self._on_save(self._config)
            return jsonify({"ok": True})

        @self._app.route("/api/clear", methods=["POST"])
        def api_clear():
            self.emit_clear()
            return jsonify({"ok": True})

        @self._sio.on("transcript")
        def handle_transcript(data):
            text  = data.get("text", "").strip()
            final = data.get("final", True)
            if text:
                if self._config.get("censor", False):
                    text = _censor(text)
                self._sio.emit("subtitle", {"text": text})
                if final:
                    self._sio.emit("log", {"text": text})
                if self._on_transcript:
                    self._on_transcript(text, final)
