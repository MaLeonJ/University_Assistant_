"""Sincronización de documentos a Google Drive con la API oficial v3.

Autenticación OAuth de usuario (una sola vez, en una PC con navegador):

1. Google Cloud Console → habilita «Google Drive API» → crea credenciales
   OAuth de tipo «Aplicación de escritorio» y guarda el JSON descargado como
   ``credentials.json`` en la raíz del proyecto.
2. Ejecuta ``asistente drive-auth``, autoriza en el navegador y se genera
   ``data/token.json`` (refrescable sin navegador mientras no caduque).
3. Copia ``credentials.json`` y ``data/token.json`` al servidor y define
   ``GDRIVE_FOLDER_ID`` en ``.env`` (el ID de la carpeta está al final de su
   URL de Drive).

La sincronización es incremental por MD5, crea las subcarpetas que hagan
falta y NUNCA borra nada del destino.
"""

import hashlib
import logging
from pathlib import Path, PurePosixPath

from .config import (
    GDRIVE_CREDENTIALS_FILE,
    GDRIVE_FOLDER_ID,
    GDRIVE_TOKEN_FILE,
    OUTPUT_DIR,
)

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
APP_NAME = "asistente-universitario"

MIME_CARPETA = "application/vnd.google-apps.folder"
MIME_MD = "text/markdown"


class DriveError(RuntimeError):
    """Fallo de la API o del flujo OAuth de Google Drive."""


def estado() -> str | None:
    """Devuelve el motivo por el que Drive no está listo, o None si lo está."""
    if not GDRIVE_FOLDER_ID:
        return "Falta GDRIVE_FOLDER_ID en .env"
    if not GDRIVE_CREDENTIALS_FILE.exists():
        return f"No existe {GDRIVE_CREDENTIALS_FILE} (credenciales OAuth de escritorio)"
    if not GDRIVE_TOKEN_FILE.exists():
        return (
            f"No existe {GDRIVE_TOKEN_FILE}; genéralo con "
            "`asistente drive-auth` en tu PC y cópialo al servidor"
        )
    return None


