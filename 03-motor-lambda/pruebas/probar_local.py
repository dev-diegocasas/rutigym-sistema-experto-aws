"""Pruebas del motor contra un PostgreSQL local (solo desarrollo)."""

import json, os, sys
AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "..", "motor"))
os.environ.update(DB_MODO="local", DB_NOMBRE="prueba", DB_SOCKET="/var/tmp/pgtest/.s.PGSQL.5499",
                  USAR_LEX="false", USAR_NOVA="false", USAR_AR="false")
import servicio  # noqa: E402
from escenarios import correr  # noqa: E402

def llamar(accion, identidad, parametros):
    r = servicio.lambda_handler({"accion": accion, "identidad": identidad, "parametros": parametros}, None)
    return r["statusCode"], json.loads(r["body"])

sys.exit(1 if correr(llamar) else 0)
