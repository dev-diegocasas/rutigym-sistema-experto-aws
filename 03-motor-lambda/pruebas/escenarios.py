"""Escenarios del motor; corren igual en local o contra la Lambda."""

import json
import os
import statistics
import time

AQUI = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(AQUI, "reglas_arbol.json"), encoding="utf-8") as f:
    REGLAS = [(r, h, [tuple(c) for c in conds]) for r, h, conds in json.load(f)]


# Cada perfil puede tener una sola consulta abierta: las pruebas que empiezan una
# consulta nueva descartan la que hubiera quedado a medias de una prueba anterior
NUEVA = {"descartar_pendiente": True}


def ident(alias, grupo):
    return {"sub": f"pendiente-cognito-{alias}", "correo": f"{alias}@sistema-experto.test",
            "grupo": grupo, "nombre": alias}


LAURA = ident("laura", "usuario_final")
ANDRES = ident("andres", "usuario_final")
VALENTINA = ident("valentina", "usuario_final")
CRISTIAN = ident("cristian", "experto")
SIMON = ident("simon", "ingeniero_conocimiento")
DIEGO = ident("diego", "administrador")
AUTOMATICO = {"sub": "prueba-automatica-1", "correo": "automatica@sistema-experto.test",
              "grupo": "usuario_final", "nombre": "Prueba automática"}


class Resultados:
    def __init__(self):
        self.filas = []
        self.tiempos = []

    def check(self, ok, descripcion, detalle=""):
        self.filas.append((bool(ok), descripcion, detalle))
        print(f"  {'OK   ' if ok else 'FALLO'} {descripcion}" + (f"  ← {detalle}" if not ok and detalle else ""),
              flush=True)


def consulta_completa(llamar, identidad, perfil, res=None):
    """Recorre una consulta respondiendo según el perfil. Devuelve (estado final, preguntas)."""
    t0 = time.time()
    st, cuerpo = llamar("iniciar_consulta", identidad, NUEVA)
    if res is not None:
        res.tiempos.append(time.time() - t0)
    if st != 200:
        return None, [], cuerpo
    preguntas = []
    while cuerpo.get("estado") == "en_curso" and cuerpo.get("pregunta"):
        p = cuerpo["pregunta"]
        preguntas.append(p["atributo"])
        valor = perfil.get(p["atributo"])
        if valor is None:
            return cuerpo, preguntas, f"se preguntó {p['atributo']}, que no está en el camino"
        # La interfaz solo conoce el texto de la opción; buscamos por el valor en la base
        opcion = next((o for o in p["opciones"] if _coincide(o["texto"], valor)), None)
        t0 = time.time()
        st, cuerpo = llamar("responder", identidad,
                            {"id_consulta": cuerpo["id_consulta"], "id_respuesta": opcion["id_respuesta"]})
        if res is not None:
            res.tiempos.append(time.time() - t0)
        if st != 200:
            return None, preguntas, cuerpo
    return cuerpo, preguntas, None


_VALOR_A_TEXTO = {}


def _coincide(texto_opcion, valor):
    return _VALOR_A_TEXTO.get(valor) == texto_opcion


def cargar_textos(llamar):
    st, kb = llamar("base_conocimiento", SIMON, {})
    for p in kb["preguntas"]:
        for o in p["opciones"]:
            _VALOR_A_TEXTO[o["valor"]] = o["texto_opcion"]
    return kb


