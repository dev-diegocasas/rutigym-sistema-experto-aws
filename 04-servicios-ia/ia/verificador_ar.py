"""Crea la política de Automated Reasoning (48 reglas en SMT-LIB) y el guardrail verificador.
Uso: python3 ia/verificador_ar.py"""

import json
import os
import sys
import time

import boto3
from botocore.exceptions import ClientError

from conexion import REGION, preguntas_y_opciones

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "..", "motor"))
from vocabulario_ar import VALORES, VARIABLE_RUTINA, VARIABLES, valor_rutina  # noqa: E402

POLITICA = "se-rutinas-reglas-experto"
GUARDRAIL = "se-rutinas-verificador"
br = boto3.client("bedrock", region_name=REGION)


def construir_definicion(preguntas, hipotesis, reglas):
    tipos, variables = [], []
    for p in preguntas:
        var, tipo, desc = VARIABLES[p["atributo"]]
        tipos.append({"name": tipo, "description": desc, "values": [
            {"value": VALORES[(p["atributo"], o["valor"])][0],
             "description": VALORES[(p["atributo"], o["valor"])][1]} for o in p["opciones"]]})
        variables.append({"name": var, "type": tipo, "description": desc + " Possible values: "
                          + ", ".join(VALORES[(p["atributo"], o["valor"])][0] for o in p["opciones"])
                          + "."})
    var, tipo, desc = VARIABLE_RUTINA
    tipos.append({"name": tipo, "description": desc, "values": [
        {"value": valor_rutina(h["codigo"]),
         "description": f"Routine {h['codigo']} for {h['nivel']} level, equipment "
                        + VALORES[("equipo_disponible", h["equipo"])][0]}
        for h in hipotesis]})
    variables.append({"name": var, "type": tipo, "description": desc})

    reglas_logicas, legibles = [], []
    for codigo, hip, condiciones in reglas:
        partes = [f"(= {VARIABLES[a][0]} {VALORES[(a, v)][0]})" for a, v in condiciones]
        expresion = f"(=> (and {' '.join(partes)}) (= {var} {valor_rutina(hip)}))"
        # El identificador debe tener 12 caracteres: R25 -> REGLA0000R25
        reglas_logicas.append({"id": "REGLA" + codigo.rjust(7, "0"), "expression": expresion})
        legibles.append((codigo, hip, condiciones, expresion))
    return {"version": "1.0", "types": tipos, "variables": variables,
            "rules": reglas_logicas}, legibles


