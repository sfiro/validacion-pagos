"""Descarga la última versión del sistema desde GitHub.

Conserva siempre la configuración (.env) y los pagos guardados (datos/).
  python3 actualizar.py               Actualiza mostrando el detalle
  python3 actualizar.py --silencioso  Solo avisa si hubo actualización (lo usa el lanzador)
"""
import io
import json
import shutil
import stat
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

REPO = "sfiro/validacion-pagos"
RAMA = "main"
RAIZ = Path(__file__).resolve().parent
ARCHIVO_VERSION = RAIZ / ".version_instalada"
PROTEGIDOS = {".env", "datos", ".git", ".version_instalada"}
AGENTE = {"User-Agent": "validacion-pagos-actualizador"}


def _get(url: str, timeout: int = 15) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=AGENTE), timeout=timeout) as r:
        return r.read()


def ultima_version() -> tuple[str, str]:
    datos = json.loads(_get(f"https://api.github.com/repos/{REPO}/commits/{RAMA}"))
    return datos["sha"], datos["commit"]["message"].splitlines()[0]


def actualizar_con_git(silencioso: bool) -> None:
    antes = subprocess.run(["git", "rev-parse", "HEAD"], cwd=RAIZ, capture_output=True, text=True).stdout
    r = subprocess.run(["git", "pull", "--ff-only"], cwd=RAIZ, capture_output=True, text=True)
    despues = subprocess.run(["git", "rev-parse", "HEAD"], cwd=RAIZ, capture_output=True, text=True).stdout
    if r.returncode != 0:
        print("No se pudo actualizar con git:\n" + r.stderr.strip())
    elif antes != despues:
        print("✅ Sistema actualizado a la última versión.")
    elif not silencioso:
        print("✅ Ya tienes la última versión.")


def instalar_zip(sha: str) -> int:
    contenido = _get(f"https://codeload.github.com/{REPO}/zip/{sha}", timeout=60)
    copiados = 0
    with zipfile.ZipFile(io.BytesIO(contenido)) as z:
        for info in z.infolist():
            partes = Path(info.filename).parts[1:]  # quitar carpeta "validacion-pagos-<sha>/"
            if not partes or info.is_dir() or partes[0] in PROTEGIDOS or ".." in partes:
                continue
            destino = RAIZ.joinpath(*partes)
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_bytes(z.read(info))
            if destino.suffix in (".command", ".sh"):
                destino.chmod(destino.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            copiados += 1
    return copiados


def main() -> None:
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    silencioso = "--silencioso" in sys.argv

    if (RAIZ / ".git").exists() and shutil.which("git"):
        actualizar_con_git(silencioso)
        return

    if not silencioso:
        print("Buscando actualizaciones…")
    try:
        sha, mensaje = ultima_version()
    except Exception as e:
        print(f"⚠️  No se pudo revisar actualizaciones (¿sin internet?): {e}")
        return

    instalada = ARCHIVO_VERSION.read_text().strip() if ARCHIVO_VERSION.exists() else ""
    if sha == instalada:
        if not silencioso:
            print(f"✅ Ya tienes la última versión ({sha[:7]}).")
        return

    print(f"⬇️  Descargando actualización: {mensaje}")
    try:
        n = instalar_zip(sha)
    except Exception as e:
        print(f"❌ Falló la actualización: {e}. El sistema sigue con la versión anterior.")
        return
    ARCHIVO_VERSION.write_text(sha)
    print(f"✅ Actualizado ({n} archivos). Tu configuración y tus pagos se conservaron.")


if __name__ == "__main__":
    main()
