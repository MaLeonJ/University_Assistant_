from asistente.parser import parse_message, slugify


def test_mensaje_vacio_devuelve_none():
    assert parse_message("") is None
    assert parse_message("   ") is None


def test_formato_titulo_y_temas():
    parsed = parse_message("temario corte 1: bases de datos, modelo E-R, normalización")
    assert parsed == ("temario corte 1", ["bases de datos", "modelo E-R", "normalización"])


def test_separadores_punto_coma_y_salto_de_linea():
    parsed = parse_message("corte 2: sql; joins\níndices")
    assert parsed == ("corte 2", ["sql", "joins", "índices"])


def test_temas_sin_titulo_generan_titulo_generico():
    parsed = parse_message("normalización, índices")
    assert parsed == ("Investigación", ["normalización", "índices"])


def test_un_solo_titulo_usa_primeras_palabras_como_titulo():
    parsed = parse_message("qué es la normalización de bases de datos y para qué sirve")
    assert parsed is not None
    titulo, temas = parsed
    assert titulo == "qué es la normalización de bases"
    assert len(temas) == 1


def test_titulo_vacio_devuelve_none():
    assert parse_message(": tema") is None
    assert parse_message("   : tema") is None


def test_lista_vacia_devuelve_none():
    assert parse_message("título: , ,") is None


def test_limpia_espacios_y_puntos_de_cada_tema():
    parsed = parse_message("t: .- a ., - b -")
    assert parsed == ("t", ["a", "b"])


def test_slugify_quita_acentos_y_enie():
    assert slugify("Qué es la Ñandú? Íbamos!") == "que-es-la-nandu-ibamos"


def test_slugify_trunca_a_sesenta():
    slug = slugify("a" * 100)
    assert len(slug) <= 60


def test_slugify_vacio_usa_default():
    assert slugify("!!!") == "documento"
