#!/bin/bash
# Doble clic para abrir el panel de pagos en Mac.
cd "$(dirname "$0")" || exit 1
if ! command -v python3 >/dev/null 2>&1; then
  echo "Falta instalar Python 3. Se abrirá la página de descarga."
  open "https://www.python.org/downloads/"
  read -r -p "Presiona Enter para cerrar..."
  exit 1
fi
python3 actualizar.py --silencioso
python3 main.py --abrir
read -r -p "El panel se detuvo. Presiona Enter para cerrar..."
