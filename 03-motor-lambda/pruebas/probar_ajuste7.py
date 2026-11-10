"""Prueba en AWS: una consulta abierta por perfil, descartar y numeración. Después: reiniciar_demo.sh --aplicar"""

import os
import sys

import boto3

sys.path.insert(0, os.path.expanduser("~/fase4/pruebas"))
cf = boto3.client("cloudformation", region_name="us-east-1")
salidas = {o["OutputKey"]: o["OutputValue"] for o in
           cf.describe_stacks(StackName="se-rutinas-motor")["Stacks"][0]["Outputs"]}
sys.argv = [sys.argv[0], salidas["ApiUrl"], salidas["ClienteWebId"]]
import probar_api as P  # noqa: E402

resultados = []


def check(ok, texto, detalle=""):
    resultados.append(bool(ok))
    print(f"  {'OK   ' if ok else 'FALLO'} {texto}" + (f"  <- {str(detalle)[:300]}" if not ok else ""))


def api(metodo, ruta, cuenta, cuerpo=None):
    return P.api(metodo, ruta, cuenta, cuerpo)


NUEVA = {"descartar_pendiente": True}

print("==> Despertando la base"); api("POST", "/despertar", None, None)

print("\n==> 1. Una sola consulta abierta por perfil")
st, a = api("POST", "/consultas", "andres", NUEVA)
check(st == 200, f"Andrés abre su consulta {a.get('numero')}", a)
st, r = api("POST", f"/consultas/{a['id_consulta']}/respuestas", "andres",
            {"id_respuesta": a["pregunta"]["opciones"][0]["id_respuesta"]})
st, b = api("POST", "/consultas", "andres", {})
check(st == 409 and b.get("pendiente", {}).get("id_consulta") == a["id_consulta"],
      "Con una abierta, pedir otra responde 409 y devuelve la pendiente", b)
check(b.get("pendiente", {}).get("respondidas") == 1, "La pendiente conserva su respuesta", b)
st, l = api("GET", "/consultas", "andres")
check(sum(x["estado"] == "en_curso" for x in l["consultas"]) == 1, "Andrés tiene exactamente una abierta",
      [x["estado"] for x in l["consultas"]])

print("\n==> 2. Descartar")
st, x = api("POST", f"/consultas/{a['id_consulta']}/descartar", "laura", {})
check(st in (403, 404), "Laura no puede descartar la consulta de Andrés", st)
st, x = api("POST", f"/consultas/{a['id_consulta']}/descartar", "cristian", {})
check(st == 403, "El experto no descarta consultas", st)
st, x = api("POST", f"/consultas/{a['id_consulta']}/descartar", "andres", {})
check(st == 200 and x.get("estado") == "abandonada" and len(x.get("hechos", [])) == 1,
      "Andrés la descarta y su respuesta queda guardada", x)
st, x = api("POST", f"/consultas/{a['id_consulta']}/respuestas", "andres", {"id_respuesta": 1})
check(st == 409, "Una descartada no admite respuestas", st)
st, x = api("POST", f"/consultas/{a['id_consulta']}/verificacion", "cristian", None)
check(st == 409, "Una descartada no se verifica con Automated Reasoning", st)
st, n = api("POST", "/consultas", "andres", {})
check(st == 200 and n.get("numero") == a["numero"] + 1, f"Empieza la siguiente: consulta {n.get('numero')}", n)
st, d = api("POST", "/consultas", "andres", NUEVA)
check(st == 200 and d.get("numero") == n["numero"] + 1, "«Descartarla y empezar otra» en un solo paso", d)
api("POST", f"/consultas/{d['id_consulta']}/descartar", "andres", {})

print("\n==> 3. Numeración propia de cada perfil")
st, l = api("POST", "/consultas", "laura", NUEVA)
check(st == 200, f"Laura abre la suya mientras Andrés tuvo las de él (número {l.get('numero')})", l)
api("POST", f"/consultas/{l['id_consulta']}/descartar", "laura", {})
for cuenta in ("andres", "laura"):
    st, lista = api("GET", "/consultas", cuenta)
    nums = sorted(x["numero"] for x in lista["consultas"])
    check(nums == list(range(1, len(nums) + 1)), f"{cuenta} ve sus consultas 1..{len(nums)}", nums)
st, lista = api("GET", "/consultas", "cristian")
por = {}
for x in lista["consultas"]:
    por.setdefault(x["alias"], []).append(x["numero"])
check(all(sorted(v) == list(range(1, len(v) + 1)) for v in por.values()),
      "El experto ve la numeración de cada perfil por separado", por)
st, det = api("GET", f"/consultas/{a['id_consulta']}", "cristian")
check(det.get("alias") and det.get("numero") == a["numero"], "El detalle trae el perfil y su número", det.get("alias"))

print("\n==> 4. Métricas")
todas = lista["consultas"]
st, m = api("GET", "/metricas", "cristian")
esperado = {"consultas": len(todas), "descartadas": sum(x["estado"] == "abandonada" for x in todas),
            "en_curso": sum(x["estado"] == "en_curso" for x in todas),
            "terminadas": sum(x["estado"] == "terminada" for x in todas)}
dif = {k: (m.get(k), v) for k, v in esperado.items() if m.get(k) != v}
check(st == 200 and not dif, "Las métricas cuentan las descartadas aparte", dif or m)

print(f"\n{sum(resultados)}/{len(resultados)} correctas")
print("Ahora deja los datos en cero: bash ~/limpieza/reiniciar_demo.sh --aplicar")
