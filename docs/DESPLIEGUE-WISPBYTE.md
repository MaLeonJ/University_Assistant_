# Despliegue en WispByte — Asistente Universitario

Guía para correr el bot 24/7 en [wispbyte.com](https://wispbyte.com)
(hosting gratuito, panel tipo Pterodactyl, imagen Docker Python).

## 0. Lo que necesitas a mano

- Cuenta en Wispbyte (plan Free, imagen **Python**)
- El paquete `asistente-universitario-wispbyte.zip`
- 3 archivos secretos que **NO vienen en el zip** (los subes aparte):
  | Archivo | Está en tu PC en |
  |---|---|
  | `.env` (ya configurado) | raíz del proyecto |
  | `credentials.json` | raíz del proyecto |
  | `token.json` | `data/token.json` |

## 1. Crear el servidor

1. Panel → **Create Server** → nombre y descripción
2. Plan **Free** · Docker image: **Python**
3. Crear y esperar a que aparezca en el dashboard

## 2. Subir los archivos

1. Tu servidor → pestaña **Files**
2. Sube el zip y extráelo en la raíz (`/home/container`)
3. Sube los 3 archivos secretos:
   - `.env` → raíz
   - `credentials.json` → raíz
   - `token.json` → dentro de `data/`

> El `.env` también puede ir como variables de entorno en la pestaña
> **Startup**: el código lee primero las variables del panel y el `.env`
> solo completa lo que falte.

## 3. Configurar Startup

Pestaña **Startup**:

- **Startup command / main file**: `python main.py`
- **Additional Python Packages** (si el egg no instala `requirements.txt`
  automáticamente, el zip ya lo trae en la raíz):
  ```
  python-telegram-bot==22.8
  ddgs==9.15.0
  google-genai==2.19.0
  openai==3.3.1
  python-dotenv==1.2.3
  typer==0.27.1
  google-api-python-client==2.199.0
  google-auth-oauthlib==1.4.1
  google-auth-httplib2==0.4.2
  ```

## 4. Arrancar y verificar

1. Pestaña **Console** → **Start**
2. En el log debe aparecer `Bot iniciado`
3. Prueba en Telegram: `/menu` → 🔄 Sincronizar → ☁️ **Google Drive**
   (la sync local no aplica en el servidor; si la pulsas, el bot avisa
   con los pasos en vez de romperse)

## 5. Avisos importantes

- **⚠️ 409 Conflict**: nunca tengas el mismo token corriendo en tu PC y en
  WispByte a la vez. Antes de arrancar el servidor, detén tu instancia
  local (`pkill -f "python main.py"`).
- **Renovación**: el plan Free pide iniciar sesión en el panel al menos una
  vez al mes (si no, archiva el servidor; no lo borra).
- **RAM**: el plan free tiene 512 MB — suficiente para este bot.
- **Actualizaciones**: sube los archivos cambiados desde tu repo local
  (mismo código, mismos tests) y reinicia desde Console.
- **Backups de estado**: `data/usage.json`, `data/cache.db` y
  `data/search.db` se regeneran solos; `data/token.json` es el único que
  conviene conservar (si lo pierdes, repite `asistente drive-auth` en tu PC).
