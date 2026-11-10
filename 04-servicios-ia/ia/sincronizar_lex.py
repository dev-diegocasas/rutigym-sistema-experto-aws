"""Construye el bot de Lex desde la base: un slot por pregunta, valores = hechos, sinónimos de la base.
Uso: python3 ia/sincronizar_lex.py"""

import json
import sys
import time

import boto3
from botocore.exceptions import ClientError

from conexion import REGION, preguntas_y_opciones

BOT = "se-rutinas-nlu"
ROL = "se-rutinas-lex-rol"
LOCALE = "es_419"
INTENT = "ResponderPregunta"
ALIAS = "produccion"
EXPRESIONES = {   # frases típicas que envuelven la respuesta, por pregunta
    "tecnica_dominada": ["{s}", "creo que {s}", "pues {s}"],
    "tiempo_entrenando": ["{s}", "llevo {s}", "entreno hace {s}", "hace {s}", "desde hace {s}"],
    "equipo_disponible": ["{s}", "entreno {s}", "tengo {s}", "voy al {s}", "en el {s}"],
    "objetivo_principal": ["{s}", "quiero {s}", "busco {s}", "mi objetivo es {s}"],
    "fase_priorizada": ["{s}", "prefiero {s}", "quiero priorizar {s}"],
    "dias_semana": ["{s}", "puedo {s}", "entreno {s}", "tengo {s}"],
    "actividad_actual": ["{s}", "soy {s}", "estoy {s}", "me considero {s}"],
}

lex = boto3.client("lexv2-models", region_name=REGION)
rt = boto3.client("lexv2-runtime", region_name=REGION)
iam = boto3.client("iam")


def esperar(fn, campo, deseados, limite=900, malos=("Failed",)):
    inicio = time.time()
    while time.time() - inicio < limite:
        try:
            r = fn()
        except lex.exceptions.ResourceNotFoundException:
            # Recién creado: Lex tarda unos segundos en mostrar el recurso
            time.sleep(5)
            continue
        if r[campo] in deseados:
            return r
        if r[campo] in malos:
            raise RuntimeError(f"{campo}={r[campo]}: {r.get('failureReasons')}")
        time.sleep(5)
    raise TimeoutError(f"{campo} no llegó a {deseados}")


def rol_lex():
    confianza = {"Version": "2012-10-17", "Statement": [{
        "Effect": "Allow", "Principal": {"Service": "lexv2.amazonaws.com"},
        "Action": "sts:AssumeRole"}]}
    try:
        arn = iam.create_role(RoleName=ROL, AssumeRolePolicyDocument=json.dumps(confianza),
                              Description="Rol del bot de Lex del sistema experto")["Role"]["Arn"]
        time.sleep(10)
        return arn
    except iam.exceptions.EntityAlreadyExistsException:
        return iam.get_role(RoleName=ROL)["Role"]["Arn"]


def bot_id(arn_rol):
    b = lex.list_bots(filters=[{"name": "BotName", "values": [BOT], "operator": "EQ"}])["botSummaries"]
    if b:
        return b[0]["botId"]
    bid = lex.create_bot(botName=BOT, roleArn=arn_rol, dataPrivacy={"childDirected": False},
                         idleSessionTTLInSeconds=600,
                         description="Interpreta las respuestas en lenguaje natural del "
                                     "sistema experto de rutinas")["botId"]
    esperar(lambda: lex.describe_bot(botId=bid), "botStatus", {"Available"})
    return bid


def sinonimos_de(opcion):
    vistos, salida = set(), []
    for s in [opcion["texto_opcion"], opcion["valor"]] + list(opcion["sinonimos"] or []):
        s = s.lower().strip()[:140]
        if s and s not in vistos and s != opcion["codigo_hecho"].lower():
            vistos.add(s)
            salida.append({"value": s})
    return salida


