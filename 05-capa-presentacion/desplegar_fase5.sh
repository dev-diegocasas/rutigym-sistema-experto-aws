#!/usr/bin/env bash
# =====================================================================
# FASE 5 · Página en S3 privado + CloudFront; la API solo acepta este dominio (carpeta fase5).
# =====================================================================
set -uo pipefail
cd "$(dirname "$0")"
export AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1
MODO=${1:-}
API_STACK=se-rutinas-motor
WEB_STACK=se-rutinas-web
REPORTE=reporte_fase5.txt
: > "$REPORTE"
log() { echo "$@" | tee -a "$REPORTE"; }
salida() {
  aws cloudformation describe-stacks --stack-name "$1" \
    --query "Stacks[0].Outputs[?OutputKey=='$2'].OutputValue" --output text 2>/dev/null
}

API_URL=$(salida $API_STACK ApiUrl); POOL=$(salida $API_STACK UserPoolId); CLIENTE=$(salida $API_STACK ClienteWebId)
[ -n "$API_URL" ] && [ "$API_URL" != "None" ] || { log "No se encontró la API (Fase 4)"; exit 1; }
log "==> API: $API_URL"

if [ -z "$MODO" ]; then
  log ""
  log "==> 1. Bucket privado y distribución de CloudFront (puede tardar 3-6 minutos)"
  aws cloudformation deploy --stack-name "$WEB_STACK" --template-file template-web.yaml \
    --parameter-overrides "ApiUrl=$API_URL" --no-fail-on-empty-changeset 2>&1 | tail -2 | tee -a "$REPORTE"
fi

BUCKET=$(salida $WEB_STACK BucketWeb); DISTRIBUCION=$(salida $WEB_STACK DistribucionId)
URL_WEB=$(salida $WEB_STACK UrlWeb)
[ -n "$BUCKET" ] && [ "$BUCKET" != "None" ] || { log "No se encontró el stack de la web"; exit 1; }
log "    Sitio: $URL_WEB"

if [ "$MODO" != "--cors" ]; then
log ""
log "==> 2. Publicando la interfaz"
cat > web/config.js <<EOF
window.SE_CONFIG = { api: "$API_URL", region: "$AWS_REGION", cliente: "$CLIENTE" };
EOF
# index.html y config.js se revalidan siempre; css y js 5 minutos; la fuente un año
aws s3 cp web/index.html "s3://$BUCKET/index.html" --cache-control "no-cache" \
  --content-type "text/html; charset=utf-8" >/dev/null
aws s3 cp web/config.js "s3://$BUCKET/config.js" --cache-control "no-cache" \
  --content-type "text/javascript; charset=utf-8" >/dev/null
aws s3 cp web/app.js "s3://$BUCKET/app.js" --cache-control "public, max-age=300" \
  --content-type "text/javascript; charset=utf-8" >/dev/null
aws s3 cp web/estilos.css "s3://$BUCKET/estilos.css" --cache-control "public, max-age=300" \
  --content-type "text/css; charset=utf-8" >/dev/null
for f in web/fuentes/*.woff2; do
  aws s3 cp "$f" "s3://$BUCKET/fuentes/$(basename "$f")" \
    --cache-control "public, max-age=31536000, immutable" --content-type "font/woff2" >/dev/null
done
# Fuentes de diseños anteriores que ya no se usan
for viejo in instrument-sans barlow-400 barlow-600 barlow-condensed-600; do
  aws s3 rm "s3://$BUCKET/fuentes/$viejo.woff2" >/dev/null 2>&1 || true
done
aws s3 cp web/fuentes/OFL.txt "s3://$BUCKET/fuentes/OFL.txt" --content-type "text/plain; charset=utf-8" >/dev/null
TOTAL=$(aws s3 ls "s3://$BUCKET" --recursive --summarize | awk '/Total Size/ {print $3}')
log "    Archivos publicados ($TOTAL bytes en total)"
aws cloudfront create-invalidation --distribution-id "$DISTRIBUCION" --paths "/*" >/dev/null \
  && log "    Caché de CloudFront renovada"
fi

if [ -z "$MODO" ] || [ "$MODO" = "--cors" ]; then
  log ""
  log "==> 3. Restringiendo la API al dominio de la interfaz (CORS)"
  # Se aplica directo sobre la API: la plantilla de SAM fija el valor de CORS al
  # transformarse, así que cambiar solo el parámetro no tiene efecto.
  API_ID=$(echo "$API_URL" | sed -E 's#https://([^.]+)\..*#\1#')
  if aws apigatewayv2 update-api --api-id "$API_ID" --cors-configuration \
       "{\"AllowOrigins\":[\"$URL_WEB\"],\"AllowMethods\":[\"GET\",\"POST\",\"PUT\",\"DELETE\",\"OPTIONS\"],\"AllowHeaders\":[\"authorization\",\"content-type\"],\"MaxAge\":600}" \
       >/dev/null 2>error_cors.txt; then
    log "    La API solo acepta peticiones de navegador desde $URL_WEB"
  else
    log "    No se pudo actualizar CORS: $(cat error_cors.txt)"
  fi
  sleep 5
fi

log ""
log "==> 4. Comprobaciones"
for i in $(seq 1 30); do
  CODIGO=$(curl -s -o /dev/null -w "%{http_code}" "$URL_WEB/") && [ "$CODIGO" = "200" ] && break
  sleep 10
done
log "    Sitio por HTTPS: $CODIGO"
CABECERAS=$(curl -sI "$URL_WEB/")
for c in content-security-policy strict-transport-security x-frame-options x-content-type-options; do
  echo "$CABECERAS" | grep -qi "^$c:" && log "    Cabecera $c: presente" || log "    Cabecera $c: FALTA"
done
log "    Redirección de http a https: $(curl -s -o /dev/null -w "%{http_code}" "${URL_WEB/https/http}/")"
log "    Bucket directo (debe negarse): $(curl -s -o /dev/null -w "%{http_code}" "https://$BUCKET.s3.amazonaws.com/index.html")"
log "    Compresión: $(curl -s -H 'Accept-Encoding: br, gzip' -o /dev/null -w '%{size_download}' "$URL_WEB/app.js") bytes transferidos de app.js ($(wc -c < web/app.js) sin comprimir)"
PREVIA=$(curl -s -o /dev/null -D - -X OPTIONS "$API_URL/perfil" -H "Origin: $URL_WEB" \
  -H "Access-Control-Request-Method: GET" -H "Access-Control-Request-Headers: authorization,content-type")
ESTADO=$(echo "$PREVIA" | head -1 | awk '{print $2}')
ACAO=$(echo "$PREVIA" | grep -i "^access-control-allow-origin" | tr -d '\r')
log "    Consulta previa de CORS (debe ser 2xx): $ESTADO"
log "    CORS desde la interfaz: ${ACAO:-sin cabecera}"
OTRO=$(curl -s -o /dev/null -D - -X OPTIONS "$API_URL/perfil" -H "Origin: https://sitio-ajeno.example" \
  -H "Access-Control-Request-Method: GET" | grep -i "^access-control-allow-origin" | tr -d '\r')
log "    CORS desde otro sitio (debe estar vacío): ${OTRO:-sin cabecera}"

log ""
log "Abre el sistema en: $URL_WEB"
log "Reporte guardado en fase5/$REPORTE"
