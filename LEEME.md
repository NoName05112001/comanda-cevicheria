# Comanda Cevichería — generar el .apk

Esta carpeta ya tiene todo listo para que GitHub compile el `.apk` por ti,
sin instalar nada en tu computadora. Son unos 10-15 minutos la primera vez.

**Importante sobre esta versión:** está pensada para un **solo dispositivo**
(una tablet o celular). La carta completa (83 platos) ya viene cargada
dentro de la app. Las mesas y ambientes los creas tú mismo desde la app,
igual que ahora. Todo se guarda en el celular donde la instales — si más
adelante quieres que varios mozos vean las mismas mesas en tiempo real
desde celulares distintos, avísame para preparar esa otra versión (necesita
conectarse a un servidor en vez de guardar todo solo en el teléfono).

## Paso 1 — Cuenta de GitHub (gratis)

Si no tienes una, créala en https://github.com/signup

## Paso 2 — Crear el repositorio

1. Entra a https://github.com/new
2. Ponle un nombre, por ejemplo `comanda-cevicheria`
3. Puede ser público o privado, cualquiera funciona
4. NO marques "Add a README file"
5. Dale a "Create repository"

## Paso 3 — Subir esta carpeta

En la página que te aparece, busca el enlace **"uploading an existing file"**
(o el botón "Add file" → "Upload files").

Arrastra **todo el contenido** de esta carpeta (los archivos y carpetas
`android`, `www`, `.github`, `capacitor.config.json`, `package.json`, etc. —
no la carpeta en sí, sino lo que está adentro) y dale a "Commit changes".

> Nota: la carpeta `node_modules` no hace falta subirla si la ves (es pesada
> y GitHub la reconstruye sola). Si tu explorador de archivos no te la
> muestra, no te preocupes, no está incluida en esta entrega.

## Paso 4 — Dejar que se compile solo

1. Ve a la pestaña **"Actions"** de tu repositorio (arriba)
2. Debería aparecer un proceso llamado "Build Android APK" corriendo
   (ícono amarillo = en progreso). Si no arrancó solo, entra a él y dale
   a "Run workflow".
3. Espera unos 3-6 minutos hasta que el ícono se ponga verde ✔

## Paso 5 — Descargar el .apk

1. Entra al proceso ya terminado (el que tiene el ✔ verde)
2. Baja hasta la sección **"Artifacts"**
3. Descarga **"comanda-cevicheria-debug-apk"** — es un .zip
4. Ábrelo: adentro está el archivo `app-debug.apk`

## Paso 6 — Instalar en el celular

1. Pasa el archivo `app-debug.apk` a tu celular Android (por cable USB,
   WhatsApp, Google Drive, correo, etc.)
2. Ábrelo desde el celular para instalarlo
3. Android puede pedirte permitir **"instalar apps de origen desconocido"**
   la primera vez — es normal, pasa con cualquier app que no venga de la
   Play Store. Actívalo solo para ese archivo/app.
4. Listo, te aparece el ícono de "Comanda" en la pantalla de inicio

## Si algo sale mal

Si la pestaña "Actions" marca una ❌ roja en vez de un ✔, entra al proceso,
haz clic en el paso que falló para ver el detalle, y pásamelo — lo reviso
y lo arreglo.
