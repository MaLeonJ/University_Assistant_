import hashlib
from pathlib import Path

import pytest

import asistente.drive as drive
from asistente.drive import DriveError, estado, sync_drive, sync_text, texto_configuracion


class FakeRequest:
    def __init__(self, valor):
        self._valor = valor

    def execute(self):
        return self._valor


class FakeDrive:
    """Modelo mínimo de la API v3: carpetas y archivos .md con md5 real."""

    def __init__(self, fallar=False):
        self.carpetas: dict[str, dict] = {}
        self.archivos: dict[str, dict] = {}
        self._n = 0
        self.fallar = fallar

    def nueva_carpeta(self, nombre: str, parent: str) -> str:
        self._n += 1
        fid = f"C{self._n}"
        self.carpetas[fid] = {"name": nombre, "parent": parent}
        return fid

    def _hijos(self, folder_id: str) -> list[dict]:
        items = [
            {"id": cid, "name": c["name"], "mimeType": drive.MIME_CARPETA}
            for cid, c in self.carpetas.items()
            if c["parent"] == folder_id
        ]
        items += [
            {
                "id": aid,
                "name": a["name"],
                "mimeType": drive.MIME_MD,
                "md5Checksum": a["md5"],
            }
            for aid, a in self.archivos.items()
            if a["parent"] == folder_id
        ]
        return items

    @staticmethod
    def _md5_de(media) -> str:
        ruta = Path(media._filename)
        return hashlib.md5(ruta.read_bytes()).hexdigest()

    def files(self):
        return self

    def list(self, q=None, fields=None, pageSize=None, pageToken=None):
        folder_id = q.split("'")[1]
        return FakeRequest({"files": self._hijos(folder_id)})

    def create(self, body=None, media_body=None, fields=None):
        if self.fallar:
            raise RuntimeError("quota exceeded")

        def ejecutar():
            if body.get("mimeType") == drive.MIME_CARPETA:
                fid = self.nueva_carpeta(body["name"], body["parents"][0])
                return {"id": fid}
            self._n += 1
            aid = f"F{self._n}"
            self.archivos[aid] = {
                "name": body["name"],
                "parent": body["parents"][0],
                "md5": self._md5_de(media_body),
            }
            return {"id": aid}

        return FakeRequest(ejecutar())

    def update(self, fileId=None, media_body=None):
        if self.fallar:
            raise RuntimeError("quota exceeded")

        def ejecutar():
            self.archivos[fileId]["md5"] = self._md5_de(media_body)
            return {"id": fileId}

        return FakeRequest(ejecutar())


@pytest.fixture
def remoto(monkeypatch, tmp_path):
    """Drive configurado con carpeta raíz RAIZ y biblioteca temporal."""
    cred = tmp_path / "credentials.json"
    token = tmp_path / "data" / "token.json"
    monkeypatch.setattr(drive, "GDRIVE_FOLDER_ID", "RAIZ")
    monkeypatch.setattr(drive, "GDRIVE_CREDENTIALS_FILE", cred)
    monkeypatch.setattr(drive, "GDRIVE_TOKEN_FILE", token)
    fake = FakeDrive()
    monkeypatch.setattr(drive, "_servicio", lambda: fake)
    return fake


def crear_biblioteca(out: Path) -> None:
    mes = out / "2026" / "08-agosto"
    mes.mkdir(parents=True)
    (mes / "a.md").write_text("contenido A", encoding="utf-8")


# ---------- estado() ----------


def test_estado_sin_folder_id(monkeypatch):
    monkeypatch.setattr(drive, "GDRIVE_FOLDER_ID", "")
    assert "GDRIVE_FOLDER_ID" in (estado() or "")


def test_estado_sin_credentials(monkeypatch, tmp_path):
    monkeypatch.setattr(drive, "GDRIVE_FOLDER_ID", "RAIZ")
    monkeypatch.setattr(drive, "GDRIVE_CREDENTIALS_FILE", tmp_path / "credentials.json")
    assert "credentials.json" in (estado() or "")