def login_interactivo() -> Path:
    """Abre el navegador para autorizar y guarda el token refrescable."""
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as e:
        raise DriveError(
            'Faltan librerías de Google; instala con: pip install -e ".[drive]"'
        ) from e

    if not GDRIVE_CREDENTIALS_FILE.exists():
        raise DriveError(
            f"Primero descarga credentials.json desde Google Cloud Console "
            f"(debe estar en {GDRIVE_CREDENTIALS_FILE})"
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(GDRIVE_CREDENTIALS_FILE), SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent")

    GDRIVE_TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    GDRIVE_TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
    logger.info("Token de Drive guardado en %s", GDRIVE_TOKEN_FILE)
    return GDRIVE_TOKEN_FILE


def _credenciales():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    if not GDRIVE_TOKEN_FILE.exists():
        raise DriveError("Sin token de Drive; ejecuta `asistente drive-auth` y copia token.json")
    creds = Credentials.from_authorized_user_file(str(GDRIVE_TOKEN_FILE), SCOPES)
    if not creds.valid and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        GDRIVE_TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
    if not creds.valid:
        raise DriveError("El token de Drive es inválido; repite `asistente drive-auth`")
    return creds


def _servicio():
    try:
        from googleapiclient.discovery import build
    except ImportError as e:
        raise DriveError(
            'Faltan librerías de Google; instala con: pip install -e ".[drive]"'
        ) from e
    return build("drive", "v3", credentials=_credenciales(), static_discovery=False)


def sync_drive(servicio=None) -> dict[str, int]:
    """Copia incremental de documentos/ a la carpeta configurada de Drive."""
    if servicio is None:
        servicio = _servicio()

    if not OUTPUT_DIR.exists():
        return {"nuevos": 0, "actualizados": 0, "total": 0}

    carpetas: dict[str, str] = {"": GDRIVE_FOLDER_ID}
    archivos: dict[str, tuple[str, str]] = {}
    _indexar_remoto(servicio, GDRIVE_FOLDER_ID, "", carpetas, archivos)

    nuevos = 0
    actualizados = 0
    total = 0

    for src in sorted(OUTPUT_DIR.rglob("*.md")):
        rel = src.relative_to(OUTPUT_DIR).as_posix()
        total += 1
        padre = str(PurePosixPath(rel).parent)
        folder_id = _asegurar_carpeta(servicio, carpetas, padre)

        remoto = archivos.get(rel)
        md5_local = _md5(src)
        if remoto is not None and remoto[1] == md5_local:
            continue

        media = _media(src)
        try:
            if remoto is not None:
                servicio.files().update(fileId=remoto[0], media_body=media).execute()
                actualizados += 1
            else:
                servicio.files().create(
                    body={"name": src.name, "parents": [folder_id]},
                    media_body=media,
                    fields="id",
                ).execute()
                nuevos += 1
        except Exception as e:
            raise DriveError(f"API de Drive falló subiendo {rel}: {e}") from e

    logger.info("Sync a Drive: %s nuevos, %s actualizados de %s", nuevos, actualizados, total)
    return {"nuevos": nuevos, "actualizados": actualizados, "total": total}


def sync_text(resultado: dict[str, int]) -> str:
    destino = "☁️ *Google Drive* (`GDRIVE_FOLDER_ID`)"
    if resultado["total"] == 0:
        return f"📭 No hay documentos para sincronizar.\n\n🎯 Destino: {destino}"

    lineas = [
        "🔄 *Sincronización a Drive completada*\n",
        f"✨ Nuevos: *{resultado['nuevos']}*",
        f"♻️ Actualizados: *{resultado['actualizados']}*",
        f"📚 Total en biblioteca: {resultado['total']}",
        "",
        f"🎯 Destino: {destino}",
    ]
    return "\n".join(lineas)


def texto_configuracion(motivo: str) -> str:
    return (
        "☁️ *Drive aún no está configurado*\n\n"
        f"Motivo: `{motivo}`\n\n"
        "*Pasos (una sola vez):*\n"
        "1. Google Cloud Console → habilita *Google Drive API* → credenciales "
        "OAuth «Aplicación de escritorio» → guarda como `credentials.json`\n"
        "2. En tu PC: `asistente drive-auth` y autoriza en el navegador\n"
        "3. Copia `credentials.json` y `data/token.json` al servidor\n"
        "4. En `.env`: `GDRIVE_FOLDER_ID=<ID de tu carpeta>`\n"
        "_El ID de la carpeta es la parte final de su URL de Drive._"
    )


def _indexar_remoto(
    servicio,
    folder_id: str,
    prefijo: str,
    carpetas: dict[str, str],
    archivos: dict[str, tuple[str, str]],
) -> None:
    token: str | None = None
    while True:
        peticion = servicio.files().list(
            q=f"'{folder_id}' in parents and trashed=false",
            fields="nextPageToken, files(id, name, mimeType, md5Checksum)",
            pageSize=200,
            pageToken=token,
        )
        respuesta = peticion.execute()
        for item in respuesta.get("files", []):
            rel = f"{prefijo}{item['name']}"
            if item["mimeType"] == MIME_CARPETA:
                carpetas[rel] = item["id"]
                _indexar_remoto(servicio, item["id"], rel + "/", carpetas, archivos)
            elif item["name"].endswith(".md"):
                archivos[rel] = (item["id"], item.get("md5Checksum", ""))
        token = respuesta.get("nextPageToken")
        if not token:
            return


def _asegurar_carpeta(servicio, carpetas: dict[str, str], ruta_relativa: str) -> str:
    if ruta_relativa in carpetas:
        return carpetas[ruta_relativa]

    partes = PurePosixPath(ruta_relativa).parts
    if len(partes) > 1:
        padre_id = _asegurar_carpeta(servicio, carpetas, "/".join(partes[:-1]))
    else:
        padre_id = carpetas[""]

    try:
        creado = (
            servicio.files()
            .create(
                body={
                    "name": partes[-1],
                    "mimeType": MIME_CARPETA,
                    "parents": [padre_id],
                },
                fields="id",
            )
            .execute()
        )
    except Exception as e:
        raise DriveError(f"API de Drive falló creando carpeta {ruta_relativa}: {e}") from e
    carpetas[ruta_relativa] = creado["id"]
    return creado["id"]


def _media(src: Path):
    from googleapiclient.http import MediaFileUpload

    return MediaFileUpload(str(src), mimetype=MIME_MD)


def _md5(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()