def main():
    preguntas, _ = preguntas_y_opciones()
    print(f"Base de conocimiento: {len(preguntas)} preguntas, "
          f"{sum(len(p['opciones']) for p in preguntas)} opciones")
    bid = bot_id(rol_lex())
    comun = {"botId": bid, "botVersion": "DRAFT", "localeId": LOCALE}
    try:
        lex.describe_bot_locale(**comun)
    except ClientError:
        lex.create_bot_locale(nluIntentConfidenceThreshold=0.40,
                              description="Español latinoamericano", **comun)
    esperar(lambda: lex.describe_bot_locale(**comun), "botLocaleStatus",
            {"NotBuilt", "Built", "ReadyExpressTesting"})

    # Tipos de slot (uno por pregunta)
    existentes = {t["slotTypeName"]: t["slotTypeId"]
                  for t in lex.list_slot_types(maxResults=100, **comun)["slotTypeSummaries"]}
    tipos = {}
    for p in preguntas:
        nombre = "Tipo_" + p["atributo"]
        spec = {"slotTypeName": nombre, "description": p["texto"][:200],
                "valueSelectionSetting": {"resolutionStrategy": "TopResolution"},
                "slotTypeValues": [{"sampleValue": {"value": o["codigo_hecho"]},
                                    "synonyms": sinonimos_de(o)} for o in p["opciones"]], **comun}
        if nombre in existentes:
            lex.update_slot_type(slotTypeId=existentes[nombre], **spec)
            tipos[p["atributo"]] = existentes[nombre]
        else:
            tipos[p["atributo"]] = lex.create_slot_type(**spec)["slotTypeId"]
    print(f"Tipos de slot: {len(tipos)}")

    # Intent único con un slot por pregunta
    intents = {i["intentName"]: i["intentId"]
               for i in lex.list_intents(maxResults=100, **comun)["intentSummaries"]}
    iid = intents.get(INTENT) or lex.create_intent(
        intentName=INTENT, sampleUtterances=[{"utterance": "quiero responder"}], **comun)["intentId"]
    slots = {s["slotName"]: s["slotId"]
             for s in lex.list_slots(intentId=iid, maxResults=100, **comun)["slotSummaries"]}
    prioridades, frases = [], []
    for n, p in enumerate(preguntas, start=1):
        spec = {"slotName": p["atributo"], "slotTypeId": tipos[p["atributo"]], "intentId": iid,
                "valueElicitationSetting": {
                    "slotConstraint": "Optional",
                    "promptSpecification": {"maxRetries": 1, "messageGroups": [
                        {"message": {"plainTextMessage": {"value": p["texto"]}}}]}}, **comun}
        if p["atributo"] in slots:
            lex.update_slot(slotId=slots[p["atributo"]], **spec)
            sid = slots[p["atributo"]]
        else:
            sid = lex.create_slot(**spec)["slotId"]
        prioridades.append({"priority": n, "slotId": sid})
        for e in EXPRESIONES.get(p["atributo"], ["{s}"]):
            frases.append({"utterance": e.format(s="{" + p["atributo"] + "}")})
    lex.update_intent(intentId=iid, intentName=INTENT, sampleUtterances=frases,
                      slotPriorities=prioridades,
                      description="Respuesta del usuario a la pregunta que elija el motor", **comun)
    print(f"Intent {INTENT}: {len(prioridades)} slots, {len(frases)} expresiones de ejemplo")

    print("Construyendo el modelo de lenguaje (1-5 min)...", flush=True)
    lex.build_bot_locale(**comun)
    esperar(lambda: lex.describe_bot_locale(**comun), "botLocaleStatus", {"Built"})

    version = lex.create_bot_version(botId=bid, botVersionLocaleSpecification={
        LOCALE: {"sourceBotVersion": "DRAFT"}})["botVersion"]
    esperar(lambda: lex.describe_bot_version(botId=bid, botVersion=version),
            "botStatus", {"Available"})
    alias = next((a for a in lex.list_bot_aliases(botId=bid)["botAliasSummaries"]
                  if a["botAliasName"] == ALIAS), None)
    ajustes = {"botAliasName": ALIAS, "botVersion": version, "botId": bid,
               "botAliasLocaleSettings": {LOCALE: {"enabled": True}},
               "description": "Versión que usa el motor de inferencia"}
    if alias:
        lex.update_bot_alias(botAliasId=alias["botAliasId"], **ajustes)
        alias_id = alias["botAliasId"]
    else:
        alias_id = lex.create_bot_alias(**ajustes)["botAliasId"]
    esperar(lambda: lex.describe_bot_alias(botId=bid, botAliasId=alias_id),
            "botAliasStatus", {"Available"})
    print(f"Versión {version} publicada en el alias '{ALIAS}'")

    # Prueba rápida con frases naturales
    pruebas = [("tecnica_dominada", "la verdad no", "HC02"),
               ("tiempo_entrenando", "llevo como tres años", "HC06"),
               ("equipo_disponible", "voy al gym", "HC08"),
               ("objetivo_principal", "quiero bajar de peso", "HC12"),
               ("fase_priorizada", "prefiero cargas altas", "HC15"),
               ("dias_semana", "solo los fines de semana", "HC16"),
               ("actividad_actual", "trabajo sentado todo el día", "HC18")]
    aciertos = 0
    for atributo, frase, esperado in pruebas:
        r = rt.recognize_text(botId=bid, botAliasId=alias_id, localeId=LOCALE,
                              sessionId=f"sincronizacion-{int(time.time())}", text=frase,
                              sessionState={"dialogAction": {"type": "ElicitSlot",
                                                             "slotToElicit": atributo},
                                            "intent": {"name": INTENT, "state": "InProgress"}})
        valor = (((r.get("sessionState", {}).get("intent", {}).get("slots") or {})
                  .get(atributo) or {}).get("value") or {}).get("interpretedValue")
        aciertos += valor == esperado
        print(f"   {'OK   ' if valor == esperado else 'FALLO'} [{atributo}] «{frase}» → {valor}")
    print(f"LEX: {aciertos}/{len(pruebas)} frases interpretadas correctamente")
    return 0 if aciertos == len(pruebas) else 1


if __name__ == "__main__":
    sys.exit(main())
