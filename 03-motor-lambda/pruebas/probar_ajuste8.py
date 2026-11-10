"""Prueba en AWS: negaciones, roles en la base, verificación definitiva y alias. Después: reiniciar_demo.sh --aplicar"""

import os
import re
import sys

import boto3

sys.path.insert(0, os.path.expanduser("~/fase4/pruebas"))
cf = boto3.client("cloudformation", region_name="us-east-1")
salidas = {o["OutputKey"]: o["OutputValue"] for o in
           cf.describe_stacks(StackName="se-rutinas-motor")["Stacks"][0]["Outputs"]}
sys.argv = [sys.argv[0], salidas["ApiUrl"], salidas["ClienteWebId"]]
import probar_api as P  # noqa: E402
from escenarios_api import Resultados, consulta_por_botones  # noqa: E402

resultados = []
NUEVA = {"descartar_pendiente": True}


def check(ok, texto, detalle=""):
    resultados.append(bool(ok))
    print(f"  {'OK   ' if ok else 'FALLO'} {texto}" + (f"  <- {str(detalle)[:300]}" if not ok else ""))


def api(metodo, ruta, cuenta, cuerpo=None):
    return P.api(metodo, ruta, cuenta, cuerpo)


def respuesta_p1(texto):
    st, c = api("POST", "/consultas", "andres", NUEVA)
    st, r = api("POST", f"/consultas/{c['id_consulta']}/mensajes", "andres", {"texto": texto})
    hecho = r["hechos"][0]["hecho"] if r.get("hechos") else None
    return r, hecho


print("==> Despertando la base"); api("POST", "/despertar", None)

print("\n==> 1. Negaciones en la pregunta de técnica (con Lex y Nova reales)")
for texto in ("No domino la tecnica", "No, sinceramente no domino la tecnica", "la verdad no la domino"):
    r, hecho = respuesta_p1(texto)
    check(hecho == "HC02", f"«{texto}» -> No ({(r.get('interpretacion') or {}).get('metodo')})",
          (hecho, r.get("interpretacion")))
for texto in ("nunca aprendí a hacerlos bien", "claro que no", "ni idea de cómo se hacen"):
    r, hecho = respuesta_p1(texto)
    pasos = [(p["metodo"], p.get("resultado"), p.get("descartado")) for p in
             (r.get("interpretacion") or {}).get("pasos", [])]
    check(hecho != "HC01", f"«{texto}» nunca queda como Sí -> {hecho or r.get('confirmar', {}).get('opcion') or 'pide aclarar'}",
          pasos)
r, hecho = respuesta_p1("Sí, los domino")
check(hecho == "HC01", "«Sí, los domino» sigue siendo Sí", hecho)
api("POST", f"/consultas/{r['id_consulta']}/descartar", "andres", {})

print("\n==> 2. El experto consulta la base en solo lectura")
st, b = api("GET", "/base-conocimiento", "cristian")
check(st == 200 and b.get("preguntas"), "Ve preguntas, opciones, rutinas y gránulos", st)
st, b = api("GET", "/base-conocimiento/validacion", "cristian")
check(st == 403, "No ejecuta el validador (es del ingeniero)", st)
st, b = api("GET", "/base-conocimiento/frases", "cristian")
check(st == 403, "No ve las frases por revisar (son del ingeniero)", st)
st, b = api("GET", "/base-conocimiento/validacion", "simon")
check(st == 200 and all(v["resultado"] != "FALLO" for v in b["validacion"]), "El ingeniero valida la base sin fallos", b)
st, f = api("GET", "/base-conocimiento/frases", "simon")
check(st == 200 and not any(x["frase"].lower().startswith("no domino") for x in f["frases"]),
      "«No domino la técnica» ya no aparece como frase por revisar (es sinónimo de No)", f)

print("\n==> 3. Verificación formal definitiva")
st, c, esperada = consulta_por_botones(api, "laura", "R25", Resultados())
idc = c.get("id_consulta")
st, v = api("POST", f"/consultas/{idc}/verificacion", "cristian")
check(st == 200 and v.get("resultado") == "VALID", f"El experto verifica la consulta: {v.get('resultado')}", v)
st, v2 = api("POST", f"/consultas/{idc}/verificacion", "simon")
check(st == 409, "Ya verificada: no se repite, ni por el ingeniero", (st, v2))
st, v2 = api("POST", f"/consultas/{idc}/verificacion", "cristian")
check(st == 409, "Ni por el mismo experto", st)
st, d = api("GET", f"/consultas/{idc}", "simon")
check(d.get("verificacion_formal") == "VALID", "El ingeniero ve el resultado guardado", d.get("verificacion_formal"))

print("\n==> 4. Alias legibles")
st, u = api("GET", "/usuarios", "diego")
raros = [x["alias"] for x in u.get("usuarios", []) if re.match(r"^usuario-[0-9a-f]{6}$", x["alias"])]
check(st == 200 and not raros, "Ningún perfil tiene un alias al azar", raros)

print(f"\n{sum(resultados)}/{len(resultados)} correctas")
print("Ahora deja los datos en cero: bash ~/limpieza/reiniciar_demo.sh --aplicar")
