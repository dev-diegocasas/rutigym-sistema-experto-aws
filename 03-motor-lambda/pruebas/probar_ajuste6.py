"""Prueba en AWS: interpretación de texto, numeración y métricas. Después: reiniciar_demo.sh --aplicar"""

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


def api(m, r, c, b=None):
    return P.api(m, r, c, b)


print("==> Despertando la base"); api("POST", "/despertar", None, None)

print("\n==> 1. Interpretación de respuestas escritas")
st, c = api("POST", "/consultas", "andres", {"descartar_pendiente": True})
check(st == 200 and c.get("numero"), f"Consulta creada con número visible {c.get('numero')}", c)
i = c["id_consulta"]
check(bool(c["pregunta"].get("ejemplos")), "La pregunta trae ejemplos para escribir", c["pregunta"])
st, r = api("POST", f"/consultas/{i}/mensajes", "andres", {"texto": "Sii, claro"})
check(st == 200 and r.get("interpretacion", {}).get("metodo") == "sinonimos",
      "«Sii, claro» se entiende con los sinónimos de la base", r.get("interpretacion") or r)
st, r = api("POST", f"/consultas/{i}/mensajes", "andres",
            {"texto": "hace como 3 años que voy al gimnasio y lo que busco es ser más fuerte"})
via = (r.get("interpretacion") or {}).get("metodo")
check(st == 200 and not r.get("no_entendido"), f"Mensaje largo entendido (con {via})", r.get("mensaje"))
print("     sugerencias para preguntas futuras:", {k: v["opcion"] for k, v in (r.get("sugerencias") or {}).items()})
if r.get("pregunta"):
    st, r2 = api("POST", f"/consultas/{i}/mensajes", "andres", {"texto": "pues la idea es que me vea más musculoso"})
    if r2.get("confirmar"):
        print(f"     Nova pidió confirmar: «{r2['confirmar']['opcion']}» ({r2['confirmar']['motivo']})")
        check(True, "Con confianza media pide confirmar")
    else:
        m = (r2.get("interpretacion") or {})
        check(st == 200, f"Frase indirecta: {('entendida con ' + m.get('metodo', '?')) if not r2.get('no_entendido') else 'no entendida'}",
              r2.get("mensaje"))
st, r = api("POST", f"/consultas/{i}/mensajes", "andres", {"texto": "xyz qwerty"})
check(st == 200 and (r.get("no_entendido") or r.get("confirmar") is None),
      "Un texto sin sentido no se registra como respuesta", r.get("mensaje"))
pasos = [p["metodo"] for p in (r.get("interpretacion") or {}).get("pasos", [])]
check(pasos == ["sinonimos", "lex", "nova"], f"Pasó por la cascada completa {pasos}", r.get("interpretacion"))

print("\n==> 2. Numeración visible")
st, l = api("GET", "/consultas", "andres")
nums = sorted(x["numero"] for x in l["consultas"])
check(nums == list(range(1, len(nums) + 1)), f"Andrés ve sus consultas numeradas {nums}", nums)
st, l = api("GET", "/consultas", "cristian")
nums = sorted(x["numero"] for x in l["consultas"])
check(nums == list(range(1, len(nums) + 1)), f"El experto ve un consecutivo global sin saltos ({len(nums)})", nums)

print("\n==> 3. Métricas por rol (contra la lista de consultas)")
lista = l["consultas"]
esperado = {"consultas": len(lista),
            "terminadas": sum(x["estado"] == "terminada" for x in lista),
            "en_curso": sum(x["estado"] == "en_curso" for x in lista),
            "pendientes_verificar": sum(x["estado"] == "terminada" and not x["verificacion_formal"] for x in lista),
            "verificadas_valid": sum(x["verificacion_formal"] == "VALID" for x in lista)}
for cuenta in ("cristian", "simon", "diego"):
    st, m = api("GET", "/metricas", cuenta)
    dif = {k: (m.get(k), v) for k, v in esperado.items() if m.get(k) != v}
    ok = st == 200 and not dif and sum(h["veces"] for h in m["por_hipotesis"]) == m["terminadas"]
    if ok and m["validaciones"]:
        ok = abs(m["concordancia_experto"] - m["de_acuerdo"] / m["validaciones"]) < 1e-4
    check(ok, f"Métricas de {cuenta} correctas", dif or m)
st, m = api("GET", "/metricas", "laura")
check(st == 403, "El usuario final no ve métricas", st)

print("\n==> 4. Frases por revisar")
st, f = api("GET", "/base-conocimiento/frases", "simon")
check(st == 200, f"El ingeniero ve {len(f.get('frases', []))} frases por revisar", f)
st, f = api("GET", "/base-conocimiento/frases", "laura")
check(st == 403, "El usuario final no las ve", st)

print(f"\n{sum(resultados)}/{len(resultados)} correctas")
print("Ahora deja los datos en cero: bash ~/limpieza/reiniciar_demo.sh --aplicar")