def test_estado_sin_token(monkeypatch, tmp_path):
    monkeypatch.setattr(drive, "GDRIVE_FOLDER_ID", "RAIZ")
    monkeypatch.setattr(drive, "GDRIVE_CREDENTIALS_FILE", tmp_path / "c.json")
    (tmp_path / "c.json").write_text("{}")
    monkeypatch.setattr(drive, "GDRIVE_TOKEN_FILE", tmp_path / "data" / "t.json")
    assert "drive-auth" in (estado() or "")


def test_estado_listo(monkeypatch, tmp_path, remoto):
    cred = tmp_path / "credentials.json"
    cred.write_text("{}")
    token = tmp_path / "data" / "token.json"
    token.parent.mkdir(parents=True, exist_ok=True)
    token.write_text("{}")
    monkeypatch.setattr(drive, "GDRIVE_CREDENTIALS_FILE", cred)
    monkeypatch.setattr(drive, "GDRIVE_TOKEN_FILE", token)
    assert estado() is None


# ---------- sync_drive ----------


def test_sync_inicial_sube_todo_y_crea_carpetas(output_dirs, remoto):
    crear_biblioteca(output_dirs["out"])
    r = sync_drive()
    assert r == {"nuevos": 1, "actualizados": 0, "total": 1}
    assert len(remoto.carpetas) == 2  # 2026 y 08-agosto


def test_sync_es_incremental(output_dirs, remoto):
    crear_biblioteca(output_dirs["out"])
    assert sync_drive()["nuevos"] == 1
    assert sync_drive() == {"nuevos": 0, "actualizados": 0, "total": 1}


def test_sync_detecta_contenido_modificado(output_dirs, remoto):
    crear_biblioteca(output_dirs["out"])
    sync_drive()
    doc = output_dirs["out"] / "2026" / "08-agosto" / "a.md"
    doc.write_text("versión nueva", encoding="utf-8")
    assert sync_drive()["actualizados"] == 1
    md5s = [a["md5"] for a in remoto.archivos.values()]
    assert md5s == [hashlib.md5(b"versi\xc3\xb3n nueva").hexdigest()]


def test_sync_respeta_estructura_de_carpetas(output_dirs, remoto):
    crear_biblioteca(output_dirs["out"])
    sync_drive()
    anio = next(fid for fid, c in remoto.carpetas.items() if c["name"] == "2026")
    mes = next(fid for fid, c in remoto.carpetas.items() if c["name"] == "08-agosto")
    assert remoto.carpetas[mes]["parent"] == anio
    archivo = next(iter(remoto.archivos.values()))
    assert archivo["parent"] == mes


def test_sync_nunca_borra_del_destino(output_dirs, remoto):
    viejo = remoto.nueva_carpeta("2026", "RAIZ")
    remoto.archivos["VIEJO"] = {"name": "viejo.md", "parent": viejo, "md5": "x"}
    crear_biblioteca(output_dirs["out"])
    sync_drive()
    assert "VIEJO" in remoto.archivos


def test_sync_reusa_carpetas_existentes(output_dirs, remoto):
    anio = remoto.nueva_carpeta("2026", "RAIZ")
    remoto.nueva_carpeta("08-agosto", anio)
    crear_biblioteca(output_dirs["out"])
    r = sync_drive()
    assert r["nuevos"] == 1
    assert len(remoto.carpetas) == 2


def test_sync_sin_directorio_origen(output_dirs, remoto):
    assert sync_drive() == {"nuevos": 0, "actualizados": 0, "total": 0}


def test_api_rota_lanza_driveerror(output_dirs, remoto):
    remoto.fallar = True
    crear_biblioteca(output_dirs["out"])
    with pytest.raises(DriveError, match="quota"):
        sync_drive()


# ---------- textos ----------


def test_sync_text_reporte():
    texto = sync_text({"nuevos": 2, "actualizados": 1, "total": 3})
    assert "Drive" in texto and "3" in texto


def test_sync_text_vacio():
    assert "No hay documentos" in sync_text({"nuevos": 0, "actualizados": 0, "total": 0})


def test_texto_configuracion_incluye_motivo_y_pasos():
    texto = texto_configuracion("Falta GDRIVE_FOLDER_ID en .env")
    assert "Falta GDRIVE_FOLDER_ID" in texto
    assert "drive-auth" in texto
