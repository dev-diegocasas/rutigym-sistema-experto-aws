#!/usr/bin/env bash
# Borra el clúster Aurora de prueba. SOLO si la Fase 0 falló o quieres empezar de cero.
# Uso: bash borrar_aurora.sh
set -uo pipefail
export AWS_REGION=us-east-1
CLUSTER=se-rutinas-db
read -r -p "Esto borra el clúster $CLUSTER y todos sus datos. Escribe BORRAR para confirmar: " r
[ "$r" = "BORRAR" ] || { echo "Cancelado."; exit 0; }
for i in $(aws rds describe-db-clusters --db-cluster-identifier "$CLUSTER" \
            --query "DBClusters[0].DBClusterMembers[].DBInstanceIdentifier" --output text); do
  aws rds delete-db-instance --db-instance-identifier "$i" --skip-final-snapshot >/dev/null \
    && echo "Instancia $i en borrado"
done
aws rds delete-db-cluster --db-cluster-identifier "$CLUSTER" --skip-final-snapshot >/dev/null \
  && echo "Clúster $CLUSTER en borrado (tarda unos minutos)"