def guardar_documento(definicion, legibles):
    lineas = ["# Política de Automated Reasoning · Reglas del experto", "",
              f"Variables: {len(definicion['variables'])} · Tipos: {len(definicion['types'])} · "
              f"Reglas: {len(definicion['rules'])}", "", "## Variables", ""]
    for v in definicion["variables"]:
        lineas.append(f"- `{v['name']}` ({v['type']}): {v['description']}")
    lineas += ["", "## Reglas (SMT-LIB)", ""]
    for codigo, hip, cond, expr in legibles:
        si = " Y ".join(f"{a} = {v}" for a, v in cond)
        lineas += [f"**{codigo}** · SI {si} ENTONCES rutina = {hip}", "", f"`{expr}`", ""]
    with open(os.path.join(AQUI, "politica_reglas_experto.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lineas))


def _crear_o_actualizar(definicion):
    existentes = br.list_automated_reasoning_policies(maxResults=50)[
        "automatedReasoningPolicySummaries"]
    actual = next((p for p in existentes if p["name"] == POLITICA), None)
    if actual:
        r = br.update_automated_reasoning_policy(policyArn=actual["policyArn"],
                                                 policyDefinition=definicion)
        print(f"Política actualizada: {r['policyArn']}")
    else:
        r = br.create_automated_reasoning_policy(
            name=POLITICA, policyDefinition=definicion,
            description="Reglas de producción del sistema experto de rutinas, validadas con el experto")
        print(f"Política creada: {r['policyArn']}")
    return r


def politica(definicion):
    try:
        r = _crear_o_actualizar(definicion)
    except ClientError as e:
        # El valor del campo "version" del formato no está documentado: si el
        # servicio lo rechaza, se envía la definición sin ese campo.
        if "version" not in str(e).lower():
            raise
        print("   El servicio no acepta el campo 'version'; se envía sin él")
        definicion = {k: v for k, v in definicion.items() if k != "version"}
        r = _crear_o_actualizar(definicion)
    try:
        v = br.create_automated_reasoning_policy_version(
            policyArn=r["policyArn"], lastUpdatedDefinitionHash=r["definitionHash"])
        version = v["version"]
        print(f"Versión publicada: {version}")
    except ClientError as e:
        # Sin cambios en las reglas: se reutiliza la última versión publicada
        versiones = [p["version"] for p in br.list_automated_reasoning_policies(
            policyArn=r["policyArn"], maxResults=50)["automatedReasoningPolicySummaries"]
            if str(p.get("version", "")).isdigit()]
        if not versiones:
            raise
        version = max(versiones, key=int)
        print(f"Sin cambios en las reglas ({e.response['Error']['Code']}); "
              f"se usa la versión {version}")
    base = r["policyArn"].rsplit(":", 1)[0] if r["policyArn"].split(":")[-1].isdigit() \
        else r["policyArn"]
    return f"{base}:{version}"


def guardrail(arn_version):
    base = {"name": GUARDRAIL,
            "description": "Verifica que el diagnóstico cumpla las reglas del experto",
            "blockedInputMessaging": "La consulta no cumple las reglas del sistema experto.",
            "blockedOutputsMessaging": "El diagnóstico no cumple las reglas del sistema experto.",
            "automatedReasoningPolicyConfig": {"policies": [arn_version],
                                               "confidenceThreshold": 0.5}}
    existente = next((g for g in br.list_guardrails(maxResults=100)["guardrails"]
                      if g["name"] == GUARDRAIL), None)
    # AWS documenta que un guardrail con Automated Reasoning requiere un perfil
    # entre regiones; se intenta primero con él y, si la cuenta no lo permite, sin él.
    errores = []
    gid = None
    for extra in ({"crossRegionConfig": {"guardrailProfileIdentifier": "us.guardrail.v1:0"}}, {}):
        try:
            if existente:
                gid = br.update_guardrail(guardrailIdentifier=existente["id"], **base,
                                          **extra)["guardrailId"]
            else:
                gid = br.create_guardrail(**base, **extra)["guardrailId"]
            print("   Guardrail configurado " + ("con perfil entre regiones (us.guardrail.v1:0)"
                                                 if extra else "sin perfil entre regiones"))
            break
        except ClientError as e:
            errores.append(f"{e.response['Error']['Code']}: {e.response['Error']['Message']}")
    if gid is None:
        print("   No se pudo crear el guardrail:")
        for m in errores:
            print("     -", m[:300])
        raise RuntimeError("guardrail no disponible en esta cuenta")
    for _ in range(40):
        estado = br.get_guardrail(guardrailIdentifier=gid)["status"]
        if estado == "READY":
            break
        if estado == "FAILED":
            raise RuntimeError("el guardrail quedó en estado FAILED")
        time.sleep(3)
    version = br.create_guardrail_version(guardrailIdentifier=gid,
                                          description="Reglas del experto")["version"]
    print(f"Guardrail {GUARDRAIL}: id {gid}, versión {version}")
    return gid, version


def probar(reglas):
    import servicios_ia
    servicios_ia._cache.clear()
    ver = servicios_ia.VerificadorFormal()
    casos = []
    for codigo in ("R01", "R13", "R25", "R33"):
        _, hip, cond = next(r for r in reglas if r[0] == codigo)
        hechos = [{"atributo": a, "valor": v} for a, v in cond]
        casos.append((f"{codigo} con su rutina correcta {hip}", hechos, hip, "VALID"))
    _, _, cond = next(r for r in reglas if r[0] == "R25")
    casos.append(("R25 con una rutina equivocada (H20 en vez de H21)",
                  [{"atributo": a, "valor": v} for a, v in cond], "H20", "INVALID"))
    _, _, cond = next(r for r in reglas if r[0] == "R01")
    casos.append(("Principiante con una rutina de avanzado (H26)",
                  [{"atributo": a, "valor": v} for a, v in cond], "H26", "INVALID"))
    aciertos = 0
    for nombre, hechos, hip, esperado in casos:
        res, det = ver.verificar(hechos, hip)
        ok = res == esperado
        aciertos += ok
        print(f"   {'OK   ' if ok else 'FALLO'} {nombre}: {res} (esperado {esperado})"
              + (f" · reglas {det.get('reglas')}" if det.get("reglas") else "")
              + (f" · {det.get('error')}" if det.get("error") else ""))
    print(f"VERIFICADOR: {aciertos}/{len(casos)} casos con el resultado esperado")
    return aciertos == len(casos)


def main():
    with open(os.path.join(AQUI, "reglas_experto.json"), encoding="utf-8") as f:
        reglas = [(r, h, [tuple(c) for c in conds]) for r, h, conds in json.load(f)]
    preguntas, hipotesis = preguntas_y_opciones()
    definicion, legibles = construir_definicion(preguntas, hipotesis, reglas)
    guardar_documento(definicion, legibles)
    print(f"Política: {len(definicion['variables'])} variables, {len(definicion['types'])} tipos, "
          f"{len(definicion['rules'])} reglas")
    try:
        arn = politica(definicion)
    except ClientError as e:
        print(f"ERROR al crear la política: {e.response['Error']['Code']}: "
              f"{e.response['Error']['Message'][:500]}")
        return 1
    try:
        guardrail(arn)
    except (ClientError, RuntimeError) as e:
        print(f"ERROR en el guardrail: {e}")
        print("La política quedó guardada en Automated Reasoning, pero sin guardrail no se puede "
              "verificar desde el motor. Comparte este reporte para ajustar la configuración.")
        return 2
    print("Probando el verificador con diagnósticos correctos e incorrectos...")
    time.sleep(5)
    return 0 if probar(reglas) else 1


if __name__ == "__main__":
    sys.exit(main())
