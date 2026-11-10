#!/usr/bin/env bash
# FASE 0 · Prueba de viabilidad en CloudShell (us-east-1).
# Uso: bash ejecutar_fase0.sh [aurora|lex|bedrock ...]
set -uo pipefail
cd "$(dirname "$0")"
export AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1

echo "==> Instalando pg8000 en la carpeta local _deps"
# CloudShell usa un entorno virtual: no admite '--user', por eso se instala con -t
python3 -m pip install --quiet --upgrade -t _deps pg8000 'python-dateutil<3' \
  || { echo "No se pudo instalar pg8000"; exit 1; }

echo "==> Descargando el certificado de Amazon RDS para conexiones SSL"
curl -sSf -o global-bundle.pem https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem \
  || echo "   (no se pudo descargar; se usará la cadena de confianza del sistema)"

python3 fase0.py "$@" 2>&1 | tee salida_fase0.log
