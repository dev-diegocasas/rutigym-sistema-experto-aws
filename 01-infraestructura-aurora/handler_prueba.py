"""Lambda de prueba: se conecta a Aurora con token IAM, cambia de rol (SET ROLE)
y ejecuta un procedimiento almacenado. Valida el patrón que usará el motor."""

import os
import ssl

import boto3
import pg8000.native


def _contexto_ssl():
    ctx = ssl.create_default_context()
    bundle = os.path.join(os.path.dirname(__file__), "global-bundle.pem")
    if os.path.exists(bundle):
        ctx.load_verify_locations(bundle)
    return ctx


def handler(event, context):
    host = os.environ["DB_HOST"]
    region = os.environ.get("AWS_REGION", "us-east-1")
    token = boto3.client("rds").generate_db_auth_token(
        DBHostname=host, Port=5432, DBUsername="app_lambda", Region=region)
    con = pg8000.native.Connection(
        user="app_lambda", host=host, port=5432, database="postgres",
        password=token, ssl_context=_contexto_ssl(), timeout=15)
    try:
        con.run("SET ROLE rol_prueba")
        con.run("CALL sp_prueba('lambda')")
        filas = con.run("SELECT count(*) FROM prueba_viabilidad")[0][0]
        rol = con.run("SELECT current_user")[0][0]
        version = con.run("SELECT version()")[0][0]
    finally:
        con.close()
    return {"ok": True, "filas": filas, "rol_activo": rol, "version": version[:60]}
