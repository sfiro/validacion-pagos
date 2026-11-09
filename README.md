# Sistema de validación de pagos (Bancolombia + Bold)

Lee las notificaciones que llegan a Gmail de **Bancolombia** (QR, llave Bre‑B, transferencias)
y de **Bold** (datáfono, link de pago), y las muestra en un panel web para que los empleados
confirmen que el dinero llegó **antes de entregar** el producto.

No necesita instalar nada aparte de Python 3.10+ (ya incluido en macOS con Python.org).

## Cómo protege contra fraudes

- **No se confía en pantallazos**: solo cuenta el correo real del banco.
- **Correos falsos**: cada correo se verifica con la firma DKIM/DMARC que comprueba Gmail.
  Si alguien envía un correo haciéndose pasar por Bancolombia, aparece en rojo como
  *"CORREO NO VERIFICADO — no entregar"*.
- **Un pago = una entrega**: al validar, queda registrado quién y a qué hora. Si otro empleado
  intenta validar el mismo pago, el sistema lo bloquea y avisa quién ya lo usó.
- Transacciones **rechazadas** por Bold se muestran en rojo.
- Alertas de salida (transferiste, pagaste, compraste) se ignoran.
- Correos de Bancolombia/Bold que no se pudieron leer bien aparecen como *"Revisar"*, nunca se pierden.

## Instalar en un computador nuevo

1. **Python 3**: en Mac normalmente ya está. En Windows instálalo desde
   <https://www.python.org/downloads/> y **marca la casilla "Add python.exe to PATH"**.
2. **Descargar el sistema**: entra a <https://github.com/sfiro/validacion-pagos>,
   botón verde **Code → Download ZIP**, y descomprímelo en el Escritorio o en Documentos.
3. **Abrir** con doble clic:
   - Mac: `Iniciar (Mac).command`. La primera vez macOS puede bloquearlo: clic derecho → **Abrir** → **Abrir**.
   - Windows: `Iniciar (Windows).bat`. Si aparece "Windows protegió su PC": **Más información → Ejecutar de todas formas**.
     Si el firewall pregunta, permite el acceso en **redes privadas**.
4. La primera vez, el panel se abre en el navegador con la pantalla **Conectar cuenta de Gmail**:
   - **Correo de Gmail** donde llegan las notificaciones.
   - **Contraseña de aplicación** de 16 letras, creada en <https://myaccount.google.com/apppasswords>
     (requiere verificación en 2 pasos).
   - **PIN** (recomendado) para que solo los empleados abran el panel.

   Al tocar **Probar conexión y guardar**, el sistema verifica con Gmail y guarda los datos en la
   base local (`datos/pagos.db`) de ese computador. No hay que crear ni editar ningún archivo.
   Para cambiarlos después: botón **⚙︎ Configuración** del panel.

   Por seguridad, la cuenta solo se puede ver o cambiar desde el computador donde corre el
   sistema (`http://localhost:8080`), nunca desde los celulares, y la contraseña nunca se muestra.

> Solo **un** computador necesita correr el sistema. Los demás empleados abren desde el
> celular la dirección `http://192.168.x.x:8080` que aparece en la ventana.

## Actualizaciones

- Cada vez que se abre con `Iniciar`, el sistema busca y descarga la última versión de GitHub.
- Para actualizar a mano: doble clic en `Actualizar (Mac).command` o `Actualizar (Windows).bat`
  (con el panel cerrado).
- La cuenta conectada y los pagos guardados (`datos/`) **nunca** se reemplazan.

Para publicar una nueva versión (desde el computador de desarrollo):

```bash
git add -A && git commit -m "Descripción del cambio" && git push
```

## Uso diario

Doble clic en `Iniciar`. Mantén esa ventana abierta y el computador sin suspenderse
mientras el negocio esté abierto. Para detenerlo, cierra la ventana (o Ctrl+C).

En el panel el empleado:
1. Escribe su nombre (una vez por celular).
2. Cuando el cliente dice "ya le pagué $45.000", escribe `45000` en el buscador.
3. Si aparece el pago verde, toca **Validar y entregar**.

Desde terminal también funciona: `python3 main.py probar-conexion` y `python3 main.py`.
El archivo `.env` es opcional (configuración avanzada); lo normal es configurar desde el panel.

## Ajustar a tus correos reales

Los lectores se construyeron con el formato típico de estas notificaciones. Para verificar
con tus correos reales: en Gmail abre la notificación → ⋮ → **Descargar mensaje** (archivo `.eml`) y ejecuta:

```bash
python3 main.py probar ~/Downloads/archivo.eml
```

Muestra qué monto, método y pagador detectó, sin guardar nada. Si algo sale mal, ese
archivo `.eml` sirve para ajustar `app/parsers.py`.

## Pruebas

```bash
python3 -m unittest discover -s tests -v
```

## Estructura

Detalle técnico (flujo, base de datos, estados, API): [MODELO.md](MODELO.md).
Guía para desarrollar con Claude Code: [CLAUDE.md](CLAUDE.md).

| Archivo | Qué hace |
|---|---|
| `Iniciar …` / `Actualizar …` | Lanzadores de doble clic para Mac y Windows |
| `main.py` | Arranque y comandos |
| `actualizar.py` | Descarga de nuevas versiones desde GitHub |
| `app/correo.py` | Conexión IMAP a Gmail, verificación DKIM/DMARC |
| `app/parsers.py` | Lectura de monto, método, pagador, referencia |
| `app/db.py` | Base SQLite (`datos/pagos.db`) |
| `app/servidor.py` | API del panel |
| `app/static/index.html` | Panel para empleados |
| `ejemplos/` | Correos de prueba (formato aproximado, no reales) |
