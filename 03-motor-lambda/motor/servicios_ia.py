"""CAPA DE DATOS · Fuentes externas de IA: Lex (texto), Nova (redacción y clasificación)
y Automated Reasoning (verificación formal). Todas fallan de forma segura."""

import json
import os
import time

from vocabulario_ar import enunciado_verificacion

BOT_NOMBRE = os.environ.get("LEX_BOT", "se-rutinas-nlu")
BOT_ALIAS = os.environ.get("LEX_ALIAS", "produccion")
LOCALE = os.environ.get("LEX_LOCALE", "es_419")
INTENT = "ResponderPregunta"
MODELO_NOVA = os.environ.get("MODELO_NOVA", "amazon.nova-micro-v1:0")
GUARDRAIL_NOMBRE = os.environ.get("GUARDRAIL", "se-rutinas-verificador")


def _activo(variable):
    return os.environ.get(variable, "true").lower() == "true"


def _cliente(servicio, timeout=5):
    import boto3
    from botocore.config import Config
    return boto3.client(servicio, config=Config(connect_timeout=3, read_timeout=timeout,
                                                retries={"max_attempts": 1}))


_cache = {}


# ---------------------------------------------------------------- Amazon Lex
class InterpreteLex:
    """Convierte la frase del usuario en el código del hecho (HC..) de la pregunta actual."""

    def _ids(self):
        if "lex" not in _cache:
            m = _cliente("lexv2-models")
            bot = m.list_bots(filters=[{"name": "BotName", "values": [BOT_NOMBRE],
                                        "operator": "EQ"}])["botSummaries"]
            if not bot:
                raise RuntimeError(f"No existe el bot {BOT_NOMBRE}")
            bot_id = bot[0]["botId"]
            alias = next((a for a in m.list_bot_aliases(botId=bot_id)["botAliasSummaries"]
                          if a["botAliasName"] == BOT_ALIAS), None)
            if alias is None:
                raise RuntimeError(f"El bot {BOT_NOMBRE} no tiene el alias '{BOT_ALIAS}'")
            _cache["lex"] = (bot_id, alias["botAliasId"])
        return _cache["lex"]

    def interpretar(self, id_consulta, atributo, texto):
        """Devuelve (codigo_hecho o None, detalle para la traza)."""
        if not _activo("USAR_LEX"):
            return None, {"servicio": "Lex", "estado": "desactivado"}
        try:
            bot_id, alias_id = self._ids()
            t0 = time.time()
            r = _cliente("lexv2-runtime").recognize_text(
                botId=bot_id, botAliasId=alias_id, localeId=LOCALE,
                sessionId=f"consulta-{id_consulta}", text=texto[:1024],
                sessionState={"dialogAction": {"type": "ElicitSlot", "slotToElicit": atributo},
                              "intent": {"name": INTENT, "state": "InProgress"}})
            slot = ((r.get("sessionState", {}).get("intent", {}).get("slots") or {})
                    .get(atributo) or {}).get("value") or {}
            codigo = slot.get("interpretedValue")
            return codigo, {"servicio": "Amazon Lex", "texto": texto,
                            "valor_reconocido": codigo, "original": slot.get("originalValue"),
                            "ms": int((time.time() - t0) * 1000)}
        except Exception as e:
            return None, {"servicio": "Amazon Lex", "error": f"{type(e).__name__}: {e}"[:200]}


