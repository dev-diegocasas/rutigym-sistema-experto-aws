#!/usr/bin/env bash
# =====================================================================
# FASE 4 · Cognito + API Gateway (JWT) + Lambda del motor (CloudShell, carpeta fase4).
# Uso: bash desplegar_fase4.sh [--probar | --cuentas]
# =====================================================================
set -uo pipefail
cd "$(dirname "$0")"
export AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1
MODO=${1:-}
STACK=se-rutinas-motor
REPORTE=reporte_fase4.txt
: > "$REPORTE"
log() { echo "$@" | tee -a "$REPORTE"; }
INICIO=$(date -u +"%Y-%m-%d %H:%M:%S+00")

log "==> Preparando herramientas"
python3 -m pip install --quiet --upgrade -t _deps pg8000 'python-dateutil<3' >/dev/null 2>&1
[ -f global-bundle.pem ] || curl -sSf -o global-bundle.pem \
  https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem
CA_SISTEMA=$(python3 -c "import ssl; p=ssl.get_default_verify_paths(); print(p.cafile or p.openssl_cafile)")
for c in "$CA_SISTEMA" /etc/pki/tls/certs/ca-bundle.crt /etc/ssl/certs/ca-certificates.crt; do
  [ -f "$c" ] && { cat "$c" global-bundle.pem > ca-confianza.pem; break; }
done
read -r HOST RESOURCE_ID < <(aws rds describe-db-clusters --db-cluster-identifier se-rutinas-db \
  --query "DBClusters[0].[Endpoint,DbClusterResourceId]" --output text)
log "    Clúster: $HOST"
export PGHOST=$HOST PGPORT=5432 PGDATABASE=postgres PGUSER=postgres \
       PGSSLMODE=verify-full PGSSLROOTCERT="$PWD/ca-confianza.pem" PGCONNECT_TIMEOUT=60
token() { aws rds generate-db-auth-token --hostname "$HOST" --port 5432 --username postgres; }
PSQL_OWNER() { PGPASSWORD=$(token) PGOPTIONS='-c role=se_owner' psql -v ON_ERROR_STOP=1 -q -X "$@"; }
for i in 1 2 3 4 5 6; do
  PGPASSWORD=$(token) psql -X -tAc "SELECT 1" >/dev/null 2>&1 && break
  log "    el clúster está despertando..."; sleep 10
done
export PYTHONPATH="$PWD/_deps"
salida() {
  aws cloudformation describe-stacks --stack-name "$STACK" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}

if [ -z "$MODO" ]; then
  log ""
  log "==> 1. Desplegando Cognito, API Gateway y el motor (CloudFormation)"
  rm -rf build && mkdir build
  python3 -m pip install --quiet -t build pg8000 'python-dateutil<3' boto3 >/dev/null 2>&1 \
    || { log "No se pudieron instalar las dependencias"; exit 1; }
  cp motor/*.py build/ && cp global-bundle.pem build/
  sam deploy --template-file template.yaml --stack-name "$STACK" \
    --capabilities CAPABILITY_IAM --resolve-s3 --no-confirm-changeset \
    --no-fail-on-empty-changeset \
    --parameter-overrides "DbHost=$HOST" "DbResourceId=$RESOURCE_ID" 2>&1 | tail -4 | tee -a "$REPORTE"
  aws lambda wait function-updated-v2 --function-name se-motor-inferencia 2>/dev/null
fi

API_URL=$(salida ApiUrl); POOL=$(salida UserPoolId); CLIENTE=$(salida ClienteWebId)
if [ -z "$API_URL" ] || [ "$API_URL" = "None" ]; then
  log "No se encontraron las salidas del stack $STACK"; exit 1
fi
log "    API:     $API_URL"
log "    Cognito: $POOL · cliente $CLIENTE"

if [ -z "$MODO" ] || [ "$MODO" = "--cuentas" ]; then
  log ""
  log "==> 2. Cuentas de demostración en Cognito (correo verificado, sin enviar correos)"
  python3 cuentas/crear_cuentas.py "$POOL" 2>&1 | tee -a "$REPORTE"
fi

if [ -z "$MODO" ] || [ "$MODO" = "--probar" ]; then
  log ""
  log "==> 3. Pruebas de la API por HTTPS con tokens reales de cada rol"
  (cd pruebas && python3 probar_api.py "$API_URL" "$CLIENTE") 2>&1 | tee -a "$REPORTE"

  log ""
  log "==> Limpieza de lo creado por las pruebas"
  PRUEBA=$(cat pruebas/prueba_creada.txt 2>/dev/null || true)
  if [ -n "$PRUEBA" ]; then
    aws cognito-idp admin-delete-user --user-pool-id "$POOL" --username "$PRUEBA" 2>/dev/null
  fi
  PSQL_OWNER -c "DELETE FROM se.consulta WHERE fecha_inicio >= '$INICIO';
                 DELETE FROM se.usuario WHERE correo LIKE 'prueba-api-%';" \
    && log "    Listo (la auditoría conserva el registro de los cambios)"
fi

log ""
log "Resumen"
log "    API:          $API_URL"
log "    User pool:    $POOL"
log "    Cliente web:  $CLIENTE"
log "    Contraseñas:  fase4/credenciales_demo.txt (no se incluyen en este reporte)"
log ""
log "Reporte guardado en fase4/$REPORTE"
