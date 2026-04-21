# -*- mode: python ; coding: utf-8 -*-


from PyInstaller.utils.hooks import collect_data_files, copy_metadata, collect_submodules

_datas = [('data/templates', 'data/templates'), ('personal_os/locales', 'locales')]
# SECURITY: .env is loaded from ~/.imbuto/.env at runtime — never bundled.
_datas += collect_data_files('litellm')
_datas += collect_data_files('tiktoken')
_datas += copy_metadata('litellm')

hidden_imports = ['onnxruntime-cpu', 'personal_os.api.main', 'tiktoken_ext.openai_public', 'tiktoken_ext', 'regex', 'filelock']
hidden_imports += collect_submodules('chromadb')
hidden_imports += collect_submodules('litellm')

a = Analysis(
    ['run_backend.py'],
    pathex=['personal_os'],
    binaries=[],
    datas=_datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['nvidia', 'cuda'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='imbuto_backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='imbuto_backend',
)
