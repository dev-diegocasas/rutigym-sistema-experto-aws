"""Limpia sobrantes en AWS y conserva lo que usa producción.
Uso: python3 limpiar_nube.py [--aplicar]"""

import re
import sys
import time

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"
APLICAR = "--aplicar" in sys.argv
ses = boto3.Session(region_name=REGION)

STACK_API, STACK_WEB = "se-rutinas-motor", "se-rutinas-web"
LAMBDA_MOTOR = "se-motor-inferencia"
BOT, ALIAS, BOT_PRUEBA = "se-rutinas-nlu", "produccion", "se-prueba-lex"
POLITICA, GUARDRAIL = "se-rutinas-reglas-experto", "se-rutinas-verificador"
ROLES_PRUEBA = ["se-prueba-viabilidad-rol", "se-prueba-lex-rol"]
CUENTAS_DEMO = {"diego.admin", "simon.ingeniero", "cristian.experto", "profesor.experto",
                "laura.usuario", "andres.usuario", "valentina.usuario"}
ARCHIVOS_WEB = {"index.html", "config.js", "app.js", "estilos.css", "fuentes/OFL.txt",
                "fuentes/archivo-400.woff2", "fuentes/archivo-600.woff2", "fuentes/archivo-800.woff2"}

resumen = {"encontrados": 0, "borrados": 0, "errores": 0}


def seccion(titulo):
    print(f"\n==> {titulo}")


def sobrante(descripcion, borrar):
    """Informa un recurso sobrante y, con --aplicar, lo elimina."""
    resumen["encontrados"] += 1
    if not APLICAR:
        print(f"   sobra: {descripcion}")
        return
    try:
        borrar()
        resumen["borrados"] += 1
        print(f"   borrado: {descripcion}")
    except ClientError as e:
        resumen["errores"] += 1
        print(f"   NO se pudo borrar {descripcion}: {e.response['Error']['Code']} "
              f"{e.response['Error']['Message'][:160]}")


def salida_stack(stack, clave):
    try:
        for o in ses.client("cloudformation").describe_stacks(StackName=stack)["Stacks"][0].get(
                "Outputs", []):
            if o["OutputKey"] == clave:
                return o["OutputValue"]
    except ClientError:
        pass
    return None


# ---------------------------------------------------------------- Cognito
def cognito():
    seccion("Cuentas de Cognito creadas por las pruebas")
    pool = salida_stack(STACK_API, "UserPoolId")
    if not pool:
        print("   No se encontró el grupo de usuarios")
        return
    cog = ses.client("cognito-idp")
    for pagina in cog.get_paginator("list_users").paginate(UserPoolId=pool):
        for u in pagina["Users"]:
            correo = next((a["Value"] for a in u["Attributes"] if a["Name"] == "email"), "")
            if correo.split("@")[0] in CUENTAS_DEMO and correo.endswith("@sistema-experto.test"):
                continue
            sobrante(f"cuenta {correo or u['Username']}",
                     lambda n=u["Username"]: cog.admin_delete_user(UserPoolId=pool, Username=n))
    print("   Las 7 cuentas de demostración se conservan")


# ---------------------------------------------------------------- Lex
def lex():
    seccion("Versiones de Amazon Lex")
    lx = ses.client("lexv2-models")
    bots = {b["botName"]: b["botId"] for b in lx.list_bots(maxResults=50)["botSummaries"]}
    if BOT_PRUEBA in bots:
        sobrante(f"bot de la prueba de viabilidad {BOT_PRUEBA}",
                 lambda: lx.delete_bot(botId=bots[BOT_PRUEBA], skipResourceInUseCheck=True))
    if BOT not in bots:
        print(f"   No existe el bot {BOT}")
        return
    bid = bots[BOT]
    alias = next((a for a in lx.list_bot_aliases(botId=bid)["botAliasSummaries"]
                  if a["botAliasName"] == ALIAS), None)
    en_uso = alias.get("botVersion") if alias else None
    print(f"   El alias '{ALIAS}' usa la versión {en_uso}: se conserva")
    versiones, token = [], None
    while True:
        r = lx.list_bot_versions(botId=bid, maxResults=50, **({"nextToken": token} if token else {}))
        versiones += [v["botVersion"] for v in r["botVersionSummaries"]]
        token = r.get("nextToken")
        if not token:
            break
    for v in versiones:
        if v.isdigit() and v != en_uso:
            sobrante(f"versión {v} del bot {BOT}",
                     lambda v=v: lx.delete_bot_version(botId=bid, botVersion=v,
                                                       skipResourceInUseCheck=True))


