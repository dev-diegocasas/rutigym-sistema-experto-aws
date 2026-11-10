"""Conexión de solo lectura a la base de conocimiento para los scripts de la Fase 3."""
import os
import ssl
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "..", "_deps"))
import boto3  # noqa: E402
import pg8000.native  # noqa: E402

REGION = "us-east-1"


def conectar_lectura():
    rds = boto3.client("rds", region_name=REGION)
    host = rds.describe_db_clusters(DBClusterIdentifier="se-rutinas-db")["DBClusters"][0]["Endpoint"]
    token = rds.generate_db_auth_token(DBHostname=host, Port=5432, DBUsername="app_lambda",
                                       Region=REGION)
    ctx = ssl.create_default_context()
    bundle = os.path.join(AQUI, "..", "global-bundle.pem")
    if os.path.exists(bundle):
        ctx.load_verify_locations(bundle)
    con = pg8000.native.Connection(user="app_lambda", host=host, database="postgres",
                                   password=token, ssl_context=ctx, timeout=60)
    con.run("SET ROLE rol_experto")
    return con


def preguntas_y_opciones():
    """[{codigo, atributo, texto, opciones: [{codigo_hecho, valor, texto_opcion, sinonimos}]}]"""
    con = conectar_lectura()
    try:
        preguntas = [dict(zip(("id", "codigo", "atributo", "texto"), f)) for f in con.run(
            "SELECT id_pregunta, codigo, atributo, texto FROM preguntas ORDER BY orden")]
        for p in preguntas:
            p["opciones"] = [dict(zip(("codigo_hecho", "valor", "texto_opcion", "sinonimos"), f))
                             for f in con.run(
                "SELECT he.codigo, he.valor, r.texto_opcion, r.sinonimos FROM respuesta_pregunta r "
                "JOIN hechos he ON he.id_hecho = r.id_hecho WHERE he.id_pregunta = :p "
                "ORDER BY r.orden", p=p["id"])]
        hipotesis = [dict(zip(("codigo", "nivel", "equipo", "objetivo", "fase", "dias", "actividad"), f))
                     for f in con.run("SELECT codigo, nivel::TEXT, equipo::TEXT, objetivo::TEXT, "
                                      "fase::TEXT, dias_semana::TEXT, actividad::TEXT FROM hipotesis "
                                      "ORDER BY codigo")]
        return preguntas, hipotesis
    finally:
        con.close()
