"""Sistema de validación de pagos Bancolombia (QR / llave / transferencia) y Bold.

Uso:
  python3 main.py                      Inicia el panel y la lectura de Gmail
  python3 main.py probar-conexion      Verifica que se puede entrar a Gmail
  python3 main.py probar correo.eml    Muestra cómo se lee un correo (no guarda nada)
  python3 main.py importar correo.eml  Guarda correos .eml en la base de datos (pruebas)
"""
import imaplib
import json
import logging
import socket
import sys
import threading
import webbrowser
from pathlib import Path

from app.config import aplicar_ajustes, cargar_config
from app.correo import Vigilante, procesar_mensaje, revisar_correo
from app.db import BaseDatos
from app.servidor import crear_servidor


def ip_local() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def iniciar(cfg, db, abrir_navegador=False):
    if abrir_navegador:
        threading.Timer(1.5, webbrowser.open, (f"http://localhost:{cfg.puerto}",)).start()
    vigilante = Vigilante(cfg, db)
    vigilante.start()
    if not cfg.correo_configurado:
        print("⚠️  Falta conectar la cuenta de Gmail: hazlo en el panel, desde este computador.")
    servidor = crear_servidor(cfg, db, al_configurar=vigilante.despertar.set)
    print("\nPanel de pagos listo:")
    print(f"  En este computador:      http://localhost:{cfg.puerto}")
    print(f"  Celulares en el WiFi:    http://{ip_local()}:{cfg.puerto}")
    print(f"  Revisando Gmail cada {cfg.segundos_entre_revisiones} s. Ctrl+C para detener.\n")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nDetenido.")


def probar_conexion(cfg, db):
    if not cfg.correo_configurado:
        sys.exit("Falta conectar la cuenta de Gmail. Abre el panel (Iniciar) y configúrala ahí.")
    try:
        n = revisar_correo(cfg, db)
    except imaplib.IMAP4.error as e:
        sys.exit(f"❌ Gmail rechazó el acceso: {e}\n   Usa una contraseña de aplicación (no tu clave normal).")
    print(f"✅ Conexión correcta con {cfg.gmail_usuario}. Pagos nuevos guardados: {n}")


def probar(cfg, archivos, db=None):
    for archivo in archivos:
        resultado = procesar_mensaje(Path(archivo).read_bytes(), cfg, db)
        resultado.pop("texto", None)
        print(f"\n== {archivo}")
        print(json.dumps(resultado, ensure_ascii=False, indent=2))


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    for flujo in (sys.stdout, sys.stderr):  # consola de Windows y tildes/emojis
        try:
            flujo.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    cfg = cargar_config()  # .env es opcional; lo normal es configurar desde el panel
    args = sys.argv[1:]
    abrir = "--abrir" in args
    args = [a for a in args if a != "--abrir"]
    comando = args[0] if args else "iniciar"
    if comando == "probar":
        probar(cfg, args[1:])
        return
    db = BaseDatos(cfg.base_datos)
    aplicar_ajustes(cfg, db.get_ajustes())
    if comando == "iniciar":
        try:
            iniciar(cfg, db, abrir_navegador=abrir)
        except OSError as e:
            sys.exit(f"No se pudo abrir el puerto {cfg.puerto} ({e}). ¿El panel ya está abierto en otra ventana?")
    elif comando == "probar-conexion":
        probar_conexion(cfg, db)
    elif comando == "importar":
        probar(cfg, args[1:], db)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