# ---------------------------------------------------------------- Bedrock
def bedrock():
    seccion("Guardrail y política de Automated Reasoning")
    br = ses.client("bedrock")
    patron = re.compile(r"arn:aws:bedrock:[^\"' ]*automated-reasoning-policy/[^\"' ,\]]+")
    referenciadas = set()

    guardrails = br.list_guardrails(maxResults=100)["guardrails"]
    for g in guardrails:
        if g["name"].startswith("se-") and g["name"] != GUARDRAIL:
            sobrante(f"guardrail sobrante {g['name']}",
                     lambda i=g["id"]: br.delete_guardrail(guardrailIdentifier=i))
    g = next((x for x in guardrails if x["name"] == GUARDRAIL), None)
    if g:
        versiones = [v["version"] for v in br.list_guardrails(
            guardrailIdentifier=g["id"], maxResults=100)["guardrails"]]
        numericas = sorted((v for v in versiones if v.isdigit()), key=int)
        conservar = numericas[-1] if numericas else None
        print(f"   Guardrail {GUARDRAIL}: {len(numericas)} versiones; se conserva la {conservar}")
        for v in [conservar, "DRAFT"]:
            if v:
                datos = br.get_guardrail(guardrailIdentifier=g["id"], guardrailVersion=v)
                referenciadas |= set(patron.findall(str(datos)))
        for v in numericas[:-1]:
            sobrante(f"versión {v} del guardrail",
                     lambda v=v: br.delete_guardrail(guardrailIdentifier=g["id"],
                                                     guardrailVersion=v))

    if not hasattr(br, "list_automated_reasoning_policies"):
        print("   Este boto3 no trae Automated Reasoning; se omite")
        return
    politicas = br.list_automated_reasoning_policies(maxResults=50)[
        "automatedReasoningPolicySummaries"]
    for p in politicas:
        if p["name"].startswith("se-") and p["name"] != POLITICA:
            sobrante(f"política sobrante {p['name']}",
                     lambda a=p["policyArn"]: br.delete_automated_reasoning_policy(policyArn=a))
    p = next((x for x in politicas if x["name"] == POLITICA), None)
    if not p:
        return
    base = p["policyArn"]
    en_uso = {a.rsplit(":", 1)[-1] for a in referenciadas if a.split(":")[-1].isdigit()}
    versiones = [x for x in br.list_automated_reasoning_policies(
        policyArn=base, maxResults=50)["automatedReasoningPolicySummaries"]
        if str(x.get("version", "")).isdigit()]
    print(f"   Política {POLITICA}: {len(versiones)} versiones; el guardrail usa la "
          f"{', '.join(sorted(en_uso)) or '(no se pudo leer)'}")
    if not en_uso:
        print("   Como no se sabe cuál usa el guardrail, no se borra ninguna versión")
    else:
        for x in versiones:
            if str(x["version"]) not in en_uso:
                sobrante(f"versión {x['version']} de la política",
                         lambda a=f"{base}:{x['version']}":
                         br.delete_automated_reasoning_policy(policyArn=a))
    if hasattr(br, "list_automated_reasoning_policy_build_workflows"):
        try:
            flujos = br.list_automated_reasoning_policy_build_workflows(
                policyArn=base, maxResults=50).get("automatedReasoningPolicyBuildWorkflowSummaries", [])
        except ClientError:
            flujos = []
        for f in flujos:
            sobrante(f"compilación {f['buildWorkflowId']} de la política",
                     lambda f=f: br.delete_automated_reasoning_policy_build_workflow(
                         policyArn=base, buildWorkflowId=f["buildWorkflowId"],
                         lastUpdatedAt=f["updatedAt"]))


# ---------------------------------------------------------------- Lambda, IAM, logs
def lambda_iam_logs():
    seccion("Funciones Lambda, roles de prueba y registros")
    lam, iam, logs = ses.client("lambda"), ses.client("iam"), ses.client("logs")
    funciones = set()
    for pag in lam.get_paginator("list_functions").paginate():
        funciones |= {f["FunctionName"] for f in pag["Functions"]}
    for f in sorted(funciones):
        if f.startswith("se-") and f != LAMBDA_MOTOR:
            sobrante(f"función {f}", lambda f=f: lam.delete_function(FunctionName=f))

    for rol in ROLES_PRUEBA:
        try:
            iam.get_role(RoleName=rol)
        except ClientError:
            continue

        def borrar_rol(rol=rol):
            for pol in iam.list_attached_role_policies(RoleName=rol)["AttachedPolicies"]:
                iam.detach_role_policy(RoleName=rol, PolicyArn=pol["PolicyArn"])
            for nombre in iam.list_role_policies(RoleName=rol)["PolicyNames"]:
                iam.delete_role_policy(RoleName=rol, PolicyName=nombre)
            iam.delete_role(RoleName=rol)
        sobrante(f"rol IAM {rol}", borrar_rol)

    for pag in logs.get_paginator("describe_log_groups").paginate(logGroupNamePrefix="/aws/lambda/se-"):
        for grupo in pag["logGroups"]:
            nombre = grupo["logGroupName"]
            if nombre.split("/")[-1] != LAMBDA_MOTOR:
                sobrante(f"registros de {nombre}",
                         lambda n=nombre: logs.delete_log_group(logGroupName=n))
    # Registros del motor: se vacían para que en el video no aparezcan errores viejos
    grupo = f"/aws/lambda/{LAMBDA_MOTOR}"
    try:
        flujos = []
        for pag in logs.get_paginator("describe_log_streams").paginate(logGroupName=grupo):
            flujos += [s["logStreamName"] for s in pag["logStreams"]]
    except ClientError:
        flujos = []
    if flujos:
        def vaciar():
            for s in flujos:
                logs.delete_log_stream(logGroupName=grupo, logStreamName=s)
        sobrante(f"{len(flujos)} flujos de registro antiguos del motor", vaciar)


