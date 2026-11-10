"""Pruebas del motor desplegado: invoca directamente la Lambda se-motor-inferencia."""

import json
import sys

import boto3
from botocore.config import Config

from escenarios import correr

cliente = boto3.client("lambda", region_name="us-east-1",
                       config=Config(read_timeout=60, retries={"max_attempts": 0}))


def llamar(accion, identidad, parametros):
    r = cliente.invoke(FunctionName="se-motor-inferencia", Payload=json.dumps(
        {"accion": accion, "identidad": identidad, "parametros": parametros}).encode())
    cuerpo = json.loads(r["Payload"].read())
    if "statusCode" not in cuerpo:                       # la Lambda falló antes de responder
        return 500, {"error": cuerpo.get("errorMessage", str(cuerpo))}
    return cuerpo["statusCode"], json.loads(cuerpo["body"])


if __name__ == "__main__":
    completo = "--rapido" not in sys.argv
    print("Despertando la base (puede tardar ~20 s si estaba en pausa)...", flush=True)
    print("  ", llamar("despertar", {"sub": "pendiente-cognito-laura", "grupo": "usuario_final"}, {}))
    sys.exit(1 if correr(llamar, completo) else 0)
