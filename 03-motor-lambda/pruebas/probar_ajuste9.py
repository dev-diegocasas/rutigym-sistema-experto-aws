"""Prueba en AWS: modelo sin ciclos y opiniones de varios expertos. Después: reiniciar_demo.sh --aplicar"""

import os
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


def check(ok, texto, detalle=""):
    resultados.append(bool(ok))
    print(f"  {'OK   ' if ok else 'FALLO'} {texto}" + (f"  <- {str(detalle)[:300]}" if not ok else ""))


def api(metodo, ruta, cuenta, cuerpo=None):
    return P.api(metodo, ruta, cuenta, cuerpo)


print("==> Despertando la base"); api("POST", "/despertar", None)

print("\n==> 1. Consulta completa (la pregunta de cada respuesta sale del hecho)")
st, c, esperada = consulta_por_botones(api, "laura", "R25", Resultados())
check(st == 200 and c.get("estado") == "terminada" and c["diagnostico"]["rutina"]["codigo"] == esperada,
      f"Laura termina una consulta -> {esperada}", c)
idc = c.get("id_consulta")
check(len({h["pregunta"] for h in c.get("hechos", [])}) == len(c.get("hechos", [])),
      "Una respuesta por pregunta", c.get("hechos"))

print("\n==> 2. Opiniones de varios expertos")
st, v = api("POST", f"/consultas/{idc}/validacion", "cristian", {"de_acuerdo": True, "comentario": "De acuerdo"})
check(st == 200, "Cristian da su opinión", v)
st, v = api("POST", f"/consultas/{idc}/validacion", "profesor", {"de_acuerdo": False, "comentario": "Bajaría el volumen"})
check(st == 200 and sorted(x["experto"] for x in v["validaciones"]) == ["cristian", "profesor"],
      "El profesor da la suya sobre la misma consulta", v)
st, v = api("POST", f"/consultas/{idc}/validacion", "cristian", {"de_acuerdo": True, "comentario": "Lo confirmo"})
check(st == 200 and len(v["validaciones"]) == 2, "Cristian corrige la suya sin duplicarla", v)
st, b = api("GET", f"/consultas/{idc}", "laura")
check(st == 200 and "validaciones" not in b
      and all(t["tipo"] != "validacion_experto" for t in b.get("traza", [])),
      "Laura no ve las opiniones de los expertos", b.get("traza"))
st, v = api("POST", f"/consultas/{idc}/validacion", "simon", {"de_acuerdo": True})
check(st == 403, "El ingeniero no opina como experto", st)

print("\n==> 3. Métricas")
st, m = api("GET", "/metricas", "cristian")
check(st == 200 and m["validaciones"] >= 2 and m["consultas_con_opinion"] >= 1,
      f"Concordancia con {m.get('validaciones')} opiniones: {m.get('concordancia_experto')}", m)

print(f"\n{sum(resultados)}/{len(resultados)} correctas")
print("Ahora deja los datos en cero: bash ~/limpieza/reiniciar_demo.sh --aplicar")
