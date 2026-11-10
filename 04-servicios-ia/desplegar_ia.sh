#!/usr/bin/env bash
# =====================================================================
# Servicios de IA: bot de Lex y política de Automated Reasoning (CloudShell, carpeta fase3).
# Uso: bash desplegar_ia.sh [--lex | --politica]
# =====================================================================
set -uo pipefail
cd "$(dirname "$0")"
export AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1
MODO=${1:---ia}   # en esta entrega solo Lex y la política formal; el motor se despliega con 03-motor-lambda
REPORTE=reporte_fase3.txt
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

if [ "$MODO" = "--ia" ] || [ "$MODO" = "--lex" ]; then
  log ""
  log "==> 1. Amazon Lex: bot generado desde la base de conocimiento"
  (cd ia && python3 sincronizar_lex.py) 2>&1 | tee -a "$REPORTE"
fi

if [ "$MODO" = "--ia" ] || [ "$MODO" = "--politica" ]; then
  log ""
  log "==> 2. Bedrock Automated Reasoning: reglas del experto en lógica formal"
  (cd ia && python3 verificador_ar.py) 2>&1 | tee -a "$REPORTE"
fi

if [ -z "$MODO" ]; then
  log ""
  log "==> 3. Actualizando el motor de inferencia (Lambda)"
  rm -rf build && mkdir build
  # Se incluye boto3 actualizado: la verificación formal usa APIs recientes de Bedrock
  python3 -m pip install --quiet -t build pg8000 'python-dateutil<3' boto3 >/dev/null 2>&1 \
    || { log "No se pudieron instalar las dependencias"; exit 1; }
  cp motor/*.py build/ && cp global-bundle.pem build/
  sam deploy --template-file template.yaml --stack-name se-rutinas-motor \
    --capabilities CAPABILITY_IAM --resolve-s3 --no-confirm-changeset \
    --no-fail-on-empty-changeset \
    --parameter-overrides "DbHost=$HOST" "DbResourceId=$RESOURCE_ID" 2>&1 | tail -3 | tee -a "$REPORTE"
  aws lambda wait function-updated-v2 --function-name se-motor-inferencia 2>/dev/null
  log "    $(ls build/*.py | wc -l) módulos desplegados"
fi

if [ -z "$MODO" ] || [ "$MODO" = "--probar" ]; then
  log ""
  log "==> 4. Regresión del motor (muestra de caminos y reglas del servicio)"
  (cd pruebas && python3 probar_lambda.py --rapido) 2>&1 | tail -22 | tee -a "$REPORTE"
  log ""
  log "==> 5. Pruebas de los servicios de IA a través de la Lambda"
  (cd pruebas && python3 probar_lambda_ia.py) 2>&1 | tee -a "$REPORTE"

  log ""
  log "==> Limpieza de las consultas creadas por las pruebas"
  PSQL_OWNER -c "DELETE FROM se.consulta WHERE fecha_inicio >= '$INICIO';
                 DELETE FROM se.usuario WHERE cognito_sub LIKE 'prueba-automatica%';" \
    && log "    Listo"
fi

log ""
log "Reporte guardado en fase3/$REPORTE"
