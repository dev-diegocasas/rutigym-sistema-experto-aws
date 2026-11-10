"""Prueba la API real por HTTPS con tokens de Cognito.
Uso: python3 probar_api.py <ApiUrl> <ClienteWebId>"""

import json
import os
import sys
import urllib.error
import urllib.request

import boto3

from escenarios_api import correr_api

AQUI = os.path.dirname(os.path.abspath(__file__))
API, CLIENTE = sys.argv[1].rstrip("/"), sys.argv[2]
cognito = boto3.client("cognito-idp", region_name="us-east-1")

CREDENCIALES = {}
for linea in open(os.path.join(AQUI, "..", "credenciales_demo.txt"), encoding="utf-8"):
    partes = [p.strip() for p in linea.split("|")]
    if len(partes) == 4 and "@" in partes[1]:
        CREDENCIALES[partes[0]] = (partes[1], partes[3])

_tokens = {}


def token(cuenta):
    if cuenta == "token-falso":
        return "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ4In0.firma-falsa"
    if cuenta not in _tokens:
        correo, clave = CREDENCIALES[cuenta]
        r = cognito.initiate_auth(ClientId=CLIENTE, AuthFlow="USER_PASSWORD_AUTH",
                                  AuthParameters={"USERNAME": correo, "PASSWORD": clave})
        _tokens[cuenta] = r["AuthenticationResult"]["IdToken"]
    return _tokens[cuenta]


def api(metodo, ruta, cuenta, cuerpo):
    cabeceras = {"Content-Type": "application/json"}
    if cuenta:
        cabeceras["Authorization"] = f"Bearer {token(cuenta)}"
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    peticion = urllib.request.Request(API + ruta, data=datos, method=metodo, headers=cabeceras)
    try:
        with urllib.request.urlopen(peticion, timeout=35) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        cuerpo = e.read()
        try:
            return e.code, json.loads(cuerpo or b"{}")
        except ValueError:
            return e.code, {"error": cuerpo.decode(errors="replace")[:200]}


if __name__ == "__main__":
    print("Despertando la base...", flush=True)
    print("  ", api("POST", "/despertar", None, None))
    for cuenta in ("diego", "simon", "cristian", "laura", "andres"):
        token(cuenta)
    print(f"   Sesiones iniciadas en Cognito: {len(_tokens)}")
    fallos, correo = correr_api(api, real=True)
    with open(os.path.join(AQUI, "prueba_creada.txt"), "w") as f:
        f.write(correo)
    sys.exit(1 if fallos else 0)
