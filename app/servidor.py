"""Servidor web del panel para empleados (solo librería estándar)."""
from __future__ import annotations

import hmac
import json
import logging
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .config import Config
from .db import BaseDatos

log = logging.getLogger("servidor")
ESTATICOS = Path(__file__).parent / "static"


def crear_servidor(cfg: Config, db: BaseDatos) -> ThreadingHTTPServer:
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
                return self._json(200, {"requiere_pin": bool(cfg.pin_acceso)})
            if not url.path.startswith("/api/"):
                return self._json(404, {"error": "no encontrado"})
            if not self._autorizado():
                return self._json(401, {"error": "PIN incorrecto"})

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
                    "correo": cfg.gmail_usuario,
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
