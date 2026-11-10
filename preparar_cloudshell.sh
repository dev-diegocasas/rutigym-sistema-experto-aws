#!/usr/bin/env bash
# Copia esta entrega a las carpetas con las que se desplegó en AWS CloudShell
# (~/fase0 ... ~/fase5 y ~/limpieza). Los scripts de despliegue usan esas rutas.
#   bash preparar_cloudshell.sh
set -euo pipefail
cd "$(dirname "$0")"
copiar() { mkdir -p "$2" && cp -r "$1"/. "$2"/; echo "  $1 -> $2"; }
copiar 01-infraestructura-aurora ~/fase0
copiar 02-capa-datos            ~/fase1
copiar 03-motor-lambda          ~/fase4
copiar 04-servicios-ia          ~/fase3
copiar 05-capa-presentacion     ~/fase5
copiar 06-operacion             ~/limpieza
echo "Listo. Orden de despliegue: fase0 -> fase1 -> fase3 (--ia) -> fase4 -> fase5"
