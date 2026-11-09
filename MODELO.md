# Modelo del sistema

Documento técnico: cómo fluye un pago desde el correo hasta el panel, cómo se guarda y
qué reglas lo protegen contra fraudes. Para instalar y usar, ver [README.md](README.md).

## Visión general

```
Bancolombia / Bold ──correo──▶ Gmail ──IMAP (cada 30 s)──▶ Vigilante ──▶ SQLite ──▶ API HTTP ──▶ Panel (celulares en el WiFi)
                                                             │
                                                  verificación DKIM/DMARC
                                                  lectura de monto/método
```

Un solo computador corre el sistema (`main.py`). Los empleados abren el panel desde el
celular en la red local. No hay servidor en internet: los datos nunca salen del negocio.

## Flujo de un correo

1. **Vigilante** (`app/correo.py`, hilo en segundo plano) entra a Gmail por IMAP en modo
   solo lectura (`BODY.PEEK`, no marca los correos como leídos).
2. Busca solo correos de los dominios configurados (`OR FROM ...`) con UID mayor al último
   procesado. La primera vez revisa los últimos `DIAS_INICIALES` días (2 por defecto).
3. Por cada correo, `procesar_mensaje()`:
   1. **Identifica la fuente** por el dominio del remitente (`bancolombia` o `bold`).
      Otro remitente → se ignora.
   2. **Evita duplicados** por `Message-ID`.
   3. **Verifica autenticidad** (ver abajo).
   4. **Extrae el texto**: prefiere la parte HTML convertida a texto; si no tiene un valor
      en `$`/`COP`, usa la parte de texto plano.
   5. **Lee el pago** con el lector de su fuente (`app/parsers.py`).
   6. **Guarda** el pago con su estado.
4. Guarda el último UID revisado, por cuenta, carpeta y `UIDVALIDITY`.
5. Registra la hora de la última revisión o el último error; el panel lo muestra como
   "Correo al día" o "Sin conexión al correo".

## Verificación de autenticidad

Un estafador puede poner `alertas@bancolombia.com.co` como remitente, pero no puede firmar
con DKIM del banco ni pasar DMARC.

- Solo se confía en el encabezado `Authentication-Results` que agrega Gmail (el primero
  que empieza por `mx.google.com`); los encabezados que agregue un tercero se ignoran.
- Se acepta si hay `dmarc=pass` con `header.from` de un dominio permitido que coincide con
  el remitente, o `dkim=pass` firmado por un dominio permitido relacionado con el remitente.
- Si falla y `REQUERIR_AUTENTICACION=true` (por defecto), el pago se guarda como
  **`sospechoso`** y el panel muestra "CORREO NO VERIFICADO — no entregar".

Dominios permitidos por defecto:

| Fuente | Dominios |
|---|---|
| Bancolombia | `bancolombia.com.co`, `notificacionesbancolombia.com`, `bancolombia.com` |
| Bold | `bold.co` |

Se aceptan también subdominios (`x.bold.co`).

## Lectura de los correos

Los formatos cambian con el tiempo, así que los lectores buscan palabras clave y
patrones, no una plantilla fija. El texto se compara en minúsculas y sin tildes.

### Bancolombia

| Paso | Regla |
|---|---|
| ¿Es entrada? | Contiene `recibiste`, `recibida`, `te enviaron`, `abono`, `consignacion`… |
| ¿Es salida? | `transferiste`, `pagaste`, `compraste`, `retiraste`… Si es solo salida → se ignora |
| Método | `qr` → **QR**; `llave` / `bre-b` → **Llave**; si no → **Transferencia** |
| Pagador | Etiqueta (`Remitente:`, `Pagador:`) o patrón "de NOMBRE en/por…" |
| Cuenta | Últimos dígitos tras `*` |

### Bold

| Paso | Regla |
|---|---|
| ¿Rechazada? | `rechazad`, `declinad`, `fallid`, `anulad`… → estado `rechazado` |
| ¿Es pago? | `venta`, `aprobad`, `recibiste`, `pago exitoso`… |
| ¿No es pago? | Depósitos a tu cuenta, facturas, códigos → se ignora |
| Método | `link de pago` → **Link de pago**; `pse` → **PSE**; `qr` → **QR Bold**; si no → **Datáfono** |
| Tarjeta | Franquicia (Visa, Mastercard…) + últimos 4 dígitos |

### Monto

`elegir_monto()` recorre todos los valores `$`/`COP` del correo:

- Descarta los que van precedidos de `saldo`, `comision`, `retencion`, `iva`, `4x1000`,
  `gmf`, `neto`, `cupo` o `disponible`. El contexto llega solo hasta el valor anterior,
  para que "Comisión: $2.300 Monto: $65.900" tome $65.900.
- Prefiere los precedidos de `monto`, `valor`, `total`, `por`, `recibiste`, `venta`.
- Acepta `$50.000`, `$50,000.00`, `$ 1.250.000,50`, `COP 65.900`.
- Se guarda en **centavos** (entero) para evitar errores de decimales.

## Modelo de datos

Base SQLite en `datos/pagos.db` (permisos `600`, solo el usuario del computador).

### Tabla `pagos`

