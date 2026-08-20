import hashlib
import shutil

from .config import OBSIDIAN_DIR, OUTPUT_DIR


def sync_documents() -> dict[str, int]:
    if not OUTPUT_DIR.exists():
        return {"nuevos": 0, "actualizados": 0, "total": 0}

    OBSIDIAN_DIR.mkdir(parents=True, exist_ok=True)

    nuevos = 0
    actualizados = 0
    total = 0

    for src in sorted(OUTPUT_DIR.rglob("*.md")):
        rel = src.relative_to(OUTPUT_DIR)
        dst = OBSIDIAN_DIR / rel
        total += 1

        if _igual(src, dst):
            continue
        estado = "actualizado" if dst.exists() else "nuevo"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        if estado == "nuevo":
            nuevos += 1
        else:
            actualizados += 1

    return {
        "nuevos": nuevos,
        "actualizados": actualizados,
        "total": total,
    }


def sync_text(resultado: dict[str, int]) -> str:
    destino = f"`{OBSIDIAN_DIR}`"
    if resultado["total"] == 0:
        return f"📭 No hay documentos para sincronizar.\n\n🎯 Destino: {destino}"

    lineas = [
        "🔄 *Sincronización completada*\n",
        f"✨ Nuevos: *{resultado['nuevos']}*",
        f"♻️ Actualizados: *{resultado['actualizados']}*",
        f"📚 Total en biblioteca: {resultado['total']}",
        "",
        f"🎯 Destino: {destino}",
    ]
    return "\n".join(lineas)


def _igual(src, dst) -> bool:
    try:
        if src.stat().st_size != dst.stat().st_size:
            return False
        return _md5(src) == _md5(dst)
    except OSError:
        return False


def _md5(path) -> str:
    h = hashlib.md5()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()
