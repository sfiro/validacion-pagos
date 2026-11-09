"""Lectura de Gmail por IMAP y verificación de que el correo es auténtico."""
from __future__ import annotations

import email
import hashlib
import imaplib
import logging
import re
import threading
import time
from datetime import timedelta
from email import policy
from email.message import EmailMessage
from email.utils import parseaddr, parsedate_to_datetime

from . import parsers
from .config import Config
from .db import BaseDatos
from .tiempo import COLOMBIA, ahora

log = logging.getLogger("correo")


# ------------------------------------------------------------ autenticidad

def _dominio_coincide(dominio: str, permitidos: list[str]) -> bool:
    dominio = dominio.lower().strip()
    return any(dominio == p or dominio.endswith("." + p) for p in permitidos)


def identificar_fuente(remitente: str, cfg: Config) -> str | None:
    dominio = parseaddr(remitente)[1].rsplit("@", 1)[-1]
    if _dominio_coincide(dominio, cfg.dominios_bancolombia):
        return "bancolombia"
    if _dominio_coincide(dominio, cfg.dominios_bold):
        return "bold"
    return None


def verificar_autenticidad(msg: EmailMessage, cfg: Config) -> tuple[bool, str]:
    """Revisa el encabezado que Gmail agrega (Authentication-Results: mx.google.com).

    Un estafador puede escribir 'bancolombia.com.co' como remitente, pero no puede
    firmar con DKIM del banco ni pasar DMARC. Solo confiamos en el encabezado que
    agregó el servidor de Gmail (el primero que empieza por mx.google.com).
    """
    remitente = parseaddr(msg.get("From", ""))[1].lower()
    dominio = remitente.rsplit("@", 1)[-1]
    permitidos = cfg.dominios_bancolombia + cfg.dominios_bold

    resultados = [str(h) for h in msg.get_all("Authentication-Results", [])]
    de_google = next((r for r in resultados if r.strip().lower().startswith("mx.google.com")), None)
    if not de_google:
        return False, "sin verificación de Gmail"
    r = de_google.lower()

    dmarc = re.search(r"dmarc=pass[^;]*header\.from=([a-z0-9.-]+)", r)
    if dmarc and _dominio_coincide(dmarc.group(1), permitidos) and _dominio_coincide(dominio, [dmarc.group(1)]):
        return True, "dmarc=pass"
    for dkim in re.finditer(r"dkim=pass[^;]*?header\.(?:i=@?|d=)([a-z0-9.-]+)", r):
        firmante = dkim.group(1)
        if _dominio_coincide(firmante, permitidos) and (
            _dominio_coincide(dominio, [firmante]) or _dominio_coincide(firmante, [dominio])
        ):
            return True, "dkim=pass"
    return False, "firma DKIM/DMARC no válida"


# ------------------------------------------------------------ procesamiento

def texto_del_mensaje(msg: EmailMessage) -> str:
    plano = html = ""
    parte = msg.get_body(preferencelist=("plain",))
    if parte is not None:
        plano = parsers.limpiar_espacios(parte.get_content())
    parte = msg.get_body(preferencelist=("html",))
    if parte is not None:
        html = parsers.html_a_texto(parte.get_content())
    # Los bancos suelen poner basura en la parte de texto plano; preferimos la que tenga el valor
    for candidato in (html, plano):
        if "$" in candidato or "COP" in candidato:
            return candidato
    return html or plano


def _fecha_recibido(msg: EmailMessage) -> str:
    try:
        return parsedate_to_datetime(msg["Date"]).astimezone(COLOMBIA).isoformat()
    except Exception:
        return ahora().isoformat()


def procesar_mensaje(crudo: bytes, cfg: Config, db: BaseDatos | None = None) -> dict:
    """Lee un correo. Devuelve un dict con el resultado; si hay db, lo guarda."""
    msg: EmailMessage = email.message_from_bytes(crudo, policy=policy.default)
    remitente = str(msg.get("From", ""))
    asunto = str(msg.get("Subject", ""))
    message_id = str(msg.get("Message-ID", "")).strip() or "sha1:" + hashlib.sha1(crudo).hexdigest()

    fuente = identificar_fuente(remitente, cfg)
    if not fuente:
        return {"accion": "ignorado", "motivo": "remitente no es Bancolombia ni Bold", "remitente": remitente}
    if db is not None and db.existe(message_id):
        return {"accion": "duplicado", "message_id": message_id}

    autentico, motivo_auth = verificar_autenticidad(msg, cfg)
    texto = texto_del_mensaje(msg)
    pago = parsers.leer(fuente, asunto, texto)
    if pago is None:
        return {"accion": "ignorado", "motivo": "no es un pago recibido", "asunto": asunto}

    estado = pago.estado
    if not autentico and cfg.requerir_autenticacion:
        estado = "sospechoso"

    datos = {
        "message_id": message_id,
        "fuente": pago.fuente,
        "metodo": pago.metodo,
        "monto_centavos": pago.monto_centavos,
        "pagador": pago.pagador,
        "cuenta": pago.cuenta,
        "referencia": pago.referencia,
        "fecha_texto": pago.fecha_texto,
        "recibido_en": _fecha_recibido(msg),
        "asunto": asunto,
        "remitente": remitente,
        "autenticado": 1 if autentico else 0,
        "estado": estado,
        "nota": None if autentico else motivo_auth,
        "texto": texto[:4000],
    }
    if db is not None:
        datos["id"] = db.insertar(datos)
    return {"accion": "guardado", "autenticidad": motivo_auth, **datos}


