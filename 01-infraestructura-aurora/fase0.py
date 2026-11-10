"""FASE 0 · Prueba de viabilidad: Aurora, Lambda, Lex, Bedrock y permisos en la cuenta.
Uso: bash ejecutar_fase0.sh"""

import io
import json
import os
import ssl
import subprocess
import sys
import time
import traceback
import zipfile

import boto3
import botocore

REGION = "us-east-1"
CLUSTER = "se-rutinas-db"
LAMBDA = "se-prueba-viabilidad"
ROL_LAMBDA = "se-prueba-viabilidad-rol"
ROL_LEX = "se-prueba-lex-rol"
BOT = "se-prueba-lex"
AQUI = os.path.dirname(os.path.abspath(__file__))
BUNDLE = os.path.join(AQUI, "global-bundle.pem")
# CloudShell corre Python dentro de un entorno virtual: las dependencias se instalan
# en una carpeta local (_deps) y se agregan a la ruta de búsqueda
sys.path.insert(0, os.path.join(AQUI, "_deps"))

ses = boto3.Session(region_name=REGION)
resultados = []   # (prueba, estado, detalle)
contexto = {}


def registrar(prueba, ok, detalle=""):
    estado = "OK" if ok is True else ("AVISO" if ok is None else "FALLO")
    resultados.append((prueba, estado, str(detalle)))
    simbolo = {"OK": "✅", "AVISO": "⚠️ ", "FALLO": "❌"}[estado]
    print(f"{simbolo} {prueba}: {detalle}", flush=True)


def paso(titulo):
    print(f"\n=== {titulo} ===", flush=True)


def error_corto(e):
    if isinstance(e, botocore.exceptions.ClientError):
        return f"{e.response['Error']['Code']}: {e.response['Error']['Message']}"
    return f"{type(e).__name__}: {e}"


def contexto_ssl():
    ctx = ssl.create_default_context()
    if os.path.exists(BUNDLE):
        ctx.load_verify_locations(BUNDLE)
    return ctx


# ---------------------------------------------------------------- 0. Cuenta
def prueba_cuenta():
    paso("0. Cuenta y región")
    ident = ses.client("sts").get_caller_identity()
    contexto["cuenta"] = ident["Account"]
    registrar("Identidad", True, f"cuenta {ident['Account']} · región {REGION}")
    registrar("Versión de boto3", True, boto3.__version__)


# ---------------------------------------------------------------- 1. Aurora
def prueba_aurora():
    paso("1. Aurora PostgreSQL (express configuration)")
    rds = ses.client("rds")
    try:
        c = rds.describe_db_clusters(DBClusterIdentifier=CLUSTER)["DBClusters"][0]
        registrar("Clúster existente", True, f"{CLUSTER} ya existía, se reutiliza")
    except rds.exceptions.DBClusterNotFoundFault:
        try:
            rds.create_db_cluster(DBClusterIdentifier=CLUSTER, Engine="aurora-postgresql",
                                  WithExpressConfiguration=True)
            registrar("Creación con express configuration", True, "solicitada con boto3")
        except botocore.exceptions.ParamValidationError:
            # boto3 sin el parámetro: se intenta con la CLI
            r = subprocess.run(["aws", "rds", "create-db-cluster", "--region", REGION,
                                "--db-cluster-identifier", CLUSTER, "--engine",
                                "aurora-postgresql", "--with-express-configuration"],
                               capture_output=True, text=True)
            if r.returncode != 0:
                registrar("Creación con express configuration", False,
                          "ni boto3 ni la CLI aceptan el parámetro: " + r.stderr.strip()[:300])
                return False
            registrar("Creación con express configuration", True, "solicitada con la CLI")

    print("   Esperando a que el clúster y su instancia estén disponibles (máx. 20 min)...",
          flush=True)
    inicio = time.time()
    while time.time() - inicio < 1200:
        c = rds.describe_db_clusters(DBClusterIdentifier=CLUSTER)["DBClusters"][0]
        miembros = c.get("DBClusterMembers", [])
        estados = []
        for m in miembros:
            i = rds.describe_db_instances(DBInstanceIdentifier=m["DBInstanceIdentifier"])
            estados.append(i["DBInstances"][0]["DBInstanceStatus"])
        if c["Status"] == "available" and miembros and all(s == "available" for s in estados):
            break
        print(f"   ... clúster {c['Status']}, instancias {estados or 'creando'} "
              f"({int(time.time() - inicio)} s)", flush=True)
        time.sleep(20)
    else:
        registrar("Disponibilidad", False, "el clúster no quedó disponible en 20 minutos")
        return False

    contexto["host"] = c["Endpoint"]
    contexto["resource_id"] = c["DbClusterResourceId"]
    registrar("Disponibilidad", True, f"listo en {int(time.time() - inicio)} s · {c['Endpoint']}")
    escalado = c.get("ServerlessV2ScalingConfiguration", {})
    registrar("Capacidad serverless", True,
              f"mín {escalado.get('MinCapacity')} · máx {escalado.get('MaxCapacity')} ACU "
              "(Free Tier cubre hasta 4 ACU)")
    if escalado.get("MaxCapacity", 0) > 4:
        registrar("Límite Free Tier", None,
                  "la capacidad máxima supera 4 ACU; se ajustará a 4 en la Fase 1")
    return True


