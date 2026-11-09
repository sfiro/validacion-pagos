"""Lectura del texto de los correos de Bancolombia y Bold.

Los formatos de los correos cambian con el tiempo, por eso los lectores son
tolerantes: buscan palabras clave y patrones en lugar de una plantilla fija.
Si un correo de un remitente confiable no se puede leer, se guarda igual con
estado "revisar" para que nadie pierda un pago.
"""
from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass
from html.parser import HTMLParser


@dataclass
class Pago:
    fuente: str                 # "bancolombia" | "bold"
    metodo: str                 # QR, Llave, Transferencia, Datáfono, Link de pago...
    monto_centavos: int | None
    pagador: str | None = None
    cuenta: str | None = None   # últimos dígitos de cuenta o tarjeta
    referencia: str | None = None
    fecha_texto: str | None = None
    estado: str = "pendiente"   # pendiente | rechazado | revisar


# ---------------------------------------------------------------- utilidades

def sin_tildes(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))


def normalizar(texto: str) -> str:
    return sin_tildes(texto).lower()


class _HtmlATexto(HTMLParser):
    BLOQUES = {"p", "div", "br", "tr", "td", "th", "li", "h1", "h2", "h3", "h4", "table", "span"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.partes: list[str] = []
        self._ignorar = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head"):
            self._ignorar += 1
        elif tag in self.BLOQUES:
            self.partes.append(" ")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head") and self._ignorar:
            self._ignorar -= 1
        elif tag in self.BLOQUES:
            self.partes.append(" ")

    def handle_data(self, data):
        if not self._ignorar:
            self.partes.append(data)


def html_a_texto(contenido: str) -> str:
    p = _HtmlATexto()
    p.feed(contenido)
    return limpiar_espacios(html.unescape("".join(p.partes)))


def limpiar_espacios(texto: str) -> str:
    return re.sub(r"\s+", " ", texto.replace("\xa0", " ")).strip()


def parse_monto(valor: str) -> int | None:
    """Convierte '$50.000', '$50,000.00', '1.250.000,50' a centavos."""
    s = re.sub(r"[^\d.,]", "", valor).strip(".,")
    if not s or not re.search(r"\d", s):
        return None
    m = re.search(r"[.,](\d{1,2})$", s)
    if m:
        entero, decimales = s[: m.start()], m.group(1).ljust(2, "0")
    else:
        entero, decimales = s, "00"
    entero = re.sub(r"[.,]", "", entero) or "0"
    return int(entero) * 100 + int(decimales)


_RE_MONTO = re.compile(r"(?:\$|COP)\s?(\d[\d.,]*\d|\d)", re.IGNORECASE)
_PALABRAS_NO_MONTO = ("saldo", "comision", "retencion", "iva", "4x1000", "gmf", "neto", "cupo", "disponible")
_PALABRAS_MONTO = ("monto", "valor", "total", "por", "recibiste", "pago de", "venta")


def elegir_monto(texto: str) -> int | None:
    """Toma el valor del pago ignorando saldos, comisiones o retenciones."""
    candidatos = []
    fin_anterior = 0
    for m in _RE_MONTO.finditer(texto):
        # contexto: hasta 40 caracteres antes, sin cruzar el monto anterior
        contexto = normalizar(texto[max(fin_anterior, m.start() - 40): m.start()])
        fin_anterior = m.end()
        contexto = re.split(r"\.\s|\|", contexto)[-1]  # solo la última frase antes del valor
        if any(p in contexto for p in _PALABRAS_NO_MONTO):
            continue
        prioridad = 0 if any(p in contexto for p in _PALABRAS_MONTO) else 1
        candidatos.append((prioridad, m.start(), parse_monto(m.group(1))))
    candidatos = [c for c in candidatos if c[2]]
    if not candidatos:
        return None
    return min(candidatos)[2]


_ETIQUETAS = (
    "remitente", "pagador", "nombre del pagador", "origen", "cliente", "comercio",
    "monto", "valor", "fecha", "hora", "referencia", "cuenta", "tarjeta", "metodo de pago",
    "medio de pago", "estado", "id de la transaccion", "id transaccion", "numero de aprobacion",
    "codigo de aprobacion", "franquicia", "dispositivo", "llave", "banco",
)


def valor_etiqueta(texto: str, etiquetas: tuple[str, ...]) -> str | None:
    """Busca 'Etiqueta: valor' y devuelve el valor hasta la siguiente etiqueta conocida."""
    norm = normalizar(texto)
    for etiqueta in etiquetas:
        m = re.search(r"\b" + re.escape(etiqueta) + r"\s*:?\s+", norm)
        if not m:
            continue
        inicio = m.end()
        resto = norm[inicio: inicio + 80]
        corte = len(resto)
        for otra in _ETIQUETAS:
            mm = re.search(r"\s" + re.escape(otra) + r"\s*:", resto)
            if mm and mm.start() < corte:
                corte = mm.start()
        valor = texto[inicio: inicio + corte].strip(" :.-")
        if valor:
            return valor
    return None


def _fecha(texto: str) -> str | None:
    fecha = re.search(r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2})\b", texto)
    hora = re.search(r"\b(\d{1,2}:\d{2}(?::\d{2})?(?:\s?[ap]\.?\s?m\.?)?)", texto, re.IGNORECASE)
    partes = [p.group(1) for p in (fecha, hora) if p]
    return " ".join(partes) or None


