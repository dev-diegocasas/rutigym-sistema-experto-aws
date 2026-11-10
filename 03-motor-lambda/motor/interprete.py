"""CAPA DE NEGOCIO · Entiende respuestas escritas con los sinónimos de la base (sin servicios externos)."""

import re
import unicodedata
from difflib import SequenceMatcher

NEGACIONES = {"no", "ni", "nunca", "sin", "tampoco"}
NEGATIVAS = {"no"}                       # valor de la opción que niega en una pregunta de sí o no


# ---------------------------------------------------------------- normalización del texto
def normalizar(texto):
    t = unicodedata.normalize("NFD", str(texto or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return " ".join(t.split())


def frases(opcion):
    """Formas conocidas de una opción: su valor, su texto y sus sinónimos."""
    salida = {normalizar(opcion.get("valor")), normalizar(opcion.get("texto_opcion"))}
    salida |= {normalizar(s) for s in (opcion.get("sinonimos") or [])}
    salida.discard("")
    return salida


# ---------------------------------------------------------------- negaciones y pausas
def _con_pausas(texto):
    """Palabras normalizadas conservando las pausas (comas, puntos...) como «|»."""
    t = unicodedata.normalize("NFD", str(texto or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = re.sub(r"[,.;:!?¡¿()]+", " | ", t)
    return re.sub(r"[^a-z0-9|]+", " ", t).split()


def _negada(pausas, indice):
    """True si hay una negación hasta tres palabras antes, en la misma frase."""
    pos, n = None, -1
    for i, tok in enumerate(pausas):
        if tok != "|":
            n += 1
            if n == indice:
                pos = i
                break
    if pos is None:
        return False
    vistas = 0
    for tok in reversed(pausas[:pos]):
        if tok in ("|", "pero") or vistas == 3:
            break
        if tok in NEGACIONES:
            return True
        vistas += 1
    return False


def _cruza_pausa(pausas, indice, largo):
    """True si las `largo` palabras desde `indice` están separadas por una pausa:
    en «No. Domino la técnica» no se lee «no domino la técnica»."""
    n, dentro = -1, False
    for tok in pausas:
        if tok == "|":
            if dentro:
                return True
            continue
        n += 1
        if n == indice:
            dentro = True
        if n >= indice + largo - 1 and dentro:
            return False
    return False


def _indice(texto, inicio):
    return len(texto[:inicio].split())


# ---------------------------------------------------------------- coincidencia con las opciones
def _coincidencias(texto, opcion, pausas):
    """Lista de (puntaje, largo, frase, tipo) de una opción frente al texto."""
    salida = []
    palabras = texto.split()
    for f in frases(opcion):
        if texto == f and not _cruza_pausa(pausas, 0, len(f.split())):
            salida.append((1.0, len(f), f, "exacta"))
            continue
        m = re.search(rf"(?<![a-z0-9]){re.escape(f)}(?![a-z0-9])", texto)
        if m and _cruza_pausa(pausas, _indice(texto, m.start()), len(f.split())):
            m = None
        if m:
            if len(f) < 3:
                # Una frase corta ("no", "si") solo cuenta si abre la respuesta: «no, la verdad...»
                if m.start() == 0:
                    salida.append((0.8, len(f), f, "inicia"))
            elif not (f.split()[0] not in NEGACIONES and _negada(pausas, _indice(texto, m.start()))):
                salida.append((0.9, len(f), f, "contiene"))
            continue
        # Errores de tipeo: ventana del mismo número de palabras que la frase
        n = len(f.split())
        if len(f) >= 5:
            for i in range(0, max(1, len(palabras) - n + 1)):
                ventana = " ".join(palabras[i:i + n])
                if SequenceMatcher(None, ventana, f).ratio() >= 0.86:
                    salida.append((0.8, len(f), f, "parecida"))
                    break
    return salida


def negadas(texto, opciones):
    """Códigos de las opciones que el texto menciona negadas: «no domino la técnica»
    niega «domino la técnica». Sirven para no aceptar esa opción venga de donde venga."""
    t, pausas = normalizar(texto), _con_pausas(texto)
    salida = set()
    for o in opciones:
        for f in frases(o):
            if len(f) < 3 or f.split()[0] in NEGACIONES:
                continue
            for m in re.finditer(rf"(?<![a-z0-9]){re.escape(f)}(?![a-z0-9])", t):
                if _negada(pausas, _indice(t, m.start())):
                    salida.add(o["codigo_hecho"])
    return salida


def tiene_negacion(texto):
    return any(p in NEGACIONES for p in normalizar(texto).split())


def es_afirmativa(opcion):
    return normalizar(opcion.get("valor")) in {"si", "sí"}


def interpretar(texto, opciones):
    """Devuelve {"opcion", "confianza", "motivo", "metodo"} o None si no hay una opción clara."""
    t = normalizar(texto)
    if not t:
        return None
    excluidas = negadas(texto, opciones)
    pausas = _con_pausas(texto)
    mejores = []
    for o in opciones:
        if o["codigo_hecho"] in excluidas:
            continue
        c = _coincidencias(t, o, pausas)
        if c:
            mejores.append((max(c), o))
    if not mejores:
        # Pregunta de sí o no: negar la opción afirmativa equivale a responder «No»
        negativa = next((o for o in opciones if normalizar(o.get("valor")) in NEGATIVAS), None)
        afirmativas = [o["codigo_hecho"] for o in opciones if es_afirmativa(o)]
        if negativa and afirmativas and set(afirmativas) <= excluidas:
            return {"opcion": negativa, "confianza": 0.85, "metodo": "sinonimos",
                    "motivo": "niega la opción afirmativa"}
        return None
    # Una coincidencia contenida en otra más larga de otra opción no cuenta ("no" frente a "no se")
    mejores.sort(key=lambda x: (x[0][0], x[0][1]), reverse=True)
    (puntaje, _, frase, tipo), opcion = mejores[0]
    for (p2, _, f2, _), o2 in mejores[1:]:
        if o2 is opcion or f" {f2} " in f" {frase} ":
            continue
        if round(p2, 2) >= round(puntaje - 0.05, 2):
            return None                     # dos opciones igual de probables: que decida otro
    motivos = {"exacta": f"coincide con «{frase}»", "contiene": f"menciona «{frase}»",
               "inicia": f"empieza con «{frase}»", "parecida": f"se parece a «{frase}»"}
    return {"opcion": opcion, "confianza": round(puntaje, 2), "motivo": motivos[tipo], "metodo": "sinonimos"}


# ---------------------------------------------------------------- datos adelantados para otras preguntas
def detectar_otros(texto, preguntas_pendientes):
    """Datos que el usuario mencionó para preguntas que aún no llegan.
    preguntas_pendientes: [(pregunta, opciones)]. Solo coincidencias fuertes."""
    sugeridas = {}
    for pregunta, opciones in preguntas_pendientes:
        r = interpretar(texto, opciones)
        if r and r["confianza"] >= 0.9:
            sugeridas[pregunta["atributo"]] = r
    return sugeridas
