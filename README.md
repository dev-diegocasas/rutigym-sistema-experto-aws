# Rutigym · Sistema experto de rutinas de entrenamiento en AWS

Código completo con el que se montó el sistema experto en la nube (cuenta AWS, región us-east-1). Es la versión desplegada al 10 de noviembre de 2026, que incluye los ajustes 1 a 8.

## Arquitectura de tres capas

El sistema sigue una **arquitectura de tres capas**. Cada capa está en un servicio distinto de AWS y solo se comunica con la capa vecina:

```
┌──────────────────────── CAPA DE PRESENTACIÓN ────────────────────────┐
│  05-capa-presentacion/web   →  S3 + CloudFront (página Rutigym)       │
│  Inicio de sesión con Amazon Cognito (4 roles)                        │
└───────────────────────────────┬───────────────────────────────────────┘
                                │ HTTPS + token JWT (API Gateway)
┌───────────────────────── CAPA DE LÓGICA ──────────────────────────────┐
│  03-motor-lambda/motor  →  AWS Lambda "se-motor-inferencia"           │
│    servicio.py   entrada de la API: identidad, permisos, rutas        │
│    negocio.py    MOTOR DE INFERENCIA (probabilístico y granular)      │
│    interprete.py interpretación local de respuestas escritas          │
└───────────────────────────────┬───────────────────────────────────────┘
                                │ SQL con token IAM y SET LOCAL ROLE
┌───────────────────────── CAPA DE DATOS ───────────────────────────────┐
│  03-motor-lambda/motor/datos.py  (acceso a datos, sin lógica)         │
│  servicios_ia.py · identidad.py → fuentes externas: Lex, Bedrock Nova,│
│    Automated Reasoning y Cognito                                      │
│  02-capa-datos/sql  →  Aurora PostgreSQL Serverless (esquema "se")    │
│    Base de conocimiento: preguntas, hechos, respuesta_pregunta,       │
│    hipotesis, hechos_hipotesis (gránulos con peso)                    │
│    Seguridad por fila, procedimientos, disparadores y auditoría       │
└───────────────────────────────────────────────────────────────────────┘
```

Dentro de la Lambda se repite la misma separación: `servicio.py` no calcula ni consulta la base, `negocio.py` no conoce SQL ni HTTP, y `datos.py` no toma decisiones. Por eso los servicios de IA y la base se pueden reemplazar en las pruebas por dobles de prueba.

El código está documentado por bloques: cada archivo empieza con una línea que dice qué hace y en qué capa está, y cada grupo de funciones tiene un encabezado corto.

## Carpetas

| Carpeta | Capa o función | Despliega |
|---|---|---|
| `01-infraestructura-aurora/` | Infraestructura base | Clúster Aurora PostgreSQL Serverless (`se-rutinas-db`) y pruebas de viabilidad de Lex y Bedrock |
| `02-capa-datos/` | **Datos** | Roles, esquema, permisos por rol, procedimientos, carga del conocimiento (7 preguntas, 19 hechos, 32 hipótesis, 160 gránulos) y migraciones 05 y 06. Verificación de las 48 reglas y las 720 combinaciones, y pruebas de seguridad |
| `03-motor-lambda/` | **Lógica** (y acceso a datos) | Lambda, API Gateway HTTP API con autorizador JWT y Cognito con 4 grupos (`template.yaml`, pila `se-rutinas-motor`). Cuentas de demostración y pruebas |
| `04-servicios-ia/` | Servicios de IA | Bot de Amazon Lex (`se-rutinas-nlu`), política de Automated Reasoning (`se-rutinas-reglas-experto`) y guardrail (`se-rutinas-verificador`) |
| `05-capa-presentacion/` | **Presentación** | Página Rutigym en S3 + CloudFront (`template-web.yaml`, pila `se-rutinas-web`) |
| `06-operacion/` | Operación | Reinicio para la demostración, limpieza de sobrantes en la nube y estado de la base |
| `docs/` | Documentación | Estado del proyecto, árbol de decisión (Mermaid y PNG) |

### Archivos del motor (`03-motor-lambda/motor`)

