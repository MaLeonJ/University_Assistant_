import asistente.cache as cache
from asistente.searcher import SearchResult

R = [SearchResult(title="T", url="https://x.com", snippet="s")]


def test_busqueda_roundtrip(cache_db_tmp):
    assert cache.get_search("tema") is None
    cache.put_search("tema", R)
    assert cache.get_search("tema") == R


def test_ttl_expira(cache_db_tmp, monkeypatch):
    cache.put_search("tema", R)
    real_time = cache.time.time
    monkeypatch.setattr(cache.time, "time", lambda: real_time() + 8 * 86400)
    assert cache.get_search("tema") is None


def test_analisis_roundtrip(cache_db_tmp):
    key = cache.analysis_key("tema", R, "gemini", "m1")
    assert cache.get_analysis(key) is None
    cache.put_analysis(key, "TEXTO")
    assert cache.get_analysis(key) == "TEXTO"


def test_clave_cambia_con_fuentes_proveedor_o_modelo():
    otras = [SearchResult(title="T", url="https://y.com", snippet="s")]
    base = cache.analysis_key("tema", R, "gemini", "m1")
    assert cache.analysis_key("tema", otras, "gemini", "m1") != base
    assert cache.analysis_key("tema", R, "openrouter", "m1") != base
    assert cache.analysis_key("tema", R, "gemini", "m2") != base


def test_clave_ignora_orden_de_fuentes():
    a = [SearchResult("t1", "https://a.com", "s"), SearchResult("t2", "https://b.com", "s")]
    b = list(reversed(a))
    assert cache.analysis_key("t", a, "p", "m") == cache.analysis_key("t", b, "p", "m")


def test_bd_corrupta_degrada_sin_explotar(cache_db_tmp):
    cache_db_tmp.write_text("no es sqlite")
    assert cache.get_search("tema") is None
    assert cache.get_analysis("k") is None
