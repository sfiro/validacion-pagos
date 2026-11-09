import sys, tempfile, unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from app import parsers
from app.config import cargar_config
from app.correo import procesar_mensaje
from app.db import BaseDatos


class Montos(unittest.TestCase):
    def test_formatos(self):
        casos = {"$50.000": 5000000, "$50,000.00": 5000000, "$ 1.250.000,50": 125000050,
                 "$120,000": 12000000, "$5": 500, "COP 65.900": 6590000}
        for texto, esperado in casos.items():
            self.assertEqual(parsers.parse_monto(texto), esperado, texto)

    def test_ignora_saldo_y_comision(self):
        self.assertEqual(parsers.elegir_monto("Saldo disponible $900.000. Recibiste $20.000"), 2000000)
        self.assertEqual(parsers.elegir_monto("Comisión: $2.300 Monto: $65.900"), 6590000)


class Correos(unittest.TestCase):
    def setUp(self):
        self.cfg = cargar_config()
        self.cfg.requerir_autenticacion = True

    def leer(self, nombre):
        return procesar_mensaje((RAIZ / "ejemplos" / nombre).read_bytes(), self.cfg)

    def test_qr(self):
        r = self.leer("bancolombia_qr.eml")
        self.assertEqual((r["metodo"], r["monto_centavos"], r["estado"]), ("QR", 4500000, "pendiente"))

    def test_llave(self):
        r = self.leer("bancolombia_llave.eml")
        self.assertEqual((r["metodo"], r["monto_centavos"], r["pagador"]), ("Llave", 12000000, "JUAN CARLOS GOMEZ"))

    def test_salida_ignorada(self):
        self.assertEqual(self.leer("bancolombia_salida.eml")["accion"], "ignorado")

    def test_falso_sospechoso(self):
        self.assertEqual(self.leer("bancolombia_falso.eml")["estado"], "sospechoso")

    def test_encabezado_falsificado_por_estafador(self):
        crudo = (RAIZ / "ejemplos" / "bancolombia_qr.eml").read_bytes().replace(
            b"Authentication-Results: mx.google.com;", b"Authentication-Results: mx.estafa.xyz;")
        self.assertEqual(procesar_mensaje(crudo, self.cfg)["estado"], "sospechoso")

    def test_bold(self):
        r = self.leer("bold_datafono.eml")
        self.assertEqual((r["metodo"], r["monto_centavos"], r["cuenta"]), ("Datáfono", 6590000, "Visa *4321"))
        self.assertEqual(self.leer("bold_rechazada.eml")["estado"], "rechazado")

    def test_otro_remitente_ignorado(self):
        crudo = (RAIZ / "ejemplos" / "bancolombia_qr.eml").read_bytes().replace(
            b"alertasynotificaciones@bancolombia.com.co", b"alertas@bancolombia-pagos.com")
        self.assertEqual(procesar_mensaje(crudo, self.cfg)["accion"], "ignorado")


class Validacion(unittest.TestCase):
    def test_no_se_valida_dos_veces(self):
        with tempfile.TemporaryDirectory() as d:
            db = BaseDatos(Path(d) / "p.db")
            cfg = cargar_config()
            r = procesar_mensaje((RAIZ / "ejemplos" / "bancolombia_qr.eml").read_bytes(), cfg, db)
            self.assertEqual(procesar_mensaje((RAIZ / "ejemplos" / "bancolombia_qr.eml").read_bytes(), cfg, db)["accion"], "duplicado")
            ok1, _ = db.validar(r["id"], "Ana")
            ok2, pago = db.validar(r["id"], "Luis")
            self.assertTrue(ok1); self.assertFalse(ok2); self.assertEqual(pago["validado_por"], "Ana")
            self.assertEqual(len(db.listar("45.000", periodo="todo")), 1)


if __name__ == "__main__":
    unittest.main()
