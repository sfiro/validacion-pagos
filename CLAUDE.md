# CLAUDE.md

Guía para trabajar en este proyecto con Claude Code.

## Qué es

Sistema para que los empleados de un negocio en Colombia confirmen que llegó un pago antes
de entregar el producto. Lee de Gmail las notificaciones de **Bancolombia** (QR, llave
Bre-B, transferencia) y **Bold** (datáfono, link de pago) y las muestra en un panel web
en la red local.

- Detalle técnico (flujo, tablas, estados, API, reglas de lectura): [MODELO.md](MODELO.md)
- Instalación y uso para el negocio: [README.md](README.md)

Quien usa el sistema no es programador: escribe en español y usa Mac. Responde en español,
con instrucciones paso a paso y comandos listos para copiar.

## Comandos

```bash
python3 -m unittest discover -s tests -v       # pruebas (deben pasar antes de cada push)
python3 main.py                                # panel + lectura de Gmail (http://localhost:8080)
python3 main.py --abrir                        # igual, y abre el navegador (lo usan los lanzadores)
python3 main.py probar ejemplos/*.eml          # cómo se lee un correo, sin guardar
python3 main.py importar ejemplos/*.eml        # guardar .eml en la base (pruebas del panel)
python3 main.py probar-conexion                # probar la cuenta de Gmail configurada
python3 actualizar.py                          # descargar la última versión de GitHub
```

Para ver el panel en el navegador integrado: `.claude/launch.json` → configuración `panel-pagos`.

## Estructura

| Archivo | Responsabilidad |
|---|---|
| `main.py` | Arranque y comandos de terminal |
| `app/config.py` | `Config`, carga de `.env` y `aplicar_ajustes()` (ajustes del panel) |
| `app/correo.py` | IMAP, `verificar_autenticidad()`, `procesar_mensaje()`, `Vigilante`, `probar_credenciales()` |
| `app/parsers.py` | Lectores `leer_bancolombia()` / `leer_bold()`, `parse_monto()`, `elegir_monto()` |
| `app/db.py` | SQLite: tablas `pagos`, `ajustes`, `estado` |
| `app/servidor.py` | API HTTP y reglas de acceso (PIN, "solo local") |
| `app/static/index.html` | Panel completo (HTML + CSS + JS sin frameworks) |
| `app/certificados.py` | Contexto SSL con certificados del sistema en Mac |
| `actualizar.py` | Actualizador desde GitHub (git o ZIP) |
| `Iniciar …` / `Actualizar …` | Lanzadores de doble clic `.command` (Mac) y `.bat` (Windows) |
| `ejemplos/*.eml` | Correos de prueba **inventados**, con formato aproximado |
| `tests/test_sistema.py` | Pruebas de lectores, autenticidad, validación y configuración |

## Reglas del proyecto

- **Solo librería estándar de Python (3.10+).** Nada de `pip install`: el sistema se instala
  con doble clic en computadores sin conocimientos técnicos.
- **Código, nombres y textos en español** (funciones, variables, mensajes del panel).
- **Dinero en centavos (`int`)**, nunca `float`. Mostrar con formato `es-CO` (`$45.000`).
- **Hora de Colombia** con `app/tiempo.py` (`COLOMBIA`, UTC−5, sin horario de verano).
- **Panel**: el contenido de los correos no es confiable. Construir el DOM con `el()` /
  `textContent`, **nunca** `innerHTML` con datos del servidor.
- Los `.bat` deben quedar con fin de línea CRLF (`.gitattributes` tiene `*.bat -text`);
  los `.command` deben ser ejecutables (`chmod +x`).

## Seguridad (no romper)

- No subir nunca `.env`, `datos/` ni `.version_instalada` (están en `.gitignore`). El
  repositorio es **público**.
- No relajar `verificar_autenticidad()`: solo confía en el `Authentication-Results` que empieza
  por `mx.google.com`. Un correo sin DKIM/DMARC válido queda `sospechoso`.
- `db.validar()` debe seguir siendo atómico (`UPDATE … WHERE estado='pendiente'`) para que un
  pago no se entregue dos veces.
- La cuenta de Gmail solo se ve o cambia "en local" (IP local + `Host` localhost + JSON).
  La contraseña de aplicación nunca se devuelve en la API ni se escribe en los logs.
- IMAP siempre en solo lectura (`readonly=True`, `BODY.PEEK[]`).

## Ajustar un lector a un correo real

1. Pedir el `.eml` real (Gmail → ⋮ → Descargar mensaje), con datos sensibles tapados.
2. `python3 main.py probar archivo.eml` para ver qué se detecta.
3. Ajustar palabras clave o patrones en `app/parsers.py`.
4. Guardar una copia anonimizada en `ejemplos/` y agregar su caso en `tests/test_sistema.py`.
5. Correr todas las pruebas: un cambio en un patrón puede romper otro formato.

Pendiente: los lectores se hicieron con correos de ejemplo inventados; todavía no se han
validado con correos reales de Bancolombia y Bold, ni se han confirmado los dominios exactos
de los remitentes.

## Publicar cambios

**Un push a `main` llega a todos los computadores del negocio** la próxima vez que abran
`Iniciar`. Por eso:

1. Correr las pruebas y verificar el panel antes de hacer push.
2. Commit con mensaje claro en español (es lo que ve el actualizador: "Descargando
   actualización: …").
3. `git push` a `main`.

Los cambios de esquema en `db.py` deben ser compatibles con bases existentes
(`CREATE TABLE IF NOT EXISTS`, agregar columnas con `ALTER TABLE` controlado): cada
computador conserva su `datos/pagos.db` al actualizar.
