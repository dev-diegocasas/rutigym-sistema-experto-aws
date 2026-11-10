"""Pruebas locales de la API (solo desarrollo): simula los eventos de API Gateway
con los claims que pondría Cognito y usa dobles de los servicios de AWS."""
import json
import os
import sys
import uuid

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "..", "motor"))
os.environ.update(DB_MODO="local", DB_NOMBRE="prueba", DB_SOCKET="/var/tmp/pgtest/.s.PGSQL.5499",
                  USAR_LEX="false", USAR_NOVA="false", USAR_AR="false")
import servicio  # noqa: E402
from escenarios_api import correr_api  # noqa: E402

GRUPO = {"diego": "administrador", "simon": "ingeniero_conocimiento", "cristian": "experto", "profesor": "experto",
         "laura": None, "andres": None}


class VerificadorFalso:
    def verificar(self, hechos, codigo):
        return "VALID", {"servicio": "AR (doble)"}


class CuentasFalsas:
    def crear(self, correo, nombre, grupo):
        return str(uuid.uuid4()), "Tmp-Prueba123a!"

    def eliminar(self, correo):
        pass

    def cambiar_grupo(self, correo, anterior, nuevo):
        pass

    def cambiar_estado(self, correo, activo):
        pass


servicio.IA.verificador = VerificadorFalso()
servicio.IA.cuentas = CuentasFalsas()


def api(metodo, ruta, cuenta, cuerpo):
    claims = {}
    if cuenta:
        claims = {"sub": f"pendiente-cognito-{cuenta}", "email": f"{cuenta}@sistema-experto.test",
                  "name": cuenta}
        if GRUPO.get(cuenta):
            claims["cognito:groups"] = f"[{GRUPO[cuenta]}]"
    evento = {"version": "2.0", "rawPath": ruta,
              "requestContext": {"http": {"method": metodo, "path": ruta},
                                 "authorizer": {"jwt": {"claims": claims}}},
              "body": json.dumps(cuerpo) if cuerpo is not None else None}
    r = servicio.lambda_handler(evento, None)
    return r["statusCode"], json.loads(r["body"])


fallos, _ = correr_api(api, real=False)
sys.exit(1 if fallos else 0)