| Archivo | Capa | Responsabilidad |
|---|---|---|
| `servicio.py` | Servicio (entrada) | Lee el evento de API Gateway, identifica al usuario, aplica la matriz de permisos y orquesta cada caso de uso. Maneja la secuencia de interpretación de texto. |
| `identidad.py` | Datos (fuente externa) | Cuentas en Cognito (crear, cambiar grupo, activar). |
| `negocio.py` | **Negocio** | Motor de inferencia: puntaje por gránulos, elección de la siguiente pregunta, parada, top 5, traza y reglas de consulta (una abierta, descartar). |
| `interprete.py` | Negocio | Entiende respuestas escritas con los sinónimos de la base, incluidas las negaciones. |
| `servicios_ia.py`, `vocabulario_ar.py` | Datos (fuentes externas) | Amazon Lex, Bedrock Nova (redacción y clasificación) y Automated Reasoning. El motor los consulta como consulta la base. |
| `datos.py` | **Datos** | Conexión a Aurora con token IAM, transacción con el rol del usuario y consultas granulares. |

## Orden de despliegue (AWS CloudShell, us-east-1)

```bash
unzip rutigym-sistema-experto-aws.zip && cd rutigym-sistema-experto-aws
bash preparar_cloudshell.sh          # copia a ~/fase0 … ~/fase5 y ~/limpieza

cd ~/fase0 && bash ejecutar_fase0.sh            # 1. Aurora y pruebas de viabilidad
cd ~/fase1 && bash desplegar_fase1.sh           # 2. base de conocimiento + verificación
cd ~/fase3 && bash desplegar_ia.sh              # 3. Lex y política de Automated Reasoning
cd ~/fase4 && bash desplegar_fase4.sh           # 4. Cognito, API Gateway y Lambda (motor)
cd ~/fase5 && bash desplegar_fase5.sh           # 5. página en S3 + CloudFront
bash ~/limpieza/reiniciar_demo.sh --aplicar     # deja todo en cero para la demostración
```

En CloudShell las carpetas se llamaron `fase0` a `fase5`, como en la tabla siguiente. Por eso `preparar_cloudshell.sh` las copia con esos nombres.

| Carpeta aquí | Carpeta en CloudShell |
|---|---|
| `01-infraestructura-aurora` | `~/fase0` |
| `02-capa-datos` | `~/fase1` |
| `04-servicios-ia` | `~/fase3` |
| `03-motor-lambda` | `~/fase4` |
| `05-capa-presentacion` | `~/fase5` |
| `06-operacion` | `~/limpieza` |

La fase 2 (el primer motor sin API pública) quedó reemplazada por la fase 4 y no se incluye.

## Qué no viene en la entrega (a propósito)

- **`credenciales_demo.txt`:** `cuentas/crear_cuentas.py` genera contraseñas al azar para las 7 cuentas de demostración y solo quedan en CloudShell.
- **`config.js` de la página:** lo genera `desplegar_fase5.sh` con la URL de la API y el cliente de Cognito.
- **Certificados `global-bundle.pem` y `ca-confianza.pem`, y dependencias `_deps/` y `build/`:** los scripts los descargan o los generan.

## Pruebas

| Prueba | Archivo | Resultado |
|---|---|---|
| Caminos del árbol | `02-capa-datos/verificacion/verificar_caminos.py` | 48 reglas, 720 combinaciones, 32/32 hipótesis alcanzables |
| Seguridad por rol en la base | `02-capa-datos/verificacion/pruebas_seguridad.py` | 45/45 |
| Motor contra PostgreSQL local | `03-motor-lambda/pruebas/probar_local.py` | 68/68 |
| API (eventos de API Gateway) | `03-motor-lambda/pruebas/probar_local_api.py` | 45/45 |
| Servicios de IA con dobles de prueba | `probar_local_ia.py` | 16/16 |
| Negaciones escritas | `probar_local_negacion.py` | 12/12 |
| Servicios reales (Lex, Nova y Cognito) | `probar_api.py`, `probar_ajuste6.py`, `probar_ajuste7.py`, `probar_ajuste8.py` | Se corren en CloudShell |
