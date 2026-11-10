"""Escenarios de la API por rol; corren en local (eventos simulados) o contra AWS."""

import json
import os
import statistics
import time

NUEVA = {"descartar_pendiente": True}   # descarta lo que dejó a medias otra prueba

AQUI = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(AQUI, "reglas_arbol.json"), encoding="utf-8") as f:
    REGLAS = {r: (h, [tuple(c) for c in conds]) for r, h, conds in json.load(f)}


class Resultados:
    def __init__(self):
        self.filas, self.tiempos = [], []

    def check(self, ok, descripcion, detalle=""):
        self.filas.append(bool(ok))
        print(f"  {'OK   ' if ok else 'FALLO'} {descripcion}"
              + (f"  ← {str(detalle)[:200]}" if not ok and detalle else ""), flush=True)


def consulta_por_botones(api, cuenta, regla, res):
    esperada, conds = REGLAS[regla]
    perfil = dict(conds)
    st, kb = api("GET", "/base-conocimiento", "simon", None)
    texto_de = {o["valor"]: o["texto_opcion"] for p in kb["preguntas"] for o in p["opciones"]}
    t0 = time.time()
    st, c = api("POST", "/consultas", cuenta, NUEVA)
    res.tiempos.append(time.time() - t0)
    while st == 200 and c.get("estado") == "en_curso":
        p = c["pregunta"]
        opcion = next(o for o in p["opciones"] if o["texto"] == texto_de[perfil[p["atributo"]]])
        t0 = time.time()
        st, c = api("POST", f"/consultas/{c['id_consulta']}/respuestas", cuenta,
                    {"id_respuesta": opcion["id_respuesta"]})
        res.tiempos.append(time.time() - t0)
    return st, c, esperada