# ---------------------------------------------------------------- Bedrock Nova
class RedactorNova:
    SISTEMA = ("Eres el asistente conversacional de un sistema experto de rutinas de "
               "entrenamiento. Escribes en español de Colombia, en tono cercano y profesional. "
               "Nunca inventas datos, ejercicios ni recomendaciones médicas, nunca sugieres cuál "
               "opción elegir y nunca contradices al sistema experto: solo redactas.")

    def _generar(self, instruccion, max_tokens):
        if not _activo("USAR_NOVA"):
            return None
        try:
            r = _cliente("bedrock-runtime", timeout=6).converse(
                modelId=MODELO_NOVA, system=[{"text": self.SISTEMA}],
                messages=[{"role": "user", "content": [{"text": instruccion}]}],
                inferenceConfig={"maxTokens": max_tokens, "temperature": 0.3})
            return r["output"]["message"]["content"][0]["text"].strip()
        except Exception as e:
            print("Nova no disponible:", f"{type(e).__name__}: {e}"[:300])
            return None

    def mensaje_pregunta(self, ultimo_hecho, pregunta):
        """Una frase de transición hacia la siguiente pregunta (el texto exacto de la
        pregunta y sus opciones los muestra la interfaz desde la base)."""
        contexto = (f"El usuario acaba de responder «{ultimo_hecho['respuesta']}» a la pregunta "
                    f"«{ultimo_hecho['texto_pregunta']}». " if ultimo_hecho else
                    "Es el inicio de la conversación; saluda brevemente. ")
        return self._generar(
            contexto + f"Escribe UNA sola frase corta (máximo 25 palabras) que reconozca la "
            f"respuesta y dé paso a la siguiente pregunta: «{pregunta['texto']}». "
            "No repitas la pregunta ni menciones opciones.", 80)

    def explicacion(self, rutina, respaldo):
        hechos = "; ".join(f"{h['texto_pregunta']} → {h['respuesta']}" for h in respaldo)
        return self._generar(
            f"El sistema experto concluyó la rutina {rutina['codigo']} (nivel {rutina['nivel']}, "
            f"probabilidad {rutina['probabilidad'] * 100:.1f} %): «{rutina['descripcion_rutina']}». "
            f"Respuestas del usuario que la respaldan: {hechos}. "
            "Explica en máximo 3 frases, dirigidas al usuario, por qué esta rutina encaja con "
            "sus respuestas. No agregues ejercicios ni cambies la rutina.", 220)


class ClasificadorNova:
    """Nova elige una opción de la pregunta actual cuando ni los sinónimos ni Lex entienden."""
    SISTEMA = ("Clasificas respuestas escritas por personas a un cuestionario de entrenamiento. "
               "Solo puedes elegir códigos de la lista que se te da. Si la frase no responde la "
               "pregunta o es ambigua, devuelves null. Fíjate en las negaciones: «no domino la técnica» "
               "significa lo contrario de «domino la técnica», y «claro que no» es una negación. "
               "Respondes únicamente con JSON válido.")

    @staticmethod
    def _bloque(pregunta, opciones):
        lineas = [f"{pregunta['codigo']} ({pregunta['atributo']}): {pregunta['texto']}"]
        for o in opciones:
            sin = ", ".join((o.get("sinonimos") or [])[:8])
            lineas.append(f"  - {o['codigo_hecho']}: {o['texto_opcion']}" + (f" (también: {sin})" if sin else ""))
        return "\n".join(lineas)

    def clasificar(self, texto, pregunta, opciones, pendientes):
        """Devuelve {"codigo", "confianza", "motivo", "otros": {atributo: (codigo, confianza)}} o None."""
        if not _activo("USAR_NOVA"):
            return None
        otras = "\n".join(self._bloque(p, o) for p, o in pendientes) or "(ninguna)"
        instruccion = (
            f"Pregunta actual:\n{self._bloque(pregunta, opciones)}\n\n"
            f"Otras preguntas que aún no se han hecho:\n{otras}\n\n"
            f"Respuesta escrita por la persona: «{texto[:300]}»\n\n"
            "Devuelve este JSON: {\"codigo\": código de la opción de la pregunta actual o null, "
            "\"confianza\": número entre 0 y 1, \"motivo\": frase corta en español, "
            "\"otros\": [{\"codigo\": código de una opción de las otras preguntas, \"confianza\": número}]}. "
            "En \"otros\" incluye solo datos que la persona dijo de forma explícita.")
        try:
            r = _cliente("bedrock-runtime", timeout=6).converse(
                modelId=MODELO_NOVA, system=[{"text": self.SISTEMA}],
                messages=[{"role": "user", "content": [{"text": instruccion}]}],
                inferenceConfig={"maxTokens": 200, "temperature": 0})
            crudo = r["output"]["message"]["content"][0]["text"]
            datos = json.loads(crudo[crudo.index("{"):crudo.rindex("}") + 1])
        except Exception as e:
            print("Clasificador Nova no disponible:", f"{type(e).__name__}: {e}"[:300])
            return None
        validos = {o["codigo_hecho"] for o in opciones}
        codigo = datos.get("codigo") if datos.get("codigo") in validos else None
        otros = {}
        for p, ops in pendientes:
            por_codigo = {o["codigo_hecho"] for o in ops}
            for x in datos.get("otros") or []:
                if isinstance(x, dict) and x.get("codigo") in por_codigo:
                    otros[p["atributo"]] = (x["codigo"], float(x.get("confianza") or 0))
        return {"codigo": codigo, "confianza": float(datos.get("confianza") or 0) if codigo else 0.0,
                "motivo": str(datos.get("motivo") or "")[:160], "otros": otros}


