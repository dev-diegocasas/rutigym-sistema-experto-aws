"""Pruebas locales de la Fase 3 con dobles de Lex, Nova y Automated Reasoning
(solo desarrollo: comprueban que el motor usa bien los servicios)."""

import json
import os
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "..", "motor"))
os.environ.update(DB_MODO="local", DB_NOMBRE="prueba", DB_SOCKET="/var/tmp/pgtest/.s.PGSQL.5499",
                  USAR_LEX="false", USAR_NOVA="false", USAR_AR="false")
import servicio  # noqa: E402
from escenarios import SIMON  # noqa: E402
from escenarios_ia import correr_ia  # noqa: E402


def llamar(accion, identidad, parametros):
    r = servicio.lambda_handler({"accion": accion, "identidad": identidad,
                                 "parametros": parametros}, None)
    return r["statusCode"], json.loads(r["body"])


_, kb = llamar("base_conocimiento", SIMON, {})
SINONIMOS = {p["atributo"]: [(o["codigo_hecho"], [o["texto_opcion"].lower(), o["valor"].lower()]
                              + o["sinonimos"]) for o in p["opciones"]] for p in kb["preguntas"]}


class LexFalso:
    def interpretar(self, id_consulta, atributo, texto):
        t = texto.lower()
        for codigo, frases in SINONIMOS[atributo]:
            if any(f in t for f in frases):
                return codigo, {"servicio": "Lex (doble de prueba)", "valor_reconocido": codigo}
        return None, {"servicio": "Lex (doble de prueba)", "valor_reconocido": None}


class NovaFalso:
    def mensaje_pregunta(self, ultimo, pregunta):
        return f"Perfecto, sigamos con: {pregunta['codigo']}"

    def explicacion(self, rutina, respaldo):
        return f"La rutina {rutina['codigo']} encaja con {len(respaldo)} de tus respuestas."


class VerificadorFalso:
    def verificar(self, hechos, codigo):
        from vocabulario_ar import enunciado_verificacion
        p, r = enunciado_verificacion(hechos, codigo)
        return "VALID", {"servicio": "AR (doble de prueba)", "pregunta": p, "respuesta": r}


class ClasificadorFalso:
    """Sin Nova: el clasificador no reconoce nada y deja la decisión a la cascada."""
    def clasificar(self, texto, pregunta, opciones, pendientes):
        return None


class IAFalsa:
    interprete, redactor, verificador = LexFalso(), NovaFalso(), VerificadorFalso()
    clasificador = ClasificadorFalso()


servicio.IA = IAFalsa()
sys.exit(1 if correr_ia(llamar) else 0)
