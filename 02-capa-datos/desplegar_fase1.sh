#!/usr/bin/env bash
# =====================================================================
# FASE 1 · Instala la base de conocimiento en Aurora y la verifica (CloudShell, carpeta fase1).
# Uso: bash desplegar_fase1.sh [--verificar | --reinstalar]
# =====================================================================
set -uo pipefail
cd "$(dirname "$0")"
export AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1
MODO=${1:-}
CLUSTER=se-rutinas-db
REPORTE=reporte_fase1.txt
: > "$REPORTE"
log() { echo "$@" | tee -a "$REPORTE"; }

log "==> Preparando herramientas"
python3 -m pip install --quiet --upgrade -t _deps pg8000 'python-dateutil<3' >/dev/null \
  || { log "No se pudo instalar pg8000"; exit 1; }
[ -f global-bundle.pem ] || curl -sSf -o global-bundle.pem \
  https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem
# El gateway de Aurora express presenta un certificado de una autoridad pública,
# no de la CA de RDS: psql debe confiar en ambas (el sistema + RDS)
CA_SISTEMA=$(python3 -c "import ssl; p=ssl.get_default_verify_paths(); print(p.cafile or p.openssl_cafile)")
for c in "$CA_SISTEMA" /etc/pki/tls/certs/ca-bundle.crt /etc/ssl/certs/ca-certificates.crt; do
  [ -f "$c" ] && { cat "$c" global-bundle.pem > ca-confianza.pem; break; }
done
[ -f ca-confianza.pem ] || cp global-bundle.pem ca-confianza.pem
if ! command -v psql >/dev/null; then
  for v in 17 16 15; do sudo dnf install -y -q "postgresql$v" >/dev/null 2>&1 && break; done
fi
command -v psql >/dev/null || { log "No se encontró psql"; exit 1; }

HOST=$(aws rds describe-db-clusters --db-cluster-identifier "$CLUSTER" \
        --query "DBClusters[0].Endpoint" --output text) || { log "No existe $CLUSTER"; exit 1; }
log "    Clúster: $HOST"
export PGHOST=$HOST PGPORT=5432 PGDATABASE=postgres PGUSER=postgres \
       PGSSLMODE=verify-full PGSSLROOTCERT="$PWD/ca-confianza.pem" PGCONNECT_TIMEOUT=60
token() { aws rds generate-db-auth-token --hostname "$HOST" --port 5432 --username postgres; }
PSQL="psql -v ON_ERROR_STOP=1 -q -X"

log "==> Conectando (si el clúster está en pausa tarda unos segundos en despertar)"
for i in 1 2 3 4 5 6; do
  ERROR=$(PGPASSWORD=$(token) $PSQL -tAc "SELECT 1" 2>&1 >/dev/null) && break
  # Un error de certificado o de autenticación no se arregla esperando
  if echo "$ERROR" | grep -qiE "certificate|SSL error|authentication|password"; then
    log "    Error de conexión: $ERROR"; exit 1
  fi
  log "    intento $i: el clúster aún está despertando..."; sleep 10
done
PGPASSWORD=$(token) $PSQL -tAc "SELECT 1" >/dev/null || { log "No hay conexión con Aurora"; exit 1; }
log "    Conectado"

EXISTE=$(PGPASSWORD=$(token) $PSQL -tAc "SELECT count(*) FROM pg_namespace WHERE nspname = 'se'")

if [ "$MODO" = "--reinstalar" ] && [ "$EXISTE" = "1" ]; then
  read -r -p "Se BORRARÁN todas las tablas y datos del sistema experto. Escribe BORRAR: " r
  [ "$r" = "BORRAR" ] || { log "Cancelado."; exit 0; }
  PGPASSWORD=$(token) PGOPTIONS='-c role=se_owner' $PSQL -c "DROP SCHEMA se CASCADE" \
    && log "    Esquema anterior eliminado"
  EXISTE=0
fi

if [ "$MODO" != "--verificar" ]; then
  if [ "$EXISTE" = "1" ]; then
    log "==> El esquema ya está instalado; se omite la instalación"
    log "    (usa --reinstalar para empezar de cero o --verificar para solo verificar)"
  else
    log "==> Instalando la base de conocimiento"
    PGPASSWORD=$(token) $PSQL -f sql/00_preparacion.sql && log "    00_preparacion.sql OK" \
      || { log "Fallo en 00_preparacion.sql"; exit 1; }
    for f in sql/01_esquema.sql sql/02_permisos.sql sql/03_procedimientos.sql \
             sql/04_carga_conocimiento.sql sql/05_una_consulta_abierta.sql \
             sql/06_roles_y_verificacion.sql; do
      PGPASSWORD=$(token) PGOPTIONS='-c role=se_owner' $PSQL -f "$f" \
        && log "    $(basename "$f") OK" || { log "Fallo en $f"; exit 1; }
    done
  fi
fi

log ""
log "==> Validador estructural de la base de conocimiento"
PGUSER=app_lambda PGPASSWORD=$(aws rds generate-db-auth-token \
  --hostname "$HOST" --port 5432 --username app_lambda) \
  $PSQL -c "SET ROLE rol_ingeniero_conocimiento" -c "SELECT * FROM fn_validar_base()" | tee -a "$REPORTE"

log ""
log "==> Verificación del razonamiento (48 caminos, 720 combinaciones)"
(cd verificacion && python3 verificar_caminos.py aurora) 2>&1 | tee -a "$REPORTE"

log ""
log "==> Pruebas de seguridad por rol"
(cd verificacion && python3 pruebas_seguridad.py aurora) 2>&1 | tee -a "$REPORTE"

log ""
log "Reporte guardado en fase1/$REPORTE"
