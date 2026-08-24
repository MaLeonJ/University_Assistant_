import threading
from datetime import date, timedelta

from asistente.usage import format_usage, get_usage, register_call


def test_register_call_incrementa(usage_file):
    assert register_call() == 1
    assert register_call() == 2
    assert get_usage() == (2, 100)


def test_register_call_es_seguro_en_paralelo(usage_file):
    hilos = [threading.Thread(target=register_call) for _ in range(50)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    assert get_usage() == (50, 100)


def test_contador_se_reinicia_cada_dia(write_usage):
    ayer = str(date.today() - timedelta(days=1))
    write_usage(ayer, 50)
    assert register_call() == 1


def test_archivo_corrupto_arranca_de_cero(usage_file):
    usage_file.write_text("no es json")
    assert register_call() == 1


def test_format_usage_muestra_barra_y_porcentaje(write_usage):
    hoy = str(date.today())
    write_usage(hoy, 25)
    texto = format_usage()
    assert "█" in texto and "░" in texto
    assert "25%" in texto
    assert "75" in texto
