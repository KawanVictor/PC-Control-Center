"""Gera os arquivos usados no empacotamento (chamado pelo build.ps1).

* ``assets/app.ico``       — ícone com 7 tamanhos (16 a 256 px), desenhado pelo mesmo código
                             do ícone exibido no app (``pccc.ui.icons.make_app_icon``).
* ``version_info.txt``     — metadados do .EXE (versão, nome) exibidos em Propriedades → Detalhes.
* ``installer_small.bmp``  — imagem do canto do instalador.
Os dois últimos vão para a pasta de trabalho do build (fora do OneDrive).
"""
from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

from pccc import __app_name__, __version__  # noqa: E402

SIZES = (16, 24, 32, 48, 64, 128, 256)


def _png(icon, size: int) -> bytes:
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    icon.pixmap(QSize(size, size)).toImage().save(buf, "PNG")
    buf.close()
    return bytes(data)


def write_ico(path: Path) -> None:
    """ICO com imagens PNG internas (formato aceito desde o Windows Vista)."""
    from pccc.ui.icons import make_app_icon
    icon = make_app_icon()
    images = [(s, _png(icon, s)) for s in SIZES]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, blobs = b"", b""
    for size, png in images:
        dim = 0 if size >= 256 else size          # 0 significa 256 no formato ICO
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(png), offset)
        blobs += png
        offset += len(png)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + entries + blobs)


def write_version_info(path: Path) -> None:
    nums = [int(x) for x in __version__.split(".")[:3]] + [0]
    t = tuple(nums[:4])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"""# Gerado por build_tools/make_assets.py — não edite.
VSVersionInfo(
  ffi=FixedFileInfo(filevers={t}, prodvers={t}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('041604B0', [
      StringStruct('CompanyName', 'PC Control Center'),
      StringStruct('FileDescription', '{__app_name__}'),
      StringStruct('FileVersion', '{__version__}'),
      StringStruct('InternalName', 'PCControlCenter'),
      StringStruct('LegalCopyright', 'Uso pessoal'),
      StringStruct('OriginalFilename', '{__app_name__}.exe'),
      StringStruct('ProductName', '{__app_name__}'),
      StringStruct('ProductVersion', '{__version__}')])]),
    VarFileInfo([VarStruct('Translation', [0x0416, 1200])])
  ]
)
""", encoding="utf-8")


def main() -> int:
    """Uso: make_assets.py <pasta_de_trabalho_do_build>"""
    work = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "build"
    work.mkdir(parents=True, exist_ok=True)
    app = QGuiApplication(sys.argv[:1])  # noqa: F841 — necessário para desenhar
    write_ico(ROOT / "assets" / "app.ico")
    from pccc.ui.icons import make_app_icon
    icon = make_app_icon()
    icon.pixmap(QSize(55, 55)).save(str(work / "installer_small.bmp"))
    write_version_info(work / "version_info.txt")
    print(f"assets/app.ico ({len(SIZES)} tamanhos), version_info.txt v{__version__} em {work}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
