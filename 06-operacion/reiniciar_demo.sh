#!/usr/bin/env bash
# =====================================================================
# Reinicia los datos para la demostración y limpia sobrantes en la nube (carpeta limpieza).
# Uso: bash reiniciar_demo.sh [--aplicar]
# =====================================================================
set -uo pipefail
cd "$(dirname "$0")"
export AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1
MODO=${1:---revisar}
CLUSTER=se-rutinas-db
REPORTE=reporte_reinicio.txt
: > "$REPORTE"
log() { echo "$@" | tee -a "$REPORTE"; }

[ -f ../fase1/sql/04_carga_conocimiento.sql ] || { log "No encuentro ../fase1 (descomprime limpieza junto a fase1)"; exit 1; }

# ------------------------------------------------------------ Conexión a Aurora
command -v psql >/dev/null || for v in 17 16 15; do
  sudo dnf install -y -q "postgresql$v" >/dev/null 2>&1 && break; done
command -v psql >/dev/null || { log "No se encontró psql"; exit 1; }
if [ ! -f ca-confianza.pem ]; then
  if [ -f ../fase1/ca-confianza.pem ]; then cp ../fase1/ca-confianza.pem .
  else
    curl -sSf -o global-bundle.pem https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem
    CA=$(python3 -c "import ssl; p=ssl.get_default_verify_paths(); print(p.cafile or p.openssl_cafile)")
    cat "$CA" global-bundle.pem > ca-confianza.pem
  fi
fi
HOST=$(aws rds describe-db-clusters --db-cluster-identifier "$CLUSTER" \
        --query "DBClusters[0].Endpoint" --output text) || { log "No existe $CLUSTER"; exit 1; }
export PGHOST=$HOST PGPORT=5432 PGDATABASE=postgres PGUSER=postgres \
       PGSSLMODE=verify-full PGSSLROOTCERT="$PWD/ca-confianza.pem" PGCONNECT_TIMEOUT=60
token() { aws rds generate-db-auth-token --hostname "$HOST" --port 5432 --username postgres; }
PSQL="psql -v ON_ERROR_STOP=1 -q -X"
como_owner() { PGPASSWORD=$(token) PGOPTIONS='-c role=se_owner' $PSQL "$@"; }

# boto3 reciente para las APIs de Automated Reasoning
python3 -m pip install --quiet --upgrade -t _deps boto3 >/dev/null 2>&1 && export PYTHONPATH="$PWD/_deps"

log "==> Conectando con Aurora (si está en pausa tarda unos segundos)"
for i in 1 2 3 4 5 6; do
  PGPASSWORD=$(token) $PSQL -tAc "SELECT 1" >/dev/null 2>&1 && break
  log "    intento $i: el clúster aún está despertando..."; sleep 10
done
PGPASSWORD=$(token) $PSQL -tAc "SELECT 1" >/dev/null || { log "No hay conexión con Aurora"; exit 1; }

estado() { como_owner -P footer=off -f estado_base.sql | tee -a "$REPORTE"; }

if [ "$MODO" != "--aplicar" ]; then
  log ""; log "==> Estado actual de la base"; estado
  log ""; python3 limpiar_nube.py 2>&1 | tee -a "$REPORTE"
  log ""; log "Nada se borró. Para limpiar: bash reiniciar_demo.sh --aplicar"
  exit 0
fi

log ""
read -r -p "Se borrarán todas las consultas, la auditoría y los sobrantes de la nube. Escribe REINICIAR: " r
[ "$r" = "REINICIAR" ] || { log "Cancelado."; exit 0; }

log ""; log "==> 1. Limpieza de la nube"
python3 limpiar_nube.py --aplicar 2>&1 | tee -a "$REPORTE"

log ""; log "==> 2. Recarga de la base de conocimiento (una sola transacción)"
como_owner -1 -f recargar_conocimiento.sql >/dev/null \
  && log "    Base de conocimiento recargada desde 04_carga_conocimiento.sql" \
  || { log "    Falló la recarga; la base quedó como estaba"; exit 1; }

log ""; log "==> 3. Verificación (validador, 48 caminos, 720 combinaciones, seguridad)"
(cd ../fase1 && bash desplegar_fase1.sh --verificar) > verificacion.txt 2>&1
grep -E "combinaciones ·|alcanzables|RESULTADO|correctas|FALLO" verificacion.txt | tee -a "$REPORTE"
grep -q "FALLO" verificacion.txt && log "    Hay fallos: revisa limpieza/verificacion.txt"

log ""; log "==> 4. Consultas, auditoría y contadores en cero"
como_owner -1 -f reiniciar_operacion.sql >/dev/null \
  && log "    Listo: la próxima consulta será la número 1" \
  || { log "    Falló el reinicio de las tablas de operación"; exit 1; }

log ""; log "==> 5. Reinicio del motor"
python3 limpiar_nube.py --reiniciar-motor 2>&1 | tee -a "$REPORTE"

log ""; log "==> 6. Archivos temporales de CloudShell"
LIBERADO=$(du -sh ~ 2>/dev/null | cut -f1)
rm -rf ~/fase*/build ~/fase*/.aws-sam ~/fase*/paquete.zip ~/ajuste*/paquete.zip ~/fase*.zip ~/ajuste*.zip 2>/dev/null
log "    Espacio usado antes: $LIBERADO · ahora: $(du -sh ~ 2>/dev/null | cut -f1)"
log "    (se conservan el código, los reportes y credenciales_demo.txt)"

log ""; log "==> Estado final de la base"; estado
log ""
log "Reinicio terminado. En el navegador cierra sesión y vuelve a entrar."
log "Reporte guardado en limpieza/$REPORTE"