# ---------------------------------------------------------------- IMAP

def _criterio_remitentes(cfg: Config) -> list[str]:
    dominios = cfg.dominios_bancolombia + cfg.dominios_bold
    criterio = [f'FROM "{dominios[-1]}"']
    for d in reversed(dominios[:-1]):
        criterio = [f'OR FROM "{d}"'] + criterio
    return [" ".join(criterio)]


def revisar_correo(cfg: Config, db: BaseDatos) -> int:
    """Descarga los correos nuevos de Bancolombia/Bold. Devuelve cuántos pagos guardó."""
    guardados = 0
    with imaplib.IMAP4_SSL(cfg.imap_servidor) as imap:
        imap.login(cfg.gmail_usuario, cfg.gmail_clave_app)
        tipo, _ = imap.select(f'"{cfg.imap_carpeta}"', readonly=True)  # readonly: no marca como leído
        if tipo != "OK":
            raise RuntimeError(f"No se pudo abrir la carpeta {cfg.imap_carpeta}")
        uidvalidity = (imap.untagged_responses.get("UIDVALIDITY") or [b"0"])[0].decode()
        clave = f"ultimo_uid:{cfg.imap_carpeta}:{uidvalidity}"
        ultimo = int(db.get_estado(clave) or 0)

        if ultimo:
            rango = f"UID {ultimo + 1}:*"
        else:
            desde = (ahora() - timedelta(days=cfg.dias_iniciales)).strftime("%d-%b-%Y")
            rango = f"SINCE {desde}"
        tipo, datos = imap.uid("SEARCH", None, rango, *_criterio_remitentes(cfg))
        uids = [int(u) for u in (datos[0] or b"").split() if int(u) > ultimo]

        for uid in sorted(uids):
            tipo, partes = imap.uid("FETCH", str(uid), "(BODY.PEEK[])")
            crudo = next((p[1] for p in partes if isinstance(p, tuple)), None)
            if crudo:
                try:
                    r = procesar_mensaje(crudo, cfg, db)
                    if r["accion"] == "guardado":
                        guardados += 1
                        log.info("Pago %s %s %s", r["fuente"], r["monto_centavos"], r["estado"])
                except Exception:
                    log.exception("Error leyendo el correo UID %s", uid)
            db.set_estado(clave, str(uid))
        if not uids and not ultimo:
            # Primera vez sin correos: arrancar desde el último UID de la carpeta
            tipo, datos = imap.uid("SEARCH", None, "ALL")
            todos = (datos[0] or b"").split()
            if todos:
                db.set_estado(clave, todos[-1].decode())
    return guardados


class Vigilante(threading.Thread):
    """Revisa el correo cada N segundos en segundo plano."""

    def __init__(self, cfg: Config, db: BaseDatos):
        super().__init__(daemon=True, name="vigilante-correo")
        self.cfg, self.db = cfg, db

    def run(self):
        while True:
            try:
                n = revisar_correo(self.cfg, self.db)
                self.db.set_estado("ultima_revision", ahora().isoformat())
                self.db.set_estado("ultimo_error", None)
                if n:
                    log.info("%d pago(s) nuevo(s)", n)
            except imaplib.IMAP4.error as e:
                self._error(f"Gmail rechazó el acceso: {e}. Revisa usuario y contraseña de aplicación.")
            except Exception as e:
                self._error(f"{type(e).__name__}: {e}")
            time.sleep(self.cfg.segundos_entre_revisiones)

    def _error(self, mensaje: str):
        log.error(mensaje)
        self.db.set_estado("ultimo_error", mensaje)
        self.db.set_estado("ultimo_error_en", ahora().isoformat())