| Columna | Tipo | Descripción |
|---|---|---|
| `id` | INTEGER PK | Identificador |
| `message_id` | TEXT UNIQUE | `Message-ID` del correo (o hash). Evita duplicados |
| `fuente` | TEXT | `bancolombia` / `bold` |
| `metodo` | TEXT | QR, Llave, Transferencia, Datáfono, Link de pago, PSE, QR Bold |
| `monto_centavos` | INTEGER | Valor en centavos (`4500000` = $45.000). `NULL` si no se pudo leer |
| `pagador` | TEXT | Nombre de quien pagó, si viene en el correo |
| `cuenta` | TEXT | Últimos dígitos de cuenta (Bancolombia) o "Visa *4321" (Bold) |
| `referencia` | TEXT | Comprobante / ID de transacción |
| `fecha_texto` | TEXT | Fecha y hora tal como aparecen en el correo |
| `recibido_en` | TEXT | Fecha del correo en hora de Colombia (ISO 8601, `-05:00`) |
| `asunto`, `remitente` | TEXT | Del correo |
| `autenticado` | INTEGER | 1 si pasó DKIM/DMARC |
| `estado` | TEXT | Ver ciclo de vida |
| `validado_por`, `validado_en` | TEXT | Empleado y hora de la validación |
| `nota` | TEXT | Motivo de fallo de autenticidad, historial de "deshacer" |
| `texto` | TEXT | Texto del correo (máx. 4000 caracteres) para revisión |

### Tabla `ajustes`

Configuración guardada desde el panel; tiene prioridad sobre `.env`.

| Clave | Uso |
|---|---|
| `gmail_usuario` | Correo de Gmail |
| `gmail_clave_app` | Contraseña de aplicación (sin espacios) |
| `pin_acceso` | PIN del panel (vacío = sin PIN) |
| `imap_carpeta` | Carpeta a revisar (`INBOX` por defecto) |

### Tabla `estado`

Clave/valor interno: `ultimo_uid:<cuenta>:<carpeta>:<uidvalidity>`, `ultima_revision`,
`ultimo_error`, `ultimo_error_en`.

## Ciclo de vida de un pago

```
                 ┌──────────── deshacer ────────────┐
                 ▼                                  │
correo ──▶  pendiente ──── Validar y entregar ──▶ validado
   │
   ├──▶ sospechoso   (no pasó DKIM/DMARC — no entregar)
   ├──▶ rechazado    (Bold informó transacción rechazada)
   └──▶ revisar      (remitente válido pero no se pudo leer el monto o si es entrada)
```

- **Un pago = una entrega**: `validar` solo cambia `pendiente → validado` en una única
  sentencia SQL (`WHERE estado='pendiente'`). Si dos empleados tocan a la vez, solo uno
  gana; el otro recibe `409` con el nombre de quien ya lo validó.
- `desmarcar` vuelve `validado → pendiente` y deja constancia en `nota`.

## API HTTP

Servidor: `ThreadingHTTPServer` en `0.0.0.0:8080` (librería estándar). Si hay PIN,
toda ruta `/api/*` excepto `/api/config` requiere el encabezado `X-Pin`.

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/` | Panel (`app/static/index.html`) |
| GET | `/api/config` | `{requiere_pin, configurado, es_local}` — sin PIN |
| GET | `/api/pagos?q=&periodo=&estado=&fuente=` | Lista (máx. 300). `periodo`: `hoy`, `7d`, `30d`, `todo`. `q` numérico busca monto exacto, referencia o cuenta; texto busca pagador, referencia, asunto, contenido |
| GET | `/api/estado` | Conexión con Gmail y resumen del día |
| POST | `/api/pagos/{id}/validar` | `{empleado, nota?}` → `200` o `409` si ya no está pendiente |
| POST | `/api/pagos/{id}/desmarcar` | `{empleado}` |
| GET | `/api/configuracion` | Solo local. Correo, carpeta, `tiene_clave`, `tiene_pin` (nunca los secretos) |
| POST | `/api/configuracion` | Solo local. `{gmail_usuario, gmail_clave_app?, pin_acceso?, quitar_pin?, imap_carpeta?}`. Prueba la conexión con Gmail antes de guardar |

**"Solo local"** significa que se cumplen las tres condiciones:
1. La petición viene de `127.0.0.1` / `::1`.
2. El encabezado `Host` es `localhost` o `127.0.0.1` (protege contra *DNS rebinding*).
3. En `POST`, `Content-Type: application/json` (una página web ajena no puede enviarlo sin
   permiso CORS, que el servidor nunca concede).

## Distribución y actualización

- Repositorio público: <https://github.com/sfiro/validacion-pagos>.
- `Iniciar (Mac).command` / `Iniciar (Windows).bat` ejecutan `actualizar.py --silencioso`
  y luego `main.py --abrir`.
- `actualizar.py`:
  - Con carpeta `.git` → `git pull --ff-only`.
  - Sin git (descarga ZIP) → consulta el último commit de `main` en la API de GitHub,
    descarga el ZIP de ese commit y copia los archivos. Nunca toca `.env`, `datos/`,
    `.git` ni `.version_instalada`.
  - Guarda `"<sha> <fecha>"` en `.version_instalada` y **no instala** una versión con fecha
    igual o anterior (evita volver atrás por respuestas en caché).
- En Mac con el Python de python.org, `app/certificados.py` carga los certificados raíz del
  llavero del sistema para HTTPS (GitHub) e IMAP (Gmail).

## Configuración

Prioridad: tabla `ajustes` (panel) > variables de entorno / `.env` > valores por defecto.

| Variable | Defecto | Descripción |
|---|---|---|
| `GMAIL_USUARIO`, `GMAIL_CLAVE_APP` | — | Normalmente se configuran desde el panel |
| `IMAP_SERVIDOR` | `imap.gmail.com` | |
| `IMAP_CARPETA` | `INBOX` | |
| `DOMINIOS_BANCOLOMBIA`, `DOMINIOS_BOLD` | ver arriba | Separados por coma |
| `REQUERIR_AUTENTICACION` | `true` | `false` solo si los correos llegan reenviados |
| `SEGUNDOS_ENTRE_REVISIONES` | `30` | |
| `DIAS_INICIALES` | `2` | |
| `PUERTO` | `8080` | |
| `PIN_ACCESO` | vacío | |
