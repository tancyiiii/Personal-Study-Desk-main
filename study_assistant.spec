# -*- mode: python ; coding: utf-8 -*-

import os
from PyInstaller.utils.hooks import collect_all, copy_metadata


datas = [("prompts.yaml", ".")]
if os.path.exists("assets/icon.png"):
    datas.append(("assets/icon.png", "assets"))
if os.path.exists("assets/icon.ico"):
    datas.append(("assets/icon.ico", "assets"))
binaries = []
hiddenimports = [
    "langchain_community.document_loaders.pdf",
    "langchain_community.document_loaders.text",
    "langchain_community.embeddings.openai",
    "langchain_chroma",
    "duckduckgo_search",
    "groq",
    "openai",
    "pypdf",
]

for package in ("phi", "chromadb"):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

for distribution in (
    "phidata",
    "chromadb",
    "langchain",
    "langchain-community",
    "langchain-chroma",
    "langchain-core",
    "openai",
    "groq",
    "duckduckgo-search",
    "pydantic",
    "PyYAML",
    "python-dotenv",
    "tiktoken",
    "pypdf",
):
    try:
        datas += copy_metadata(distribution)
    except Exception:
        pass

a = Analysis(
    ["main_gui.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="StudyAssistant",
    icon="assets/icon.ico" if os.path.exists("assets/icon.ico") else None,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
