#!/bin/bash
# Doble clic para descargar la última versión desde GitHub.
cd "$(dirname "$0")" || exit 1
python3 actualizar.py
read -r -p "Presiona Enter para cerrar..."