def correr(llamar, completo=True):
    res = Resultados()

    print("\n1. Acceso y perfiles")
    st, b = llamar("despertar", LAURA, {})
    res.check(st == 200, "La base responde (despertar)")
    st, b = llamar("perfil", DIEGO, {})
    res.check(st == 200 and b.get("rol") == "administrador", "Diego se identifica como administrador")
    st, b = llamar("perfil", AUTOMATICO, {})
    res.check(st == 200 and b.get("rol") == "usuario_final",
              "Un usuario nuevo se registra solo como usuario final")
    st, b = llamar("perfil", {**CRISTIAN, "grupo": "administrador"}, {})
    res.check(st == 403, "Una sesión con un rol distinto al registrado es rechazada")
    st, b = llamar("perfil", {"sub": "desconocido-experto", "grupo": "experto"}, {})
    res.check(st == 403, "Nadie se auto-registra como experto")

    kb = cargar_textos(llamar)
    res.check(len(kb.get("hipotesis", [])) == 32 and len(kb.get("granulos", [])) == 160,
              "El ingeniero consulta la base de conocimiento (32 hipótesis, 160 gránulos)")

    print("\n2. Razonamiento: caminos del árbol a través del servicio")
    reglas = REGLAS if completo else [r for r in REGLAS if r[0] in ("R01", "R13", "R25", "R33", "R45")]
    for regla, esperada, conds in reglas:
        perfil = dict(conds)
        final, preguntas, error = consulta_completa(llamar, AUTOMATICO, perfil, res)
        ok = (final is not None and error is None and final.get("estado") == "terminada"
              and final["diagnostico"]["rutina"]["codigo"] == esperada
              and preguntas == [a for a, _ in conds]
              and len(final["ranking"]) == 5)
        detalle = error or (final and final.get("diagnostico", {}).get("rutina", {}).get("codigo"))
        res.check(ok, f"{regla} → {esperada} con {len(preguntas)} preguntas, top 5 guardado", detalle)

    print("\n3. Consulta de Laura: traza, explicación y aislamiento")
    perfil = dict(next(c for r, h, c in REGLAS if r == "R25"))
    final, _, error = consulta_completa(llamar, LAURA, perfil)
    idc = final["id_consulta"] if final else None
    res.check(final and final["diagnostico"]["rutina"]["codigo"] == "H21", "Laura obtiene H21", error)
    res.check(final and len(final["diagnostico"]["respaldo"]) == 5,
              "La explicación lista los 5 hechos que respaldan la rutina")
    st, b = llamar("obtener_consulta", LAURA, {"id": idc})
    tipos = {t["tipo"] for t in b.get("traza", [])}
    res.check(st == 200 and {"respuesta", "seleccion_pregunta", "conclusion"} <= tipos,
              "La traza guarda respuestas, selección de preguntas y conclusión")
    st, b = llamar("obtener_consulta", ANDRES, {"id": idc})
    res.check(st == 404, "Andrés NO puede ver la consulta de Laura (seguridad por fila)")
    st, b = llamar("obtener_consulta", CRISTIAN, {"id": idc})
    res.check(st == 200 and "traza" in b, "El experto Cristian sí la ve, con su traza")
    st, b = llamar("listar_consultas", ANDRES, {})
    res.check(st == 200 and all(c["alias"] == "andres" for c in b["consultas"]),
              "El historial de Andrés solo contiene sus consultas")

    print("\n4. Reglas del servicio")
    st, b = llamar("iniciar_consulta", CRISTIAN, NUEVA)
    res.check(st == 403, "El experto no puede hacer consultas como usuario final")
    st, b = llamar("base_conocimiento", LAURA, {})
    res.check(st == 403, "El usuario final no accede a la base de conocimiento completa")
    st, b = llamar("validar_base", SIMON, {})
    res.check(st == 200 and all(v["resultado"] != "FALLO" for v in b["validacion"]),
              "El ingeniero ejecuta el validador: sin fallos")
    st, b = llamar("validar_base", CRISTIAN, {})
    res.check(st == 403, "El validador es del ingeniero: el experto solo consulta la base")
    st, b = llamar("responder", LAURA, {"id_consulta": idc, "id_respuesta": 1})
    res.check(st == 409, "No se puede responder una consulta terminada")
    st, nueva = llamar("iniciar_consulta", ANDRES, NUEVA)
    otra = next(o for o in kb["preguntas"][2]["opciones"])["id_respuesta"]   # opción de P3
    st, b = llamar("responder", ANDRES, {"id_consulta": nueva["id_consulta"], "id_respuesta": otra})
    res.check(st == 400, "No se puede responder una pregunta que no es la actual")
    st, b = llamar("responder", LAURA, {"id_consulta": nueva["id_consulta"],
                                         "id_respuesta": nueva["pregunta"]["opciones"][0]["id_respuesta"]})
    res.check(st in (403, 404), "Laura no puede responder la consulta de Andrés")

    if res.tiempos:
        t = sorted(res.tiempos)
        p95 = t[int(len(t) * 0.95) - 1]
        print(f"\n5. Rendimiento: {len(t)} peticiones · mediana {statistics.median(t) * 1000:.0f} ms · "
              f"p95 {p95 * 1000:.0f} ms · máx {t[-1] * 1000:.0f} ms")
        res.check(p95 <= 3.0, "RNF-03: el 95 % de las respuestas tarda 3 s o menos")

    fallos = sum(not ok for ok, _, _ in res.filas)
    print(f"\n{len(res.filas) - fallos}/{len(res.filas)} correctas"
          + (" · TODO CORRECTO" if not fallos else f" · {fallos} FALLOS"))
    return fallos
