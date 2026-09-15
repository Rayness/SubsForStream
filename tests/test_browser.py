"""Real local WebSocket and browser rendering; no microphone permission needed."""
from pathlib import Path
import re
import time
import pytest
from server import SubtitleServer
from settings import DEFAULT_CONFIG

playwright = pytest.importorskip('playwright.sync_api')
CHROME = Path('C:/Program Files/Google/Chrome/Application/chrome.exe')


@pytest.fixture
def browser_server():
    server = SubtitleServer()
    server.start(0, DEFAULT_CONFIG)
    with playwright.sync_playwright() as pw:
        if not CHROME.exists():
            pytest.skip('Chrome is not installed')
        browser = pw.chromium.launch(executable_path=str(CHROME), headless=True)
        yield browser, server
        browser.close()
    server.stop()


def test_browser_delivery_and_live_settings(browser_server):
    browser, server = browser_server
    page = browser.new_page(viewport={'width': 1920, 'height': 1080})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(server.url)
    page.wait_for_function('socket.connected')
    for text in ('привет', 'привет мир', 'привет мир снова'):
        assert server.submit_transcript(text, False)
        page.wait_for_function('(text) => document.querySelector(".caption-text")?.textContent === text', arg=text)
        assert page.locator('.caption-text').evaluate('(el) => getComputedStyle(el).opacity') == '1'
        assert page.locator('.caption-text').evaluate('(el) => getComputedStyle(el).animationName') == 'none'
    page.wait_for_function("fetch('/api/metrics').then(r=>r.json()).then(m=>m.samples>0)")
    server.save_settings({'font_size': 60, 'bg_opacity': 0, 'fade_delay': .2})
    page.wait_for_function('getComputedStyle(document.querySelector(".caption-text")).fontSize === "60px"')
    server.submit_transcript('следующая фраза', False)
    page.wait_for_function('document.querySelectorAll(".caption").length === 0')
    server.emit_clear()
    assert not errors


FAKE_SPEECH = '''
window.instances = [];
window.SpeechRecognition = class {
  constructor() { window.instances.push(this); }
  start() { this.onstart?.(); }
  abort() { this.onend?.(); }
};
'''


def test_browser_speech_lifecycle_and_result_order(browser_server):
    browser, server = browser_server
    page = browser.new_page()
    page.add_init_script(FAKE_SPEECH)
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(server.admin_url)
    page.wait_for_function('socket.connected')
    page.evaluate('speech.start(); speech.start();')
    page.wait_for_function('window.instances.length === 1')
    assert len(page.evaluate('window.instances.map(r=>r.lang)')) == 1
    page.evaluate('''() => {
      window.sent = [];
      const emit = socket.emit.bind(socket);
      socket.emit = (event, ...args) => { if(event==='transcript') window.sent.push(args[0]); return emit(event,...args); };
      const result = (text, final) => Object.assign([{transcript:text}], {isFinal:final});
      window.instances[0].onresult({resultIndex:0, results:[result('первая фраза',true),result('следующая',false)]});
    }''')
    assert page.evaluate('window.sent') == [{'text': 'первая фраза', 'final': True}, {'text': 'следующая', 'final': False}]
    page.evaluate("lang='en-US'; speech.setLanguage();")
    page.wait_for_function('window.instances.length === 2')
    assert page.evaluate('window.instances[1].lang') == 'en-US'
    page.evaluate('speech.stop();')
    assert page.evaluate('speech.rec') is None
    assert not page.evaluate('speech.wanted')
    assert not errors


def test_mic_page_and_no_permission_autostart(browser_server):
    browser, server = browser_server
    page = browser.new_page()
    page.add_init_script(FAKE_SPEECH)
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(server.mic_url)
    page.wait_for_function('socket.connected')
    assert page.evaluate('window.instances.length') == 0
    page.locator('#btn').click()
    page.wait_for_function('window.instances.length === 1')
    assert not errors


@pytest.mark.parametrize('theme', ['classic','dialogue','glass','neon','comic','minimal'])
def test_multiple_speakers_styles_and_independent_updates(browser_server, theme):
    browser, server = browser_server
    server.save_settings({'subtitle_theme': theme, 'fade_delay': 30})
    page = browser.new_page(viewport={'width': 1920, 'height': 1080})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(server.url)
    page.wait_for_function('socket.connected')
    for source, name in [('discord:1', 'Анна'), ('discord:2', 'Макс')]:
        server.register_speaker(source, name)
        server.submit_transcript('Привет! У меня отдельное облачко.', source=source)
    server.submit_transcript('Мой микрофон работает одновременно.')
    page.wait_for_function('document.querySelectorAll(".caption").length === 3')
    assert page.locator('.speaker-name').all_text_contents() == ['Анна', 'Макс', 'Я']
    server.submit_transcript('Анна продолжает говорить.', source='discord:1')
    page.wait_for_function('document.querySelector(".caption-text").textContent === "Анна продолжает говорить."')
    assert page.locator('[data-speaker="discord:2"] .caption-text').inner_text() == 'Привет! У меня отдельное облачко.'
    for box in page.locator('.caption').all():
        bounds = box.bounding_box()
        assert bounds['y'] >= 0 and bounds['y'] + bounds['height'] <= 1080
    server.remove_speaker('discord:1')
    page.wait_for_function('document.querySelectorAll(".caption").length === 2')
    assert not errors


@pytest.mark.parametrize('height', [720, 1080])
def test_eight_long_captions_fit_their_cards(browser_server, height):
    browser, server = browser_server
    server.save_settings({'max_speakers': 8, 'subtitle_theme': 'comic', 'fade_delay': 30})
    page = browser.new_page(viewport={'width': 1920, 'height': height})
    page.goto(server.url)
    page.wait_for_function('socket.connected')
    for i in range(8):
        source = f'discord:{i}'
        server.register_speaker(source, f'Участник {i}')
        server.submit_transcript('Длинная реплика для проверки переполнения. ' * 20, source=source)
    page.wait_for_function('cards.size===8')
    boxes = page.locator('.caption').evaluate_all('''els=>els.map(el=>{
      const box=el.getBoundingClientRect(), text=el.querySelector('.caption-text').getBoundingClientRect();
      return {top:box.top,bottom:box.bottom,textBottom:text.bottom};
    })''')
    for box in boxes:
        assert box['top'] >= 0 and box['bottom'] <= height
        assert box['textBottom'] <= box['bottom']
