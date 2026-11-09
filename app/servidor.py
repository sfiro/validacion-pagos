"""Servidor web del panel para empleados (solo librería estándar)."""
from __future__ import annotations

import hmac
import json
import logging
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .config import Config, aplicar_ajustes
from .correo import probar_credenciales
from .db import BaseDatos

DIRECCIONES_LOCALES = {"127.0.0.1", "::1", "::ffff:127.0.0.1"}
HOSTS_LOCALES = {"localhost", "127.0.0.1", "[::1]"}
RE_CORREO = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

log = logging.getLogger("servidor")
ESTATICOS = Path(__file__).parent / "static"


def crear_servidor(cfg: Config, db: BaseDatos, al_configurar=None) -> ThreadingHTTPServer:
    class Manejador(BaseHTTPRequestHandler):
        server_version = "PagosPanel/1.0"

        def log_message(self, formato, *args):
            log.debug(formato, *args)

        # ---------------------------------------------------------- utilidades
        def _json(self, codigo: int, datos) -> None:
            cuerpo = json.dumps(datos, ensure_ascii=False).encode()
            self.send_response(codigo)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(cuerpo)))
            self.end_headers()
            self.wfile.write(cuerpo)

        def _autorizado(self) -> bool:
            if not cfg.pin_acceso:
                return True
            return hmac.compare_digest(self.headers.get("X-Pin", ""), cfg.pin_acceso)

        def _es_local(self) -> bool:
            """Solo el computador donde corre el sistema puede ver/cambiar la cuenta de Gmail.

            También se revisa el encabezado Host y el tipo de contenido JSON, para que una
            página web abierta en ese computador no pueda cambiar la configuración por detrás.
            """
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0].lower()
            return self.client_address[0] in DIRECCIONES_LOCALES and host in HOSTS_LOCALES

        def _configuracion_publica(self) -> dict:
            return {
                "gmail_usuario": cfg.gmail_usuario,
                "imap_carpeta": cfg.imap_carpeta,
                "tiene_clave": bool(cfg.gmail_clave_app),
                "tiene_pin": bool(cfg.pin_acceso),
            }

        def _guardar_configuracion(self):
            if not self._es_local() or not self.headers.get("Content-Type", "").startswith("application/json"):
                return self._json(403, {"error": "La cuenta solo se puede configurar desde el computador "
                                                 "donde corre el sistema (http://localhost)."})
            datos = self._cuerpo()
            usuario = str(datos.get("gmail_usuario", "")).strip().lower()
            clave = str(datos.get("gmail_clave_app", "")).replace(" ", "").strip() or cfg.gmail_clave_app
            carpeta = str(datos.get("imap_carpeta", "")).strip() or "INBOX"
            pin = str(datos.get("pin_acceso", "")).strip()
            if not RE_CORREO.match(usuario):
                return self._json(400, {"error": "Escribe un correo válido."})
            if not clave:
                return self._json(400, {"error": "Falta la contraseña de aplicación."})
            if pin and not re.fullmatch(r"\d{4,8}", pin):
                return self._json(400, {"error": "El PIN debe tener entre 4 y 8 números."})

            ok, mensaje = probar_credenciales(cfg.imap_servidor, usuario, clave, carpeta)
            if not ok:
                return self._json(400, {"error": mensaje})

            nuevos = {"gmail_usuario": usuario, "gmail_clave_app": clave, "imap_carpeta": carpeta}
            if datos.get("quitar_pin"):
                nuevos["pin_acceso"] = ""
            elif pin:
                nuevos["pin_acceso"] = pin
            db.guardar_ajustes(nuevos)
            aplicar_ajustes(cfg, nuevos)
            db.set_estado("ultimo_error", None)
            log.info("Configuración guardada para %s", usuario)
            if al_configurar:
                al_configurar()
            return self._json(200, {"ok": True, "mensaje": mensaje, "configuracion": self._configuracion_publica()})

        def _cuerpo(self) -> dict:
            largo = min(int(self.headers.get("Content-Length") or 0), 10_000)
            if not largo:
                return {}
            try:
                return json.loads(self.rfile.read(largo))
            except json.JSONDecodeError:
                return {}

        # -------------------------------------------------------------- GET
        def do_GET(self):
            url = urlparse(self.path)
            if url.path in ("/", "/index.html"):
                cuerpo = (ESTATICOS / "index.html").read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(cuerpo)))
                self.end_headers()
                self.wfile.write(cuerpo)
                return
            if url.path == "/api/config":
                return self._json(200, {
                    "requiere_pin": bool(cfg.pin_acceso),
                    "configurado": cfg.correo_configurado,
                    "es_local": self._es_local(),
                })
            if not url.path.startswith("/api/"):
                return self._json(404, {"error": "no encontrado"})
            if not self._autorizado():
                return self._json(401, {"error": "PIN incorrecto"})

            if url.path == "/api/configuracion":
                if not self._es_local():
                    return self._json(403, {"error": "Solo desde el computador donde corre el sistema."})
                return self._json(200, self._configuracion_publica())

            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            if url.path == "/api/pagos":
                pagos = db.listar(
                    busqueda=q.get("q", ""), periodo=q.get("periodo", "hoy"),
                    estado=q.get("estado", ""), fuente=q.get("fuente", ""),
                )
                return self._json(200, {"pagos": pagos})
            if url.path == "/api/estado":
                return self._json(200, {
                    "correo_configurado": cfg.correo_configurado,
                    "correo": cfg.gmail_usuario if self._es_local() else "",
                    "ultima_revision": db.get_estado("ultima_revision"),
                    "ultimo_error": db.get_estado("ultimo_error"),
                    "ultimo_error_en": db.get_estado("ultimo_error_en"),
                    "intervalo": cfg.segundos_entre_revisiones,
                    "resumen": db.resumen_hoy(),
                })
            return self._json(404, {"error": "no encontrado"})

        # ------------------------------------------------------------- POST
        def do_POST(self):
            url = urlparse(self.path)
            if not self._autorizado():
                return self._json(401, {"error": "PIN incorrecto"})
            if url.path == "/api/configuracion":
                return self._guardar_configuracion()
            m = re.fullmatch(r"/api/pagos/(\d+)/(validar|desmarcar)", url.path)
            if not m:
                return self._json(404, {"error": "no encontrado"})
            datos = self._cuerpo()
            empleado = str(datos.get("empleado", "")).strip()[:40]
            if not empleado:
                return self._json(400, {"error": "Falta el nombre del empleado"})
            pago_id, accion = int(m.group(1)), m.group(2)
            if accion == "validar":
                ok, pago = db.validar(pago_id, empleado, str(datos.get("nota", ""))[:200])
            else:
                ok, pago = db.desmarcar(pago_id, empleado)
            if pago is None:
                return self._json(404, {"error": "Pago no encontrado"})
            if not ok:
                return self._json(409, {"error": "El pago cambió de estado", "pago": pago})
            return self._json(200, {"pago": pago})

    return ThreadingHTTPServer(("0.0.0.0", cfg.puerto), Manejador)
