"""Compare time to fully visible captions against the original Git revision.

Run from the project root: python benchmarks/render.py
Uses headless Chrome and synthetic transcripts, never microphone input.
"""
from pathlib import Path
import json
import statistics
import subprocess
import sys
import threading
import types

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server
from server import SubtitleServer


def main():
    baseline = types.ModuleType('baseline_server')
    baseline.__file__ = str(ROOT / 'server.py')
    sys.modules[baseline.__name__] = baseline
    source = subprocess.check_output(['git', '-c', f'safe.directory={ROOT.as_posix()}',
                                      'show', '65bbf1b:server.py'], cwd=ROOT).decode('utf-8')
    exec(source, baseline.__dict__)
    results = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe', headless=True)
        try:
            for name, factory in [('baseline', baseline.SubtitleServer), ('optimized', SubtitleServer)]:
                server = factory()
                server._config['anim_type'] = 'fade'
                http = make_server('127.0.0.1', 0, server._app, threaded=True)
                threading.Thread(target=http.serve_forever, daemon=True).start()
                page = browser.new_page(viewport={'width': 1920, 'height': 1080})
                try:
                    page.route('https://cdn.socket.io/4.7.5/socket.io.min.js',
                               lambda route: route.fulfill(path=str(ROOT / 'static/socket.io.min.js'), content_type='text/javascript'))
                    page.goto(f'http://127.0.0.1:{http.server_port}')
                    page.wait_for_function('socket.connected')
                    times = []
                    for i in range(8):
                        elapsed = page.evaluate('''i => new Promise(resolve => {
                          const text = 'caption benchmark ' + i;
                          const begin = performance.now();
                          socket.emit('transcript', {text, final:false});
                          function frame() {
                            const el = document.querySelector('.caption') || document.querySelector('#sub');
                            const content = document.querySelector('.caption-text') || el;
                            if (el && content.textContent === text && Number(getComputedStyle(el).opacity) >= .999)
                              resolve(performance.now() - begin);
                            else requestAnimationFrame(frame);
                          }
                          requestAnimationFrame(frame);
                        })''', i)
                        times.append(elapsed)
                        server.emit_clear()
                        page.wait_for_function('(()=>{const el=document.querySelector(".caption") || document.querySelector("#sub");return !el || Number(getComputedStyle(el).opacity)===0})()')
                    results[name] = {'samples': len(times), 'fully_visible_ms_median': round(statistics.median(times), 2),
                                     'fully_visible_ms_max': round(max(times), 2)}
                finally:
                    page.close()
                    http.shutdown()
                    http.server_close()
        finally:
            browser.close()
    output = json.dumps(results, indent=2)
    print(output)
    (ROOT / 'benchmarks/render-results.json').write_text(output, encoding='utf-8')


if __name__ == '__main__':
    main()
