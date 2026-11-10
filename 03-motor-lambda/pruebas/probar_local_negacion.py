"""Prueba local de negaciones con un Lex de prueba que se equivoca a propósito."""

import json
import os
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "..", "motor"))
os.environ.update(DB_MODO="local", DB_NOMBRE="prueba", DB_SOCKET="/var/tmp/pgtest/.s.PGSQL.5499",
                  USAR_LEX="false", USAR_NOVA="false", USAR_AR="false")
import servicio  # noqa: E402
from escenarios import LAURA, NUEVA  # noqa: E402

resultados = []


def check(ok, texto, detalle=""):
    resultados.append(bool(ok))
    print(f"  {'OK   ' if ok else 'FALLO'} {texto}" + (f"  <- {str(detalle)[:300]}" if not ok else ""))


def llamar(accion, identidad, parametros):
    r = servicio.lambda_handler({"accion": accion, "identidad": identidad,
                                 "parametros": parametros}, None)
    return r["statusCode"], json.loads(r["body"])


class LexDistraido:
    """Como el Lex real: ve «domino» o «técnica» y responde Sí, aunque haya un «no»."""
    def interpretar(self, id_consulta, atributo, texto):
        return "HC01", {"servicio": "Lex (doble)"}       # estas pruebas solo responden P1


class NovaFijo:
    respuesta = None

    def clasificar(self, texto, pregunta, opciones, pendientes):
        if self.respuesta is None:
            return None
        codigo, confianza = self.respuesta
        return {"codigo": codigo, "confianza": confianza, "motivo": "doble de prueba", "otros": {}}

    def mensaje_pregunta(self, ultimo, pregunta):
        return None

    def explicacion(self, rutina, respaldo):
        return None


nova = NovaFijo()
servicio.IA.interprete = LexDistraido()
servicio.IA.clasificador = nova
servicio.IA.redactor = nova


def primera_respuesta(texto, nova_dice=None):
    nova.respuesta = nova_dice
    st, c = llamar("iniciar_consulta", LAURA, NUEVA)
    assert c["pregunta"]["codigo"] == "P1", c["pregunta"]
    st, r = llamar("responder_texto", LAURA, {"id_consulta": c["id_consulta"], "texto": texto})
    hecho = r["hechos"][0]["hecho"] if r.get("hechos") else None
    return st, r, hecho


print("Negaciones en la pregunta de técnica (P1)")
for texto in ("No domino la tecnica", "No, sinceramente no domino la tecnica", "no los domino",
              "no tengo buena técnica", "la verdad no la domino"):
    st, r, hecho = primera_respuesta(texto)
    check(st == 200 and hecho == "HC02" and r["interpretacion"]["metodo"] == "sinonimos",
          f"«{texto}» -> No (sin pasar por Lex)", (hecho, r.get("interpretacion")))

for texto in ("Sí, los domino", "claro, domino la técnica", "no sé si los domino"):
    st, r, hecho = primera_respuesta(texto)
    esperado = "HC03" if texto.startswith("no sé") else "HC01"
    check(st == 200 and hecho == esperado, f"«{texto}» -> {esperado}", (hecho, r.get("interpretacion")))

st, r, hecho = primera_respuesta("nunca aprendí a hacerlos bien", ("HC02", 0.9))
pasos = r.get("interpretacion", {}).get("pasos", [])
check(hecho == "HC02" and any(p.get("descartado") for p in pasos if p["metodo"] == "lex"),
      "Lex dice Sí ante una negación: se descarta y decide Nova (No)", (hecho, pasos))

st, r, hecho = primera_respuesta("claro que no", ("HC02", 0.9))
check(hecho == "HC02", "«claro que no» -> No (la palabra «claro» no basta)", (hecho, r.get("interpretacion")))

st, r, hecho = primera_respuesta("nunca aprendí a hacerlos bien", ("HC01", 0.95))
check(hecho is None and r.get("confirmar", {}).get("opcion") == "Sí, los domino",
      "Si Nova también dice Sí ante una negación, se pide confirmar en vez de registrarlo", r.get("confirmar"))

st, r, hecho = primera_respuesta("no domino nada de eso", ("HC01", 0.95))
check(hecho in (None, "HC02") and not (hecho == "HC01"), "Nunca se registra «Sí» para una frase negada", hecho)

print(f"\n{sum(resultados)}/{len(resultados)} correctas")
sys.exit(0 if all(resultados) else 1)