def correr_api(api, real=False):
    res = Resultados()

    print("\n1. Acceso a la API")
    st, b = api("POST", "/despertar", None, None)
    res.check(st == 200, "La ruta pública /despertar responde sin token")
    if real:
        st, b = api("GET", "/perfil", None, None)
        res.check(st == 401, "Sin token: 401 (lo rechaza API Gateway)", st)
        st, b = api("GET", "/perfil", "token-falso", None)
        res.check(st == 401, "Con un token inventado: 401", st)
    for cuenta, rol in [("diego", "administrador"), ("simon", "ingeniero_conocimiento"),
                        ("cristian", "experto"), ("laura", "usuario_final")]:
        st, b = api("GET", "/perfil", cuenta, None)
        res.check(st == 200 and b.get("rol") == rol, f"{cuenta} entra con su token como {rol}",
                  b)
    st, b = api("GET", "/ruta-que-no-existe", "laura", None)
    res.check(st == 404, "Ruta inexistente: 404", st)

    print("\n2. Usuario final")
    st, c, esperada = consulta_por_botones(api, "laura", "R25", res)
    ok = st == 200 and c.get("estado") == "terminada"
    res.check(ok and c["diagnostico"]["rutina"]["codigo"] == esperada,
              f"Laura completa una consulta por botones → {esperada}", c)
    id_laura = c.get("id_consulta")
    st, b = api("GET", f"/consultas/{id_laura}", "andres", None)
    res.check(st == 404, "Andrés no puede ver la consulta de Laura", st)
    st, b = api("GET", "/consultas", "andres", None)
    res.check(st == 200 and all(x["alias"] == "andres" for x in b["consultas"]),
              "El historial de Andrés solo trae sus consultas")
    st, b = api("GET", "/base-conocimiento", "laura", None)
    res.check(st == 403, "El usuario final no ve la base de conocimiento completa", st)
    st, b = api("POST", f"/consultas/{id_laura}/validacion", "laura", {"de_acuerdo": True})
    res.check(st == 403, "El usuario final no puede validar diagnósticos", st)

    print("\n2b. Una consulta abierta por perfil")
    st, abierta = api("POST", "/consultas", "laura", NUEVA)
    st, otra = api("POST", "/consultas", "laura", {})
    res.check(st == 409 and otra.get("pendiente", {}).get("id_consulta") == abierta.get("id_consulta"),
              "Con una consulta abierta no se crea otra: 409 con la pendiente", otra)
    st, b = api("POST", f"/consultas/{abierta['id_consulta']}/descartar", "andres", {})
    res.check(st in (403, 404), "Andrés no puede descartar la consulta de Laura", st)
    st, b = api("POST", f"/consultas/{abierta['id_consulta']}/descartar", "cristian", {})
    res.check(st == 403, "El experto no descarta consultas", st)
    st, b = api("POST", f"/consultas/{abierta['id_consulta']}/descartar", "laura", {})
    res.check(st == 200 and b.get("estado") == "abandonada", "Laura descarta su consulta abierta", b)
    st, b = api("POST", f"/consultas/{abierta['id_consulta']}/respuestas", "laura",
                {"id_respuesta": abierta["pregunta"]["opciones"][0]["id_respuesta"]})
    res.check(st == 409, "Una consulta descartada no admite respuestas", st)
    st, b = api("POST", f"/consultas/{abierta['id_consulta']}/verificacion", "cristian", None)
    res.check(st == 409, "Una consulta descartada no se verifica", st)
    st, nueva = api("POST", "/consultas", "laura", {})
    res.check(st == 200 and nueva.get("numero") == abierta.get("numero") + 1,
              "Después de descartarla puede empezar otra con el número siguiente", nueva)
    api("POST", f"/consultas/{nueva.get('id_consulta')}/descartar", "laura", {})
    st, b = api("GET", "/consultas", "cristian", None)
    por = {}
    for x in b.get("consultas", []):
        por.setdefault(x["alias"], []).append(x["numero"])
    res.check(st == 200 and all(sorted(v) == list(range(1, len(v) + 1)) for v in por.values()),
              "Cada perfil tiene su propia numeración 1, 2, 3…", por)

    print("\n3. Experto humano")
    st, v = api("POST", f"/consultas/{id_laura}/verificacion", "cristian", None)
    res.check(st == 200 and v.get("resultado") == "VALID",
              "Cristian verifica formalmente la consulta de Laura: VALID", v.get("resultado") or v)
    st, v = api("POST", f"/consultas/{id_laura}/verificacion", "simon", None)
    res.check(st == 409, "La verificación es definitiva: no se repite (ni el ingeniero)", st)
    st, b = api("GET", "/base-conocimiento/validacion", "cristian", None)
    res.check(st == 403, "El experto no ejecuta el validador (es del ingeniero)", st)
    st, b = api("GET", "/base-conocimiento/frases", "cristian", None)
    res.check(st == 403, "Las frases por revisar son del ingeniero", st)
    st, b = api("GET", "/base-conocimiento", "cristian", None)
    res.check(st == 200 and b.get("preguntas"), "El experto sí consulta la base en solo lectura", st)
    st, v = api("POST", f"/consultas/{id_laura}/validacion", "cristian",
                {"de_acuerdo": True, "comentario": "Coincide con mi criterio"})
    res.check(st == 200 and v["validaciones"][-1]["experto"] == "cristian",
              "Cristian valida el diagnóstico (de acuerdo)", v)
    st, v = api("POST", f"/consultas/{id_laura}/validacion", "cristian", {"de_acuerdo": "sí"})
    res.check(st == 400, "Una validación mal formada se rechaza", st)
    st, m = api("GET", "/metricas", "cristian", None)
    res.check(st == 200 and m.get("concordancia_experto") is not None,
              f"Métricas: concordancia con el experto = {m.get('concordancia_experto')}", m)
    st, b = api("GET", f"/consultas/{id_laura}", "cristian", None)
    res.check(st == 200 and b.get("validaciones") and "correo" not in json.dumps(b.get("validaciones")),
              "El experto ve la consulta con su validación, sin datos personales")
    st, b = api("PUT", "/base-conocimiento/granulos", "cristian",
                {"hecho": "HC08", "hipotesis": "H21", "peso": 0.5})
    res.check(st == 403, "El experto no puede modificar el conocimiento", st)

    print("\n4. Ingeniero del conocimiento")
    st, b = api("PUT", "/base-conocimiento/granulos", "simon",
                {"hecho": "HC08", "hipotesis": "H21", "peso": 0.82})
    res.check(st == 200 and not b.get("validacion"), "Simón ajusta el peso HC08→H21 a 0,82", b)
    st, kb = api("GET", "/base-conocimiento", "simon", None)
    peso = next((g["peso"] for g in kb.get("granulos", [])
                 if g["hecho"] == "HC08" and g["hipotesis"] == "H21"), None)
    res.check(peso == 0.82, "El cambio se ve de inmediato, sin redesplegar (RNF-04)", peso)
    st, b = api("PUT", "/base-conocimiento/granulos", "simon",
                {"hecho": "HC08", "hipotesis": "H21", "peso": 0.80})
    res.check(st == 200, "Simón restaura el peso a 0,80")
    st, b = api("PUT", "/base-conocimiento/granulos", "simon", {"hecho": "HC07", "hipotesis": "H21"})
    res.check(st == 400 and "no corresponde" in b.get("error", ""),
              "Un gránulo incoherente se rechaza con el motivo", b)
    st, b = api("PUT", "/base-conocimiento/granulos", "simon",
                {"hecho": "HC08", "hipotesis": "H21", "peso": 1.5})
    res.check(st == 400, "Un peso fuera de rango se rechaza", b)
    st, b = api("DELETE", "/base-conocimiento/hechos/HC01", "simon", None)
    res.check(st == 400, "No se puede borrar un hecho que respalda hipótesis", b)
    st, b = api("GET", "/usuarios", "simon", None)
    res.check(st == 403, "El ingeniero no gestiona usuarios", st)

    print("\n5. Administrador")
    st, b = api("GET", "/usuarios", "diego", None)
    res.check(st == 200 and len(b.get("usuarios", [])) >= 7, "Diego lista los usuarios", b)
    st, b = api("GET", "/auditoria", "diego", None)
    res.check(st == 200 and any(a["usuario_app"] and "simon" in a["usuario_app"]
                                and a["tabla"] == "hechos_hipotesis" for a in b.get("auditoria", [])),
              "La auditoría registra los cambios de Simón con su correo")
    correo = f"prueba-api-{int(time.time())}@sistema-experto.test"
    st, b = api("POST", "/usuarios", "diego", {"correo": correo, "nombre": "Prueba API",
                                                "rol": "experto"})
    res.check(st == 200 and b.get("contrasena_temporal"),
              "Diego crea una cuenta de experto (contraseña temporal)", b)
    nuevo = b.get("id_usuario")
    st, b = api("PUT", f"/usuarios/{nuevo}/rol", "diego", {"rol": "ingeniero_conocimiento"})
    res.check(st == 200 and b["usuario"]["rol"] == "ingeniero_conocimiento",
              "Diego le cambia el rol (también en Cognito)", b)
    st, b = api("PUT", f"/usuarios/{nuevo}/estado", "diego", {"activo": False})
    res.check(st == 200 and b["usuario"]["activo"] is False, "Diego desactiva la cuenta", b)
    st, perfil = api("GET", "/perfil", "diego", None)
    st, b = api("PUT", f"/usuarios/{perfil.get('id_usuario')}/rol", "diego", {"rol": "experto"})
    res.check(st == 400 and "propio rol" in b.get("error", ""),
              "Diego no puede cambiar su propio rol", b)
    st, b = api("POST", "/usuarios", "diego", {"correo": "no-es-correo", "nombre": "X",
                                                "rol": "experto"})
    res.check(st == 400, "Un correo no válido se rechaza", st)
    st, b = api("PUT", "/base-conocimiento/granulos", "diego",
                {"hecho": "HC08", "hipotesis": "H21", "peso": 0.8})
    res.check(st == 403, "El administrador no modifica el conocimiento", st)

    if res.tiempos:
        t = sorted(res.tiempos)
        p95 = t[max(int(len(t) * 0.95) - 1, 0)]
        print(f"\n6. Rendimiento por HTTPS: {len(t)} peticiones · mediana "
              f"{statistics.median(t) * 1000:.0f} ms · p95 {p95 * 1000:.0f} ms")
        res.check(p95 <= 3.0, "RNF-03: el 95 % de las respuestas tarda 3 s o menos")

    fallos = res.filas.count(False)
    print(f"\n{len(res.filas) - fallos}/{len(res.filas)} correctas"
          + (" · TODO CORRECTO" if not fallos else f" · {fallos} FALLOS"))
    return fallos, correo
