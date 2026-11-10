"""Pruebas de la Fase 3 contra la Lambda desplegada (Lex, Nova y Automated Reasoning reales)."""

import sys

from escenarios_ia import correr_ia
from probar_lambda import llamar

if __name__ == "__main__":
    print("Despertando la base...", flush=True)
    print("  ", llamar("despertar", {"sub": "pendiente-cognito-laura", "grupo": "usuario_final"}, {}))
    sys.exit(1 if correr_ia(llamar) else 0)
