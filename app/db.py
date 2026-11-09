"""Base de datos SQLite de pagos recibidos."""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path

from .tiempo import ahora

ESQUEMA = """
CREATE TABLE IF NOT EXISTS pagos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT UNIQUE NOT NULL,
    fuente TEXT NOT NULL,
    metodo TEXT,
    monto_centavos INTEGER,
    pagador TEXT,
    cuenta TEXT,
    referencia TEXT,
    fecha_texto TEXT,
    recibido_en TEXT NOT NULL,
    asunto TEXT,
    remitente TEXT,
    autenticado INTEGER NOT NULL DEFAULT 0,
    estado TEXT NOT NULL,
    validado_por TEXT,
    validado_en TEXT,
    nota TEXT,
    texto TEXT
);
CREATE INDEX IF NOT EXISTS idx_pagos_recibido ON pagos(recibido_en);
CREATE INDEX IF NOT EXISTS idx_pagos_monto ON pagos(monto_centavos);
CREATE TABLE IF NOT EXISTS estado (clave TEXT PRIMARY KEY, valor TEXT);
"""

COLUMNAS_PUBLICAS = (
    "id, fuente, metodo, monto_centavos, pagador, cuenta, referencia, fecha_texto, recibido_en, "
    "asunto, remitente, autenticado, estado, validado_por, validado_en, nota"
)


class BaseDatos:
    def __init__(self, ruta: Path):
        ruta.parent.mkdir(parents=True, exist_ok=True)
        self._con = sqlite3.connect(ruta, check_same_thread=False)
        self._con.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._con.executescript(ESQUEMA)

    # ------------------------------------------------------------ estado
    def get_estado(self, clave: str) -> str | None:
        with self._lock:
            fila = self._con.execute("SELECT valor FROM estado WHERE clave=?", (clave,)).fetchone()
        return fila["valor"] if fila else None

    def set_estado(self, clave: str, valor: str | None) -> None:
        with self._lock, self._con:
            self._con.execute(
                "INSERT INTO estado(clave, valor) VALUES(?, ?) "
                "ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor",
                (clave, valor),
            )

    # ------------------------------------------------------------- pagos
    def existe(self, message_id: str) -> bool:
        with self._lock:
            return self._con.execute(
                "SELECT 1 FROM pagos WHERE message_id=?", (message_id,)
            ).fetchone() is not None

    def insertar(self, datos: dict) -> int | None:
        columnas = ", ".join(datos)
        marcas = ", ".join("?" for _ in datos)
        with self._lock, self._con:
            cur = self._con.execute(
                f"INSERT OR IGNORE INTO pagos ({columnas}) VALUES ({marcas})", tuple(datos.values())
            )
            return cur.lastrowid if cur.rowcount else None

    def obtener(self, pago_id: int) -> dict | None:
        with self._lock:
            fila = self._con.execute(
                f"SELECT {COLUMNAS_PUBLICAS} FROM pagos WHERE id=?", (pago_id,)
            ).fetchone()
        return dict(fila) if fila else None

    def listar(self, busqueda: str = "", periodo: str = "hoy", estado: str = "", fuente: str = "",
               limite: int = 300) -> list[dict]:
        condiciones, params = [], []
        hoy = ahora().replace(hour=0, minute=0, second=0, microsecond=0)
        if periodo == "hoy":
            condiciones.append("recibido_en >= ?")
            params.append(hoy.isoformat())
        elif periodo == "7d":
            condiciones.append("recibido_en >= ?")
            params.append((hoy - timedelta(days=7)).isoformat())
        elif periodo == "30d":
            condiciones.append("recibido_en >= ?")
            params.append((hoy - timedelta(days=30)).isoformat())
        if estado:
            condiciones.append("estado = ?")
            params.append(estado)
        if fuente:
            condiciones.append("fuente = ?")
            params.append(fuente)

        busqueda = busqueda.strip()
        if busqueda:
            solo_numero = busqueda.replace("$", "").replace(".", "").replace(",", "").replace(" ", "")
            if solo_numero.isdigit():
                condiciones.append("(monto_centavos = ? OR referencia LIKE ? OR cuenta LIKE ?)")
                params += [int(solo_numero) * 100, f"%{solo_numero}%", f"%{solo_numero}%"]
            else:
                condiciones.append("(pagador LIKE ? OR referencia LIKE ? OR asunto LIKE ? OR texto LIKE ?)")
                params += [f"%{busqueda}%"] * 4

        donde = f"WHERE {' AND '.join(condiciones)}" if condiciones else ""
        with self._lock:
            filas = self._con.execute(
                f"SELECT {COLUMNAS_PUBLICAS} FROM pagos {donde} ORDER BY recibido_en DESC LIMIT ?",
                (*params, limite),
            ).fetchall()
        return [dict(f) for f in filas]

    def resumen_hoy(self) -> dict:
        hoy = ahora().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        with self._lock:
            filas = self._con.execute(
                "SELECT fuente, estado, COUNT(*) n, COALESCE(SUM(monto_centavos),0) total "
                "FROM pagos WHERE recibido_en >= ? GROUP BY fuente, estado",
                (hoy,),
            ).fetchall()
        return {"grupos": [dict(f) for f in filas]}

    def validar(self, pago_id: int, empleado: str, nota: str = "") -> tuple[bool, dict | None]:
        """Marca un pago como entregado/validado. Falla si alguien ya lo validó."""
        with self._lock, self._con:
            cur = self._con.execute(
                "UPDATE pagos SET estado='validado', validado_por=?, validado_en=?, nota=? "
                "WHERE id=? AND estado='pendiente'",
                (empleado, ahora().isoformat(), nota or None, pago_id),
            )
            ok = cur.rowcount == 1
        return ok, self.obtener(pago_id)

    def desmarcar(self, pago_id: int, empleado: str) -> tuple[bool, dict | None]:
        with self._lock, self._con:
            cur = self._con.execute(
                "UPDATE pagos SET estado='pendiente', validado_por=NULL, validado_en=NULL, "
                "nota=COALESCE(nota || ' | ', '') || ? WHERE id=? AND estado='validado'",
                (f"desmarcado por {empleado} {ahora():%d/%m %H:%M}", pago_id),
            )
            ok = cur.rowcount == 1
        return ok, self.obtener(pago_id)