# ---------------------------------------------------------------- Automated Reasoning
class VerificadorFormal:
    def _guardrail(self):
        if "guardrail" not in _cache:
            br = _cliente("bedrock")
            g = next((g for g in br.list_guardrails(maxResults=100)["guardrails"]
                      if g["name"] == GUARDRAIL_NOMBRE), None)
            if g is None:
                raise RuntimeError(f"No existe el guardrail {GUARDRAIL_NOMBRE}")
            versiones = br.list_guardrails(guardrailIdentifier=g["id"], maxResults=100)["guardrails"]
            numericas = sorted((v["version"] for v in versiones if v["version"].isdigit()), key=int)
            _cache["guardrail"] = (g["id"], numericas[-1] if numericas else "DRAFT")
        return _cache["guardrail"]

    def verificar(self, hechos, codigo_hipotesis):
        """Devuelve (resultado, detalle). resultado: VALID, INVALID, SATISFIABLE, ..."""
        if not _activo("USAR_AR"):
            return "DESACTIVADO", {}
        pregunta, respuesta = enunciado_verificacion(hechos, codigo_hipotesis)
        detalle = {"servicio": "Bedrock Automated Reasoning", "pregunta": pregunta,
                   "respuesta": respuesta}
        try:
            gid, version = self._guardrail()
            t0 = time.time()
            r = _cliente("bedrock-runtime", timeout=20).apply_guardrail(
                guardrailIdentifier=gid, guardrailVersion=version, source="OUTPUT",
                outputScope="FULL",
                content=[{"text": {"text": pregunta, "qualifiers": ["query"]}},
                         {"text": {"text": respuesta, "qualifiers": ["guard_content"]}}])
            detalle["ms"] = int((time.time() - t0) * 1000)
            hallazgos = []
            for a in r.get("assessments", []):
                hallazgos += (a.get("automatedReasoningPolicy") or {}).get("findings", [])
            if not hallazgos:
                return "SIN_HALLAZGOS", detalle
            orden = ["translationAmbiguous", "impossible", "invalid", "satisfiable", "valid",
                     "tooComplex", "noTranslations"]
            tipos = [next(iter(h)) for h in hallazgos]
            peor = min(tipos, key=lambda t: orden.index(t) if t in orden else 99)
            h = next(h[peor] for h in hallazgos if peor in h)
            reglas = h.get("supportingRules") or h.get("contradictingRules") or []
            detalle.update({
                "reglas": [(x.get("identifier") or "").replace("REGLA", "").lstrip("0")
                           for x in reglas],
                "premisas": [p.get("logic") for p in (h.get("translation") or {}).get("premises", [])],
                "afirmaciones": [c.get("logic") for c in (h.get("translation") or {}).get("claims", [])],
                "confianza": (h.get("translation") or {}).get("confidence")})
            nombres = {"translationAmbiguous": "TRANSLATION_AMBIGUOUS", "tooComplex": "TOO_COMPLEX",
                       "noTranslations": "NO_TRANSLATIONS"}
            return nombres.get(peor, peor.upper()), detalle
        except Exception as e:
            detalle["error"] = str(e)[:300]
            return "ERROR", detalle
