"""Configuración leída del archivo .env (o variables de entorno)."""
import os
from dataclasses import dataclass, field
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def _cargar_env(ruta: Path) -> None:
    if not ruta.exists():
        return
    # utf-8-sig: el Bloc de notas de Windows puede agregar BOM al guardar
    for linea in ruta.read_text(encoding="utf-8-sig").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, valor = linea.split("=", 1)
        valor = valor.strip().strip('"').strip("'")
        os.environ.setdefault(clave.strip(), valor)


def _lista(valor: str) -> list[str]:
    return [v.strip().lower() for v in valor.split(",") if v.strip()]


def _bool(valor: str) -> bool:
    return valor.strip().lower() in ("1", "true", "si", "sí", "yes")


@dataclass
class Config:
    gmail_usuario: str
    gmail_clave_app: str
    imap_servidor: str
    imap_carpeta: str
    dominios_bancolombia: list[str]
    dominios_bold: list[str]
    requerir_autenticacion: bool
    segundos_entre_revisiones: int
    dias_iniciales: int
    puerto: int
    pin_acceso: str
    base_datos: Path = field(default_factory=lambda: RAIZ / "datos" / "pagos.db")

    @property
    def correo_configurado(self) -> bool:
        return bool(
            self.gmail_usuario and self.gmail_clave_app
            and self.gmail_usuario != "tucorreo@gmail.com"
            and not self.gmail_clave_app.startswith("xxxx")
        )


def cargar_config() -> Config:
    _cargar_env(RAIZ / ".env")
    e = os.environ.get
    return Config(
        gmail_usuario=e("GMAIL_USUARIO", ""),
        gmail_clave_app=e("GMAIL_CLAVE_APP", "").replace(" ", ""),
        imap_servidor=e("IMAP_SERVIDOR", "imap.gmail.com"),
        imap_carpeta=e("IMAP_CARPETA", "INBOX"),
        dominios_bancolombia=_lista(
            e("DOMINIOS_BANCOLOMBIA", "bancolombia.com.co,notificacionesbancolombia.com,bancolombia.com")
        ),
        dominios_bold=_lista(e("DOMINIOS_BOLD", "bold.co")),
        requerir_autenticacion=_bool(e("REQUERIR_AUTENTICACION", "true")),
        segundos_entre_revisiones=int(e("SEGUNDOS_ENTRE_REVISIONES", "30")),
        dias_iniciales=int(e("DIAS_INICIALES", "2")),
        puerto=int(e("PUERTO", "8080")),
        pin_acceso=e("PIN_ACCESO", ""),
    )
