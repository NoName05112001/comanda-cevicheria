# Puente Comanda Cevichería ↔ "999"

Este programa conecta la app "Comanda Cevichería" (la que usan los mozos en
el celular o en el navegador) con el sistema real del restaurante, "999" —
para que un pedido que un mozo registra aparezca solo, sin que nadie lo
vuelva a escribir a mano, en la computadora de "999".

**No corre en el celular.** Corre en UNA de las dos computadoras "comando"
del restaurante (la B o la C — nunca en la principal). Necesita quedarse
abierto todo el día, igual que "999".

## Cómo funciona (en corto)

Este programa lee los pedidos **directo de la base de datos en la nube**
(Firestore) con su propia llave de administrador — ya no depende de que
ninguna pestaña del navegador esté abierta ni le avise nada. Eso simplifica
bastante las cosas: el navegador de los mozos puede estar en cualquier
celular o computadora, con la pestaña que sea, y este programa se entera
igual.

1. Cuando un mozo registra platos en cocina o cierra un pedido (desde el
   sitio web normal, en cualquier dispositivo), este programa lo nota en
   cuestión de segundos.
2. Según el modo configurado, o solo anota en un log qué haría (**modo
   simulación**, el que trae por defecto) o de verdad activa la ventana de
   "999" y escribe el pedido (**modo real**).
3. Si dos mozos mandan pedidos casi al mismo tiempo, los procesa de a uno,
   **en el orden real en que se mandaron** (por la hora del servidor, no la
   del celular de cada quien) — nunca se cruzan ni se duplican.
4. Va escribiendo su propio estado (conectado, pendientes, actividad) en la
   nube, para que cualquiera pueda ver cómo va desde el panel de
   Administrador de la app, sin necesitar estar en esta misma computadora.

## Paso 1 — Conseguir el .exe

No hace falta instalar Python en la computadora del restaurante. GitHub
arma el `.exe` solo:

1. Sube esta carpeta (`puente/`) y la carpeta `.github/workflows/` a tu
   repositorio de GitHub (la carpeta `puente/` NUNCA debe incluir el
   archivo `firebase-service-account.json` — está en `.gitignore` para
   evitarlo, pero revisa que no se haya subido por error).
2. Ve a la pestaña **Actions** del repositorio. Debería aparecer o arrancar
   solo un proceso llamado **"Build Puente (.exe)"**. Si no arranca solo,
   entra a él y dale a "Run workflow".
3. Espera a que termine (ícono verde ✔, unos 2-4 minutos).
4. Entra al proceso terminado, baja a **Artifacts** y descarga
   **"puente-comanda-cevicheria-exe"** (un .zip). Adentro está
   `puente-comanda-cevicheria.exe`.
5. Pasa ese único archivo `.exe` a la computadora "comando" del restaurante
   (USB, WhatsApp, Drive, lo que sea) y déjalo en una carpeta cualquiera,
   por ejemplo el Escritorio. Crea ahí una carpeta (ej. `puente`) y pon el
   `.exe` adentro.

## Paso 2 — Poner la llave privada al lado del .exe

Este programa necesita el archivo `firebase-service-account.json` **en la
misma carpeta que el .exe**, en la computadora del restaurante. Es la llave
que le da acceso de administrador a la base de datos — nunca se sube a
GitHub ni se comparte en público. Si no la tienes a mano, pídesela a quien
armó el proyecto de Firebase.

La carpeta debe quedar así:

```
puente/
  puente-comanda-cevicheria.exe
  firebase-service-account.json
```

(`config.json` y `puente_log.txt` aparecen solos la primera vez que corres
el `.exe` — no hace falta crearlos a mano.)

## Paso 3 — Probar en modo simulación (recomendado antes que nada)

1. Doble clic en `puente-comanda-cevicheria.exe`. Va a abrir una ventana de
   consola negra, va a crear `config.json` (con `"modo": "simulacion"`) y
   va a decir "Conectado a Firestore. Vigilando pedidos en vivo..." — si en
   vez de eso dice que no encuentra `firebase-service-account.json`, revisa
   el Paso 2.
2. Desde cualquier celular o computadora, abre el sitio normal (el enlace
   de GitHub Pages, no hace falta que sea esta misma computadora) y haz un
   pedido de prueba en una mesa, regístralo en cocina.
