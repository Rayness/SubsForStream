# Build with: python -m PyInstaller SubForStream_debug.spec
# A directory build starts without extracting native libraries on each launch.
from PyInstaller.utils.hooks import collect_dynamic_libs, collect_data_files

a = Analysis(
    ['launcher.py'],
    pathex=[],
    binaries=collect_dynamic_libs('vosk') + collect_dynamic_libs('sherpa_onnx'),
    datas=[('icon.png', '.'), ('icon.ico', '.'), ('static', 'static'), ('discord_bridge', 'discord_bridge')] + collect_data_files('customtkinter'),
    hiddenimports=['engineio.async_drivers.threading', 'simple_websocket', 'wsproto'],
    hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=[], noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name='SubForStream_debug', debug=False, strip=False, upx=False,
    console=True, icon='icon.ico',
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='SubForStream_debug')