# ---------------------------------------------------------------- CloudFormation y S3
def cloudformation_s3():
    seccion("Pilas de CloudFormation fallidas")
    cf = ses.client("cloudformation")
    fallidos = ["ROLLBACK_COMPLETE", "CREATE_FAILED", "ROLLBACK_FAILED", "DELETE_FAILED"]
    for pag in cf.get_paginator("list_stacks").paginate(StackStatusFilter=fallidos):
        for st in pag["StackSummaries"]:
            if st["StackName"].startswith("se-"):
                sobrante(f"pila {st['StackName']} ({st['StackStatus']})",
                         lambda n=st["StackName"]: cf.delete_stack(StackName=n))

    seccion("Archivos en S3")
    s3 = ses.client("s3")
    bucket_web = salida_stack(STACK_WEB, "BucketWeb")
    if bucket_web:
        for pag in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket_web):
            for o in pag.get("Contents", []):
                if o["Key"] not in ARCHIVOS_WEB:
                    sobrante(f"archivo viejo de la página {o['Key']}",
                             lambda k=o["Key"]: s3.delete_object(Bucket=bucket_web, Key=k))
        print(f"   Bucket de la página: {bucket_web} (los archivos actuales se conservan)")
    # Paquetes que SAM subió en cada despliegue: no se vuelven a usar
    for b in s3.list_buckets()["Buckets"]:
        if not b["Name"].startswith("aws-sam-cli-managed-default"):
            continue
        objetos = []
        for pag in s3.get_paginator("list_object_versions").paginate(Bucket=b["Name"]):
            objetos += [{"Key": v["Key"], "VersionId": v["VersionId"]}
                        for v in pag.get("Versions", []) + pag.get("DeleteMarkers", [])]
        if objetos:
            def vaciar(bn=b["Name"], objs=objetos):
                for i in range(0, len(objs), 1000):
                    s3.delete_objects(Bucket=bn, Delete={"Objects": objs[i:i + 1000], "Quiet": True})
            sobrante(f"{len(objetos)} paquetes de despliegue antiguos en {b['Name']}", vaciar)


def reiniciar_motor():
    """Fuerza entornos nuevos de la Lambda (sin conexiones ni datos en memoria)."""
    lam = ses.client("lambda")
    conf = lam.get_function_configuration(FunctionName=LAMBDA_MOTOR)
    variables = conf.get("Environment", {}).get("Variables", {})
    variables["REINICIO"] = str(int(time.time()))
    lam.update_function_configuration(FunctionName=LAMBDA_MOTOR,
                                      Environment={"Variables": variables})
    lam.get_waiter("function_updated_v2").wait(FunctionName=LAMBDA_MOTOR)
    print("   Motor reiniciado (entornos nuevos en la próxima petición)")


def main():
    if "--reiniciar-motor" in sys.argv:
        reiniciar_motor()
        return 0
    print("MODO:", "LIMPIEZA" if APLICAR else "REVISIÓN (no se borra nada)")
    for paso in (cognito, lex, bedrock, lambda_iam_logs, cloudformation_s3):
        try:
            paso()
        except ClientError as e:
            resumen["errores"] += 1
            print(f"   Error en {paso.__name__}: {e.response['Error']['Code']} "
                  f"{e.response['Error']['Message'][:200]}")
    print(f"\nNUBE: {resumen['encontrados']} sobrantes encontrados"
          + (f", {resumen['borrados']} borrados" if APLICAR else "")
          + (f", {resumen['errores']} errores" if resumen["errores"] else ""))
    return 1 if resumen["errores"] else 0


if __name__ == "__main__":
    sys.exit(main())