def _ultimos_digitos(texto: str) -> str | None:
    m = re.search(
        r"(?:cuenta|cta\.?|tarjeta|terminada en|termina en|llave)[^$\d*]{0,25}\*+\s?(\d{3,4})"
        r"|\*{2,}\s?(\d{3,4})"
        r"|terminada en\s+(\d{4})",
        texto, re.IGNORECASE,
    )
    if not m:
        return None
    return next(g for g in m.groups() if g)


def _referencia(texto: str) -> str | None:
    m = re.search(
        r"(?:referencia|ref\.?|comprobante|id de la transacci[oó]n|id transacci[oó]n|"
        r"c[oó]digo de aprobaci[oó]n|n[uú]mero de aprobaci[oó]n|aprobaci[oó]n|recibo)"
        r"\s*(?:no\.?|n[uú]mero|#|:)?\s*:?\s*([A-Z0-9][A-Z0-9-]{3,})",
        texto, re.IGNORECASE,
    )
    return m.group(1) if m else None


_RE_NOMBRE = r"([A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñ.&' -]{2,60}?)"


def _pagador_bancolombia(texto: str) -> str | None:
    etiquetado = valor_etiqueta(texto, ("nombre del pagador", "remitente", "pagador", "origen"))
    if etiquetado:
        return etiquetado[:60]
    m = re.search(
        r"\bde\s+(?:parte de\s+)?" + _RE_NOMBRE +
        r"(?=\s+(?:en\s+tu|en\s+su|a\s+tu|a\s+su|por\s|el\s+\d|desde|con\b)|[.,])",
        texto,
    )
    if m and not normalizar(m.group(1)).startswith(("ahorros", "corriente", "tu ", "su ")):
        return m.group(1).strip()
    return None


# ------------------------------------------------------------- Bancolombia

_SALIDA = ("transferiste", "pagaste", "compraste", "retiraste", "enviaste", "realizaste una compra",
           "realizaste un pago", "realizaste una transferencia", "debito", "inicio de sesion", "clave")
_ENTRADA = ("recibiste", "recibio", "recibida", "recibido", "te enviaron", "te transfirieron",
            "abono", "consignacion", "consignaron", "te pagaron")


def leer_bancolombia(asunto: str, texto: str) -> Pago | None:
    completo = f"{asunto} . {texto}"
    norm = normalizar(completo)
    es_entrada = any(p in norm for p in _ENTRADA)
    es_salida = any(p in norm for p in _SALIDA)
    if es_salida and not es_entrada:
        return None  # movimiento de salida u otra alerta: no es un pago recibido

    if "qr" in norm:
        metodo = "QR"
    elif "llave" in norm or "bre-b" in norm or "bre b" in norm or "breb" in norm:
        metodo = "Llave"
    else:
        metodo = "Transferencia"

    pago = Pago(
        fuente="bancolombia",
        metodo=metodo,
        monto_centavos=elegir_monto(completo),
        pagador=_pagador_bancolombia(texto) or _pagador_bancolombia(asunto),
        cuenta=_ultimos_digitos(completo),
        referencia=_referencia(texto),
        fecha_texto=_fecha(texto),
    )
    if not es_entrada or pago.monto_centavos is None:
        pago.estado = "revisar"
    return pago


# -------------------------------------------------------------------- Bold

_BOLD_RECHAZO = ("rechazad", "declinad", "fallid", "no aprobad", "no fue aprobad", "anulad", "reversad")
_BOLD_ENTRADA = ("venta", "aprobad", "recibiste", "pago exitoso", "transaccion exitosa", "cobro exitoso")
_BOLD_NO_PAGO = ("deposito", "desembolso", "liquidacion", "factura", "codigo de verificacion",
                 "inicia sesion", "iniciaste sesion")


def leer_bold(asunto: str, texto: str) -> Pago | None:
    completo = f"{asunto} . {texto}"
    norm = normalizar(completo)
    rechazado = any(p in norm for p in _BOLD_RECHAZO)
    es_pago = any(p in norm for p in _BOLD_ENTRADA)
    if not es_pago and not rechazado:
        if any(p in norm for p in _BOLD_NO_PAGO):
            return None  # depósitos a tu cuenta, facturas, códigos, etc.

    if "link de pago" in norm or "enlace de pago" in norm:
        metodo = "Link de pago"
    elif re.search(r"\bpse\b", norm):
        metodo = "PSE"
    elif "qr" in norm:
        metodo = "QR Bold"
    else:
        metodo = "Datáfono"

    franquicia = None
    for marca in ("visa", "mastercard", "american express", "amex", "diners", "maestro"):
        if marca in norm:
            franquicia = marca.title()
            break
    digitos = _ultimos_digitos(completo)

    pago = Pago(
        fuente="bold",
        metodo=metodo,
        monto_centavos=elegir_monto(completo),
        pagador=valor_etiqueta(texto, ("nombre del pagador", "pagador", "cliente", "titular")),
        cuenta=" ".join(x for x in (franquicia, f"*{digitos}" if digitos else None) if x) or None,
        referencia=_referencia(texto),
        fecha_texto=_fecha(texto),
    )
    if rechazado:
        pago.estado = "rechazado"
    elif not es_pago or pago.monto_centavos is None:
        pago.estado = "revisar"
    return pago


def leer(fuente: str, asunto: str, texto: str) -> Pago | None:
    if fuente == "bancolombia":
        return leer_bancolombia(asunto, texto)
    if fuente == "bold":
        return leer_bold(asunto, texto)
    return None