3. En unos segundos debería aparecer en la consola del puente algo así:

   ```
   [SIMULACIÓN] Registraría en "999" — Mesa M07 (mozo J1):
      - 2x [002100] Gaseosa 1 Litro — Inca Kola · Helada
      -> Presionaría "Registrar" con código de mozo "J1"
   ```

4. Revisa que la mesa, el código, la cantidad y el comentario sean los
   correctos. Si un plato sale con `??? (sin código real...)`, es uno de los
   pocos platos que todavía no tienen su código real mapeado (ver el
   documento del proyecto, sección 3) — el mozo va a tener que escribirlo a
   mano en "999" cuando llegue ese caso.
5. También puedes ver el mismo estado desde el navegador: en el panel de
   Administrador de la app (código 55555) hay una sección "Puente a 999"
   que muestra si el programa está conectado, lo pendiente y la actividad
   reciente — funciona desde cualquier dispositivo, no hace falta que sea
   la computadora del puente.

**No pases a modo real hasta que esto se vea bien en varias pruebas.**

## Paso 4 — Pasar a modo real (cuando ya se probó en simulación)

1. Cierra el `.exe` si está corriendo.
2. Abre `config.json` (al lado del .exe) con el Bloc de notas y cambia:

   ```json
   "modo": "simulacion"
   ```
   por
   ```json
   "modo": "real"
   ```
3. Vuelve a abrir el `.exe`. Ahora sí va a intentar activar la ventana de
   "999" y escribir de verdad.

**Importante — la secuencia de teclas todavía no está confirmada contra el
sistema real.** `config.json` trae una secuencia de partida
(`secuencia_por_plato`, `secuencia_registrar`, `secuencia_finalizar`)
basada en lo que ya se sabe del flujo de "999" (ver el documento del
proyecto, sección 2), pero cosas como el atajo exacto del botón
"Registrar" o si hace falta Tab o Enter entre un campo y otro **son un
punto de partida, no un hecho confirmado** — hay que verlas funcionar en
la pantalla real y ajustarlas ahí mismo.

Para ajustar la secuencia **no hace falta tocar Python ni volver a
compilar el .exe**: se edita `config.json` directamente (es una lista de
pasos: `escribir` un texto, apretar una `tecla`, o `esperar` unos
milisegundos) y se vuelve a abrir el `.exe`. Si algo se traba, lo más
seguro es volver a `"modo": "simulacion"`, avisar para ajustar la
secuencia junto con lo que se vea en pantalla, y recién después volver a
probar en real.

## Seguridad / cosas a tener en cuenta

- **Nunca instalar este programa en la computadora "principal"** — solo en
  la B o la C (ver el documento del proyecto, sección 7).
- `firebase-service-account.json` es una llave privada: no se sube a
  GitHub, no se manda por canales públicos. Si alguna vez se pierde el
  control de ese archivo, hay que generar una llave nueva desde Firebase
  (Configuración del proyecto → Cuentas de servicio) y borrar la vieja.
- Mientras el puente está escribiendo en modo real, aparece una ventanita
  roja que dice "PEDIDO EN PROCESO — No tocar el teclado ni el mouse". Hay
  que respetarla: si alguien toca el teclado de "999" mientras tanto, el
  pedido puede quedar mal escrito.
- Si dos platos con el mismo pedido llegan casi al mismo tiempo, el puente
  los procesa de a uno, en el orden real en que se mandaron — no se
  cruzan.
- Si la computadora se reinicia o se cierra el `.exe`, todo lo que quedó
  pendiente de avisar se retoma solo apenas se vuelve a abrir (queda
  guardado en `puente_procesados.json`, al lado del .exe).
- Si un pedido ya se escribió a mano en "999" porque el puente estaba
  apagado en ese momento, en la sección "Puente a 999" del panel de
  Administrador hay un botón **"Descartar"** junto al pendiente
  correspondiente, para que no se vuelva a mandar cuando el puente se
  reconecte.

## Modo desarrollo (sin armar el .exe)

Si en algún momento se quiere probar cambios al código directamente (en vez
de esperar a que GitHub arme el .exe), en una computadora con Python 3.9+
instalado:

```
pip install -r requirements.txt
python bridge_server.py
```

Funciona igual que el .exe (mismo `config.json`, misma carpeta para
`firebase-service-account.json`).