def conectar(usuario, intentos=6):
    """Con capacidad mínima 0 ACU el clúster se pausa cuando no se usa; la primera
    conexión lo despierta y puede tardar. Se reintenta y se mide ese tiempo."""
    import pg8000.native
    inicio = time.time()
    for n in range(1, intentos + 1):
        token = ses.client("rds").generate_db_auth_token(
            DBHostname=contexto["host"], Port=5432, DBUsername=usuario, Region=REGION)
        try:
            con = pg8000.native.Connection(user=usuario, host=contexto["host"], port=5432,
                                           database="postgres", password=token,
                                           ssl_context=contexto_ssl(), timeout=60)
            espera = int(time.time() - inicio)
            if espera > 5:
                print(f"   Conexión lograda tras {espera} s (el clúster estaba en pausa)")
                contexto["tiempo_reanudar"] = espera
            return con
        except Exception as e:
            if n == intentos:
                raise
            print(f"   Intento {n}: {error_corto(e)} · reintentando (clúster despertando)...")
            time.sleep(10)


# ---------------------------------------------------------------- 2. CloudShell → Aurora
SQL_PREPARACION = [
    """DO $$ BEGIN
         IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_lambda') THEN
           CREATE ROLE app_lambda LOGIN;
         END IF;
         IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rol_prueba') THEN
           CREATE ROLE rol_prueba NOLOGIN;
         END IF;
       END $$""",
    "GRANT rds_iam TO app_lambda",
    "GRANT rol_prueba TO app_lambda",
    """CREATE TABLE IF NOT EXISTS prueba_viabilidad (
         id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
         origen TEXT NOT NULL,
         fecha TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
    """CREATE OR REPLACE PROCEDURE sp_prueba(p_origen TEXT)
       LANGUAGE plpgsql AS $$
       BEGIN
         INSERT INTO prueba_viabilidad (origen) VALUES (p_origen);
       END $$""",
    "REVOKE ALL ON prueba_viabilidad FROM PUBLIC",
    "REVOKE EXECUTE ON PROCEDURE sp_prueba(TEXT) FROM PUBLIC",
    "GRANT SELECT, INSERT ON prueba_viabilidad TO rol_prueba",
    "GRANT EXECUTE ON PROCEDURE sp_prueba(TEXT) TO rol_prueba",
    "CALL sp_prueba('cloudshell')",
]


def prueba_cloudshell():
    paso("2. Conexión desde CloudShell (IAM + PL/pgSQL + roles)")
    try:
        con = conectar("postgres")
    except Exception as e:
        registrar("Conexión con token IAM", False, error_corto(e))
        return False
    registrar("Conexión con token IAM", True, "usuario postgres, SSL verificado")
    if contexto.get("tiempo_reanudar"):
        registrar("Reanudación desde pausa", None,
                  f"la primera conexión tardó {contexto['tiempo_reanudar']} s en despertar el "
                  "clúster (dato para decidir la capacidad mínima)")
    try:
        version = con.run("SELECT version()")[0][0]
        registrar("Motor", True, version[:70])
        for sql in SQL_PREPARACION:
            con.run(sql)
        registrar("Procedimiento PL/pgSQL y roles con GRANT", True,
                  "sp_prueba creado y ejecutado; rol_prueba con permisos mínimos")
        return True
    except Exception as e:
        registrar("Procedimiento PL/pgSQL y roles con GRANT", False, error_corto(e))
        return False
    finally:
        con.close()


# ---------------------------------------------------------------- 3. Lambda → Aurora
def empaquetar_lambda():
    destino = os.path.join(AQUI, "_paquete_lambda")
    subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "--upgrade",
                    "pg8000", "python-dateutil<3", "-t", destino], check=True)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        for raiz, _, archivos in os.walk(destino):
            for a in archivos:
                ruta = os.path.join(raiz, a)
                z.write(ruta, os.path.relpath(ruta, destino))
        z.write(os.path.join(AQUI, "handler_prueba.py"), "handler_prueba.py")
        if os.path.exists(BUNDLE):
            z.write(BUNDLE, "global-bundle.pem")
    return buffer.getvalue()


def prueba_lambda():
    paso("3. Conexión desde Lambda sin VPC (patrón del motor de inferencia)")
    iam, lam = ses.client("iam"), ses.client("lambda")
    confianza = {"Version": "2012-10-17", "Statement": [{
        "Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"},
        "Action": "sts:AssumeRole"}]}
    try:
        try:
            arn_rol = iam.create_role(RoleName=ROL_LAMBDA,
                                      AssumeRolePolicyDocument=json.dumps(confianza))["Role"]["Arn"]
        except iam.exceptions.EntityAlreadyExistsException:
            arn_rol = iam.get_role(RoleName=ROL_LAMBDA)["Role"]["Arn"]
        iam.attach_role_policy(RoleName=ROL_LAMBDA, PolicyArn=(
            "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"))
        iam.put_role_policy(RoleName=ROL_LAMBDA, PolicyName="conectar-aurora",
                            PolicyDocument=json.dumps({"Version": "2012-10-17", "Statement": [{
                                "Effect": "Allow", "Action": "rds-db:connect",
                                "Resource": (f"arn:aws:rds-db:{REGION}:{contexto['cuenta']}:dbuser:"
                                             f"{contexto['resource_id']}/app_lambda")}]}))
        codigo = empaquetar_lambda()
    except Exception as e:
        registrar("Preparación de la Lambda", False, error_corto(e))
        return False

    for intento in range(12):  # el rol IAM tarda unos segundos en propagarse
        try:
            try:
                lam.delete_function(FunctionName=LAMBDA)
            except lam.exceptions.ResourceNotFoundException:
                pass
            lam.create_function(FunctionName=LAMBDA, Runtime="python3.12", Role=arn_rol,
                                Handler="handler_prueba.handler", Code={"ZipFile": codigo},
                                Timeout=30, MemorySize=256,
                                Environment={"Variables": {"DB_HOST": contexto["host"]}})
            break
        except botocore.exceptions.ClientError as e:
            if e.response["Error"]["Code"] == "InvalidParameterValueException" and intento < 11:
                time.sleep(5)
                continue
            registrar("Creación de la Lambda", False, error_corto(e))
            return False
    lam.get_waiter("function_active_v2").wait(FunctionName=LAMBDA)
    registrar("Creación de la Lambda", True, "python3.12, sin VPC")

    r = lam.invoke(FunctionName=LAMBDA)
    cuerpo = json.loads(r["Payload"].read())
    if r.get("FunctionError"):
        registrar("Lambda → Aurora con SET ROLE", False,
                  f"{cuerpo.get('errorType')}: {cuerpo.get('errorMessage')}"[:400])
        return False
    registrar("Lambda → Aurora con SET ROLE", True,
              f"rol activo {cuerpo['rol_activo']}, procedimiento ejecutado, {cuerpo['filas']} filas")
    return True


# ---------------------------------------------------------------- 4. Lex
def esperar(funcion, campo, deseados, fallidos=("Failed",), limite=300):
    inicio = time.time()
    while time.time() - inicio < limite:
        estado = funcion()[campo]
        if estado in deseados:
            return estado
        if estado in fallidos:
            raise RuntimeError(f"estado {estado}")
        time.sleep(5)
    raise TimeoutError(f"{campo} no llegó a {deseados}")


def prueba_lex():
    paso("4. Amazon Lex en español (el motor elige la pregunta, Lex interpreta)")
    iam, lex = ses.client("iam"), ses.client("lexv2-models")
    rt = ses.client("lexv2-runtime")
    confianza = {"Version": "2012-10-17", "Statement": [{
        "Effect": "Allow", "Principal": {"Service": "lexv2.amazonaws.com"},
        "Action": "sts:AssumeRole"}]}
    try:
        arn = iam.create_role(RoleName=ROL_LEX,
                              AssumeRolePolicyDocument=json.dumps(confianza))["Role"]["Arn"]
    except iam.exceptions.EntityAlreadyExistsException:
        arn = iam.get_role(RoleName=ROL_LEX)["Role"]["Arn"]
    time.sleep(10)
    bot_id = None
    try:
        # Si quedó un bot de una ejecución anterior, se borra antes de crear el nuevo
        previos = lex.list_bots(filters=[{"name": "BotName", "values": [BOT],
                                          "operator": "EQ"}]).get("botSummaries", [])
        for b in previos:
            lex.delete_bot(botId=b["botId"], skipResourceInUseCheck=True)
        if previos:
            time.sleep(15)
        bot_id = lex.create_bot(botName=BOT, roleArn=arn, dataPrivacy={"childDirected": False},
                                idleSessionTTLInSeconds=300)["botId"]
        contexto["bot_id"] = bot_id
        esperar(lambda: lex.describe_bot(botId=bot_id), "botStatus", {"Available"})
        locale = None
        for candidato in ("es_419", "es_US"):
            try:
                lex.create_bot_locale(botId=bot_id, botVersion="DRAFT", localeId=candidato,
                                      nluIntentConfidenceThreshold=0.40)
                locale = candidato
                break
            except botocore.exceptions.ClientError as e:
                print(f"   locale {candidato} no disponible: {error_corto(e)}")
        if not locale:
            registrar("Idioma español", False, "ni es_419 ni es_US disponibles")
            return False
        comun = {"botId": bot_id, "botVersion": "DRAFT", "localeId": locale}
        esperar(lambda: lex.describe_bot_locale(**comun), "botLocaleStatus", {"NotBuilt", "Built"})
        registrar("Idioma español", True, f"locale {locale}")

        tipo = lex.create_slot_type(slotTypeName="TiempoEntrenando",
            valueSelectionSetting={"resolutionStrategy": "TopResolution"},
            slotTypeValues=[
                {"sampleValue": {"value": "MENOS_6_MESES"}, "synonyms": [
                    {"value": "menos de seis meses"}, {"value": "poco tiempo"},
                    {"value": "unos meses"}, {"value": "acabo de empezar"}]},
                {"sampleValue": {"value": "ENTRE_6_MESES_Y_2_ANOS"}, "synonyms": [
                    {"value": "un año"}, {"value": "como un año"}, {"value": "año y medio"},
                    {"value": "entre seis meses y dos años"}]},
                {"sampleValue": {"value": "MAS_DE_2_ANOS"}, "synonyms": [
                    {"value": "más de dos años"}, {"value": "tres años"},
                    {"value": "muchos años"}, {"value": "varios años"}]}],
            **comun)["slotTypeId"]
        intent = lex.create_intent(intentName="ResponderPregunta",
                                   sampleUtterances=[{"utterance": "quiero responder"}],
                                   **comun)["intentId"]
        slot = lex.create_slot(slotName="tiempo_entrenando", slotTypeId=tipo, intentId=intent,
                               valueElicitationSetting={
                                   "slotConstraint": "Optional",
                                   # Lex exige un mensaje para ElicitSlot; la interfaz
                                   # mostrará el texto de la tabla preguntas, no este
                                   "promptSpecification": {
                                       "messageGroups": [{"message": {"plainTextMessage": {
                                           "value": "¿Cuánto tiempo llevas entrenando?"}}}],
                                       "maxRetries": 1}},
                               **comun)["slotId"]
        lex.update_intent(intentId=intent, intentName="ResponderPregunta",
                          sampleUtterances=[{"utterance": "{tiempo_entrenando}"},
                                            {"utterance": "llevo {tiempo_entrenando}"},
                                            {"utterance": "entreno hace {tiempo_entrenando}"}],
                          slotPriorities=[{"priority": 1, "slotId": slot}], **comun)
        lex.build_bot_locale(**comun)
        print("   Construyendo el modelo de lenguaje de Lex (1-3 min)...", flush=True)
        esperar(lambda: lex.describe_bot_locale(**comun), "botLocaleStatus", {"Built"}, limite=600)
        registrar("Construcción del bot", True, "slot de tiempo con sinónimos")

        aciertos = []
        for frase, esperado in [("llevo como tres años", "MAS_DE_2_ANOS"),
                                ("acabo de empezar", "MENOS_6_MESES"),
                                ("entreno hace como un año", "ENTRE_6_MESES_Y_2_ANOS")]:
            r = rt.recognize_text(botId=bot_id, botAliasId="TSTALIASID", localeId=locale,
                                  sessionId=f"prueba{int(time.time())}", text=frase,
                                  sessionState={"dialogAction": {"type": "ElicitSlot",
                                                                 "slotToElicit": "tiempo_entrenando"},
                                                "intent": {"name": "ResponderPregunta",
                                                           "state": "InProgress"}})
            valor = (((r.get("sessionState", {}).get("intent", {}).get("slots") or {})
                      .get("tiempo_entrenando") or {}).get("value") or {}).get("interpretedValue")
            aciertos.append(valor == esperado)
            print(f"   «{frase}» → {valor} (esperado {esperado})")
        registrar("Interpretación de texto libre", True if all(aciertos) else None,
                  f"{sum(aciertos)}/3 frases interpretadas correctamente "
                  "(los fallos se corrigen con más sinónimos; los botones siempre funcionan)")
        return True
    except Exception as e:
        registrar("Amazon Lex", False, error_corto(e))
        return False


# ---------------------------------------------------------------- 5 y 6. Bedrock
def prueba_bedrock():
    paso("5. Amazon Bedrock · Nova Micro")
    rt = ses.client("bedrock-runtime")
    ok = False
    for modelo in ("amazon.nova-micro-v1:0", "us.amazon.nova-micro-v1:0"):
        try:
            r = rt.converse(modelId=modelo, messages=[{"role": "user", "content": [
                {"text": "Responde solo con la palabra: listo"}]}],
                inferenceConfig={"maxTokens": 10, "temperature": 0})
            texto = r["output"]["message"]["content"][0]["text"].strip()
            registrar("Invocación de Nova Micro", True, f"modelo {modelo} respondió «{texto}»")
            contexto["modelo_nova"] = modelo
            ok = True
            break
        except Exception as e:
            print(f"   {modelo}: {error_corto(e)}")
    if not ok:
        registrar("Invocación de Nova Micro", False,
                  "sin acceso al modelo: si el mensaje dice 'account is currently being "
                  "verified', esperar la verificación de la cuenta y repetir solo esta prueba")

    paso("6. Amazon Bedrock · Automated Reasoning checks")
    try:
        br = ses.client("bedrock")
        if not hasattr(br, "list_automated_reasoning_policies"):
            registrar("Automated Reasoning", None, "boto3 no trae la API; actualizar e intentar")
            return
        pols = br.list_automated_reasoning_policies(maxResults=5).get(
            "automatedReasoningPolicySummaries", [])
        registrar("Automated Reasoning", True,
                  f"servicio accesible ({len(pols)} políticas existentes)")
    except Exception as e:
        registrar("Automated Reasoning", False, error_corto(e))


# ---------------------------------------------------------------- 7. Otros servicios
def prueba_permisos():
    paso("7. Cognito, CloudFront, API Gateway, S3")
    pruebas = [
        ("Cognito", lambda: ses.client("cognito-idp").list_user_pools(MaxResults=1)),
        ("CloudFront", lambda: ses.client("cloudfront").list_distributions(MaxItems="1")),
        ("API Gateway (HTTP API)", lambda: ses.client("apigatewayv2").get_apis(MaxResults="1")),
        ("S3", lambda: ses.client("s3").list_buckets()),
        ("CloudFormation", lambda: ses.client("cloudformation").list_stacks()),
    ]
    for nombre, fn in pruebas:
        try:
            fn()
            registrar(nombre, True, "acceso permitido")
        except Exception as e:
            registrar(nombre, False, error_corto(e))


def prueba_free_tier():
    paso("8. Uso del Free Tier")
    try:
        ft = ses.client("freetier", region_name="us-east-1")
        uso = ft.get_free_tier_usage().get("freeTierUsages", [])
        relevantes = [u for u in uso if any(s in u.get("service", "")
                      for s in ("RDS", "Aurora", "Lambda", "Lex", "Bedrock"))]
        if relevantes:
            for u in relevantes:
                print(f"   {u['service']} · {u.get('description', '')[:60]} · "
                      f"{u.get('actualUsageAmount')} de {u.get('limit')} {u.get('unit')}")
        registrar("Consulta de Free Tier", True,
                  f"{len(uso)} ofertas visibles; el uso de Aurora aparece en ~24 h")
    except Exception as e:
        registrar("Consulta de Free Tier", None,
                  f"no se pudo consultar por API ({error_corto(e)}); revisarlo en la consola")


# ---------------------------------------------------------------- Limpieza
def limpiar():
    paso("Limpieza de recursos de prueba (Aurora se conserva)")
    iam, lam, lex = ses.client("iam"), ses.client("lambda"), ses.client("lexv2-models")
    acciones = [
        lambda: lam.delete_function(FunctionName=LAMBDA),
        lambda: iam.delete_role_policy(RoleName=ROL_LAMBDA, PolicyName="conectar-aurora"),
        lambda: iam.detach_role_policy(RoleName=ROL_LAMBDA, PolicyArn=(
            "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole")),
        lambda: iam.delete_role(RoleName=ROL_LAMBDA),
        lambda: contexto.get("bot_id") and lex.delete_bot(botId=contexto["bot_id"],
                                                         skipResourceInUseCheck=True),
        lambda: iam.delete_role(RoleName=ROL_LEX),
    ]
    for accion in acciones:
        try:
            accion()
        except Exception:
            pass
    if contexto.get("host"):
        try:
            con = conectar("postgres")
            for sql in ["DROP PROCEDURE IF EXISTS sp_prueba(TEXT)",
                        "DROP TABLE IF EXISTS prueba_viabilidad",
                        "REVOKE rol_prueba FROM app_lambda",
                        "DROP ROLE IF EXISTS rol_prueba"]:
                con.run(sql)
            con.close()
        except Exception as e:
            print(f"   No se limpiaron los objetos de prueba en Aurora: {error_corto(e)}")
    print("   Listo. Quedan: clúster Aurora se-rutinas-db y usuario app_lambda (se reutilizan).")


def main():
    # Sin argumentos se corre todo; con argumentos solo esos bloques.
    # Ej.: python3 fase0.py aurora lex   |   python3 fase0.py bedrock
    pedidos = set(sys.argv[1:]) or {"aurora", "lex", "bedrock", "permisos"}
    try:
        prueba_cuenta()
        if "aurora" in pedidos and prueba_aurora() and prueba_cloudshell():
            prueba_lambda()
        if "lex" in pedidos:
            prueba_lex()
        if "bedrock" in pedidos:
            prueba_bedrock()
        if "permisos" in pedidos:
            prueba_permisos()
            prueba_free_tier()
    except Exception as e:
        registrar("Error inesperado", False, error_corto(e))
        traceback.print_exc()
    finally:
        limpiar()

    lineas = ["REPORTE FASE 0 · Viabilidad de la arquitectura",
              f"Fecha: {time.strftime('%Y-%m-%d %H:%M')} · Región: {REGION}", ""]
    for prueba, estado, detalle in resultados:
        lineas.append(f"[{estado:5}] {prueba}: {detalle}")
    fallos = sum(1 for _, e, _ in resultados if e == "FALLO")
    lineas += ["", f"Resumen: {len(resultados) - fallos} correctas, {fallos} con fallo"]
    reporte = "\n".join(lineas)
    with open(os.path.join(AQUI, "reporte_fase0.txt"), "w", encoding="utf-8") as f:
        f.write(reporte + "\n")
    print("\n" + reporte)
    print("\nCopia el contenido de reporte_fase0.txt y pégalo en el chat.")


if __name__ == "__main__":
    main()
