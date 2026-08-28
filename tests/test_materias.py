import asistente.materias as materias


def test_materias_vacias_por_defecto(tmp_path, monkeypatch):
    arch = tmp_path / "materias.json"
    monkeypatch.setattr(materias, "MATERIAS_FILE", arch)
    assert materias.get_materias() == []
    assert materias.get_materia_activa() is None


def test_agregar_y_activar_materia(tmp_path, monkeypatch):
    arch = tmp_path / "materias.json"
    monkeypatch.setattr(materias, "MATERIAS_FILE", arch)

    assert materias.agregar_materia("Teoría de Sistemas") is True
    assert materias.get_materias() == ["Teoría de Sistemas"]
    assert materias.get_materia_activa() == "Teoría de Sistemas"

    assert materias.agregar_materia("Bases de Datos") is True
    assert len(materias.get_materias()) == 2
    # Sigue activa la primera a menos que se cambie
    assert materias.get_materia_activa() == "Teoría de Sistemas"

    # Intentar duplicado
    assert materias.agregar_materia("Bases de Datos") is False

    # Cambiar activa
    assert materias.set_materia_activa("Bases de Datos") is True
    assert materias.get_materia_activa() == "Bases de Datos"

    # Cambiar activa a inexistente
    assert materias.set_materia_activa("Física") is False


def test_eliminar_materia(tmp_path, monkeypatch):
    arch = tmp_path / "materias.json"
    monkeypatch.setattr(materias, "MATERIAS_FILE", arch)

    materias.agregar_materia("Teoría de Sistemas")
    materias.agregar_materia("Bases de Datos")
    materias.set_materia_activa("Teoría de Sistemas")

    assert materias.eliminar_materia("Teoría de Sistemas") is True
    assert materias.get_materias() == ["Bases de Datos"]
    # Al eliminar la activa, pasa a la primera disponible
    assert materias.get_materia_activa() == "Bases de Datos"

    assert materias.eliminar_materia("Bases de Datos") is True
    assert materias.get_materias() == []
    assert materias.get_materia_activa() is None
