# Rutigym · Sistema experto de rutinas de entrenamiento en AWS
## Estado del proyecto y cambios de la sesión del 10 de noviembre de 2026

Este documento resume cómo está construido el sistema experto después de los ajustes 1 a 8: el árbol de decisión, la base de conocimiento, las reglas, la arquitectura en AWS y las reglas de funcionamiento por rol. Sirve como referencia para el informe, la exposición y futuras correcciones.

**Estado al cierre de la sesión:**
- El ajuste 9 (modelo sin ciclos y opiniones de varios expertos) está aplicado en AWS: `probar_ajuste9.py` dio 8/8 y la base quedó reiniciada para la demostración.
- **Verificación:** 720 combinaciones sin incoherencias, 32 de 32 hipótesis alcanzables y seguridad en 55 de 55 en la nube.
- **Pruebas con Lex y Nova reales:** el ajuste 7 pasó 17 de 17 y el ajuste 8 pasó 16 de 17. La que faltó dependía de los sinónimos nuevos, que se cargan al reiniciar la base.
- **Datos:** 0 consultas, 7 perfiles de demostración, 7 preguntas, 19 hechos, 32 hipótesis y 160 gránulos.

---

## 1. Arquitectura

| Capa | Servicio | Qué hace en el sistema experto |
|---|---|---|
| Interfaz | Amazon S3 + CloudFront (OAC y CSP) | Publica la página "Rutigym", una sola página dinámica en JavaScript sin frameworks. |
| Identidad | Amazon Cognito (4 grupos) | Inicio de sesión y roles: usuario_final, experto, ingeniero_conocimiento y administrador. |
| API | API Gateway HTTP API con autorizador JWT | Valida el token y enruta `/{proxy+}` a la Lambda. `/despertar` es pública. Límite de 10 peticiones por segundo con ráfaga de 20. |
| Motor | AWS Lambda Python 3.12 (`se-motor-inferencia`, 512 MB, 29 s) | Tiene tres capas: servicio (permisos y rutas), negocio (inferencia) y datos (SQL). |
| Base de conocimiento | Aurora PostgreSQL Serverless v2 (`se-rutinas-db`) | Usa autenticación IAM, seguridad por fila (RLS) y `SET LOCAL ROLE` por petición. Se pausa sola para no generar costo. |
| Lenguaje natural | Amazon Lex V2 (`se-rutinas-nlu`, alias `produccion`, versión 2) | Interpreta respuestas escritas. |
| IA generativa | Amazon Bedrock Nova Micro (`amazon.nova-micro-v1:0`) | Redacta los mensajes y la explicación final, y clasifica frases escritas. Solo puede elegir entre las opciones existentes. |
| Verificación formal | Bedrock Automated Reasoning: política `se-rutinas-reglas-experto` y guardrail `se-rutinas-verificador` (versión 2) | Comprueba con lógica formal que la rutina concluida cumple las reglas del experto. Es el servicio de IA enfocado en sistemas expertos. |
| Infraestructura como código | SAM / CloudFormation (`se-rutinas-motor`, `se-rutinas-web`) | Despliegue reproducible. |

**Flujo de una petición:**
1. El navegador envía la petición con el token de Cognito.
2. API Gateway valida el JWT.
3. La Lambda identifica al usuario y comprueba que su rol permita la acción.
4. La Lambda abre una transacción con el rol de base de datos que le corresponde: `rol_usuario`, `rol_experto`, `rol_ingeniero_conocimiento` o `rol_administrador`.
5. La seguridad por fila de PostgreSQL decide qué filas puede ver y escribir.

Así, aunque el código tuviera un error, la base no deja que un usuario vea las consultas de otro.

---

## 2. Base de conocimiento (modelo relacional)

**Tablas de conocimiento.** Las mantiene el ingeniero, solo mediante procedimientos almacenados que validan la coherencia.
- `preguntas`: código, atributo, texto, ayuda, orden y `peso_base`.
- `hechos`: código HCxx, pregunta y valor.
- `respuesta_pregunta`: el texto de la opción y sus **sinónimos**, que se usan para entender respuestas escritas.
- `hipotesis`: código Hxx, nivel, equipo, objetivo, fase, días por semana, actividad, descripción de la rutina y probabilidad previa.
- `hechos_hipotesis`: los **gránulos**. Cada uno indica qué hecho respalda qué hipótesis y con qué peso.

**Tablas de operación (sistema transaccional):**
- `usuario`: llave `id_usuario`, alias, correo y rol.
- `consulta` y `consulta_hecho`: la memoria de trabajo. La pregunta de cada respuesta se obtiene por el hecho.
- `diagnostico_hipotesis`: el top 5 guardado.
- `traza_inferencia`: la explicación paso a paso, la verificación formal y las **opiniones de los expertos** (tipo `validacion_experto`, una por experto y consulta).
- `auditoria`: registro técnico de cambios que llenan los disparadores. Queda **fuera del modelo conceptual**.

**Modelo sin relaciones redundantes (ajuste 9):**
- `respuesta_pregunta` y `consulta_hecho` ya no guardan `id_pregunta`, porque se obtiene por `hechos.id_pregunta`.
- La tabla `validacion_experto` desapareció: con ella se formaba el ciclo `usuario`–`consulta`–`validacion_experto`.
- No hay ciclos de tres tablas. El único ciclo del grafo es el de la relación N–M entre hechos e hipótesis, que pasa por las respuestas de la consulta y por su top 5; no hay redundancia, porque uno guarda lo que la persona respondió y el otro lo que el sistema concluyó.
- El modelo para MySQL Workbench es `MR_rutigym_workbench.sql`, equivalente al de Aurora.

**Tipos (enum):**
- `t_nivel`: Principiante, Intermedio o Avanzado.
- `t_equipo`: Básico o en casa, o Gimnasio completo.
- `t_objetivo`: Fuerza, Hipertrofia, Resistencia, Pérdida de grasa o Rendimiento deportivo.
- `t_fase`: Volumen o Intensidad.
- `t_dias_semana`: 2 días, o 3 o más días.
- `t_actividad`: Sedentario o Algo activo.
- `t_estado_consulta`: en_curso, terminada o abandonada (en pantalla, "Descartada").

### 2.1 Preguntas y peso base

| Código | Atributo | Pregunta | Peso base |
|---|---|---|---|
| P1 | tecnica_dominada | ¿Dominas la técnica de los ejercicios básicos (sentadilla, flexión, remo, peso muerto)? | 0,95 |
| P2 | tiempo_entrenando | ¿Cuánto tiempo llevas entrenando de forma constante? | 0,90 |
| P3 | equipo_disponible | ¿Con qué equipo cuentas para entrenar? | 0,80 |
| P4 | objetivo_principal | ¿Cuál es tu objetivo principal? | 0,85 |
| P5 | fase_priorizada | ¿Qué quieres priorizar en esta etapa de tu entrenamiento? | 0,70 |
| P6 | dias_semana | ¿Cuántos días a la semana puedes dedicarle al entrenamiento? | 0,75 |
| P7 | actividad_actual | ¿Cómo describirías tu actividad física actual? | 0,70 |

### 2.2 Hechos (19), opciones y sinónimos

| Hecho | Pregunta | Opción | Sinónimos principales |
|---|---|---|---|
| HC01 | P1 | Sí, los domino | sí, si, claro, los domino, domino la técnica, tengo buena técnica |
| HC02 | P1 | No | no, no los domino, **no domino la técnica, no la domino, no tengo buena técnica** (nuevos), no sé hacerlos, me cuesta la técnica, nunca he entrenado |
| HC03 | P1 | No estoy seguro | no sé, creo que sí, creo que no, más o menos, tal vez |
| HC04 | P2 | Menos de 6 meses | acabo de empezar, un mes, dos meses, poco tiempo |
| HC05 | P2 | Entre 6 meses y 2 años | un año, como un año, año y medio, dos años |
| HC06 | P2 | Más de 2 años | tres años, varios años, hace años |
| HC07 | P3 | Básico o en casa | en casa, bandas, mancuernas, peso corporal, sin equipo |
| HC08 | P3 | Gimnasio completo | gimnasio, gym, máquinas, barra olímpica |
| HC09 | P4 | Ganar fuerza | fuerza, ser más fuerte, levantar más peso |
| HC10 | P4 | Ganar masa muscular | hipertrofia, ganar músculo, masa muscular |
| HC11 | P4 | Mejorar la resistencia | resistencia, cardio, aguante |
| HC12 | P4 | Perder grasa | adelgazar, bajar de peso, definir |
| HC13 | P4 | Rendir mejor en mi deporte | deporte, competir, fútbol |
| HC14 | P5 | Volumen | muchas series, más repeticiones |
| HC15 | P5 | Intensidad | cargas altas, pesado |
| HC16 | P6 | 2 días | dos días, fines de semana |
| HC17 | P6 | 3 o más días | tres días, todos los días, varios días |
| HC18 | P7 | Sedentario | trabajo sentado, no hago ejercicio |
| HC19 | P7 | Algo activo | camino a diario, hago deporte a veces |

### 2.3 Hipótesis (32 rutinas)

- **Principiante.** Depende del equipo, los días y la actividad; no se diferencia por objetivo.
  - En casa: H01 (3+ días, sedentario), H27 (2 días, sedentario), H28 (2 días, algo activo), H29 (3+ días, algo activo).
  - En gimnasio: H02 (3+ días, sedentario), H30 (2 días, sedentario), H31 (2 días, algo activo), H32 (3+ días, algo activo).
- **Intermedio.** Depende del equipo y del objetivo.
  - En casa: H03 a H07 (Fuerza, Hipertrofia, Resistencia, Pérdida de grasa, Rendimiento deportivo).
  - En gimnasio: H08 a H12, con los mismos objetivos.
- **Avanzado.** Depende del equipo y del objetivo. En fuerza e hipertrofia, además, de la fase.
  - En casa: H13 y H14 (Fuerza en volumen e intensidad), H15 y H16 (Hipertrofia en volumen e intensidad), H17 (Resistencia), H18 (Pérdida de grasa) y H19 (Rendimiento deportivo).
  - En gimnasio: H20 a H26, en el mismo orden.

### 2.4 Gránulos (160)

Cada gránulo une un hecho con una hipótesis que respalda. Su peso parte del peso base de la pregunta, y el ingeniero lo puede ajustar gránulo por gránulo con `sp_asociar_hecho_hipotesis`, que rechaza pesos fuera de 0 a 1 y asociaciones incoherentes.

El validador `fn_validar_base()` comprueba seis cosas:
- que cada hecho tenga su opción;
- que cada hipótesis tenga gránulos y un hecho de equipo;
- que cada pregunta tenga al menos 2 opciones;
- que ningún sinónimo apunte a dos opciones de la misma pregunta;
- que no haya hipótesis indistinguibles;
- que los gránulos sean coherentes con su hipótesis.

---

## 3. Árbol de decisión y reglas

El nivel sale de la técnica y del tiempo entrenando:
- Técnica **No** o **No estoy seguro**: Principiante.
- Técnica **Sí** con menos de 6 meses: Principiante.
- Técnica **Sí** con 6 meses a 2 años: Intermedio.
- Técnica **Sí** con más de 2 años: Avanzado.

Después, cada nivel se ramifica:
- **Principiante:** equipo, luego días por semana, luego actividad.
- **Intermedio:** equipo, luego objetivo.
- **Avanzado:** equipo, luego objetivo, y, si el objetivo es Fuerza o Hipertrofia, la fase.

El árbol tiene **48 reglas (R01 a R48)**, que son los 48 caminos de la raíz a una hoja:

| Reglas | Camino | Hipótesis |
|---|---|---|
| R01–R06 | Principiante (técnica No, No estoy seguro, o Sí con menos de 6 meses) · 3+ días · sedentario | H01 en casa, H02 en gimnasio |
| R07–R11 | Intermedio · en casa · objetivo | H03–H07 |
| R12–R16 | Intermedio · gimnasio · objetivo | H08–H12 |
| R17–R23 | Avanzado · en casa · objetivo (y fase en fuerza e hipertrofia) | H13–H19 |
| R24–R30 | Avanzado · gimnasio · objetivo (y fase en fuerza e hipertrofia) | H20–H26 |
| R31–R36 | Técnica No · equipo · días · actividad (excepto 3+ días y sedentario) | H27–H32 |
| R37–R42 | Técnica No estoy seguro · mismas ramas | H27–H32 |
| R43–R48 | Técnica Sí con menos de 6 meses · mismas ramas | H27–H32 |

Las mismas 48 reglas están traducidas a la política de **Automated Reasoning**, con 8 variables, 8 tipos y 48 reglas en SMT-LIB. El script `verificar_caminos.py` recorre las 48 rutas y las 720 combinaciones posibles de respuestas. Comprueba que en todas haya una sola ganadora, que coincida con el árbol y que las 32 hipótesis sean alcanzables.

> En esta sesión no se modificaron las 48 reglas ni las hipótesis. Solo se agregaron tres sinónimos al hecho HC02, para que "no domino la técnica" se reconozca como "No".

---

## 4. Motor de inferencia (probabilístico y granular)

- **Puntaje.** Cada hipótesis empieza con su probabilidad previa. Cuando el usuario responde una pregunta, las hipótesis que tienen gránulos en ella reciben un factor:
  - **1** si la respuesta las respalda;
  - **1 − peso** si no las respalda.

  Las hipótesis sin gránulos en esa pregunta no cambian. El top 5 se normaliza para mostrarlo en porcentajes.
- **Qué preguntar.** Solo se hacen preguntas cuya respuesta puede cambiar la hipótesis líder. Por eso una consulta tiene entre 2 y 5 preguntas.
- **Cuándo termina.** La consulta se cierra cuando ninguna pregunta pendiente puede cambiar la líder. Entonces se guardan el top 5, la conclusión en la traza y la explicación que redacta Nova.
- **Consultas granulares.** El motor solo lee de la base los gránulos de la pregunta en curso.
- **Traza.** Cada paso registra la pregunta elegida y las evaluadas, la respuesta, quién la interpretó, las hipótesis respaldadas y debilitadas, y el top 5 antes y después.

---

## 5. Interpretación de respuestas escritas

Una frase escrita pasa por tres intérpretes en orden. El primero que entienda la frase decide:

1. **Sinónimos de la base** (local y sin costo). Tolera mayúsculas, tildes, signos y errores pequeños de escritura.
2. **Amazon Lex.**
3. **Bedrock Nova**, como clasificador limitado a las opciones de la pregunta:
   - con confianza de 0,8 o más acepta la opción;
   - entre 0,5 y 0,8 pregunta "¿Te refieres a…?";
   - con 0,75 o más propone datos que la persona ya adelantó para preguntas futuras.

**Negaciones (ajuste 8).** Antes, "No domino la técnica" se registraba como "Sí": los sinónimos descartaban la frase negada y Lex veía la palabra "domino". Se corrigió en varios niveles:
- El intérprete local detecta una negación hasta tres palabras antes de la frase, dentro de la misma oración. "No voy al gimnasio" niega "gimnasio", pero "No, voy al gimnasio" no lo niega.
- Negar la opción afirmativa equivale a responder "No".
- Un "no" o un "sí" al inicio de la frase cuenta como respuesta.
- Ningún servicio puede registrar una opción negada. Si el texto tiene una negación y Lex o Nova proponen "Sí", se descarta o se pide confirmar.
- Se probaron 29 formas de escribir; todas se clasifican bien.

**Aprendizaje.** En "Frases por revisar", el ingeniero ve las frases que se entendieron con ayuda de Lex o de Nova. Elige la opción correcta y la agrega como sinónimo. Desde ese momento se reconoce al instante sin servicios externos.

> Lex no se resincronizó con los sinónimos nuevos. No hace falta, porque el control de negaciones descarta sus errores.

---

## 6. Roles y reglas de funcionamiento

| Rol | Puede | No puede |
|---|---|---|
| Usuario final | Hacer consultas, una abierta a la vez; continuarlas o descartarlas; ver su historial y por qué se eligió su rutina | Ver consultas de otros; métricas; base de conocimiento |
| Experto | Revisar consultas; **verificar formalmente** (una vez por consulta); dar su opinión (de acuerdo o en desacuerdo); ver métricas; **consultar la base en solo lectura**: preguntas, opciones, hipótesis, gránulos y pesos | Modificar la base; ejecutar el validador; ver las frases por revisar |
| Ingeniero del conocimiento | Modificar la base mediante procedimientos; ejecutar el validador; revisar frases y agregarlas como sinónimos; verificar formalmente | Dar la opinión del experto; gestionar usuarios |
| Administrador | Gestionar cuentas (crear, cambiar rol, activar o desactivar); ver la auditoría, las consultas y las métricas en solo lectura | Modificar la base; verificar; cambiar su propio rol |

**Reglas agregadas en esta sesión.** Todas se cumplen en la página, en el motor y en la base de datos:
- **Varios expertos opinan sobre la misma consulta.** Cada uno tiene una opinión que puede corregir pero no duplicar; lo garantiza el índice `ux_traza_validacion`. El usuario final no la ve, por la seguridad por fila. Un experto no puede cambiar la opinión de otro, y solo se opina sobre consultas terminadas (disparador `tr_opinion_sobre_terminada`).
- **Una respuesta por pregunta en cada consulta:** disparador `tr_una_respuesta_por_pregunta`, porque la pregunta sale del hecho.
- **Una sola consulta abierta por perfil.** Lo garantiza un índice único parcial (`ux_consulta_abierta`), incluso si llegan dos peticiones a la vez.
  - Si la persona pide otra, el motor responde 409 con la consulta pendiente y la página ofrece "Continuar" o "Descartarla y empezar otra".
- **Descartar una consulta.** `POST /consultas/{id}/descartar` cambia el estado a abandonada ("Descartada").
  - Se conservan las respuestas, pero no se genera rutina, no se verifica y no se valida.
  - Una consulta con 7 días sin actividad se descarta sola.
  - El disparador `tr_estado_consulta` impide reabrir una consulta cerrada.
- **Numeración por perfil.** Cada perfil ve sus consultas como 1, 2, 3…, sin saltos y sin importar las de otros. El experto ve "Consulta 2 de laura". El `id_consulta` interno no se muestra.
- **Verificación formal definitiva.** Un resultado lógico (VALID, INVALID, SATISFIABLE o IMPOSSIBLE) no se repite, porque las respuestas y la rutina ya no cambian. Lo garantiza el disparador `tr_verificacion_definitiva`.
  - Solo se puede reintentar si falló por causas técnicas: error, traducción ambigua o sin traducción.
  - Para probar un cambio en la base se verifica una consulta nueva.
- **Validador solo para el ingeniero.** Se revocó `EXECUTE` sobre `fn_validar_base()` a `rol_experto`.
- **Alias legibles.** El alias sale del nombre de registro: primer nombre más la inicial del apellido ("Juan Pérez" queda como `juan.p`; si se repite, `juan.p2`).
  - El alias no es la llave; la llave es `id_usuario`.
  - Muestra al equipo un nombre reconocible sin exponer el nombre completo ni el correo.
  - Los alias al azar anteriores ("usuario-c47814") se corrigieron con la migración.
- **Métricas:**
  - consultas terminadas, en curso y descartadas;
  - pendientes por verificar;
  - verificadas (válidas o inválidas);
  - concordancia con el experto, es decir, opiniones de acuerdo sobre el total de opiniones;
  - rutinas más recomendadas.

---

## 7. Interfaz (Rutigym)

- **Estilo.** Usa tres colores: blanco `#fff`, caucho `#262626` y rojo `#c8102e`. La fuente es Archivo, incluida en el propio sitio. La barra superior es fija, solo el contenido se desplaza y el diseño se adapta al celular.
- **Consulta.** Muestra una pregunta a la vez y un marcador con el top 5 que se anima con cada respuesta. Se puede responder con botones o escribiendo. También muestra las sugerencias, la pregunta de confirmación y el recorrido.
- **Botón principal arriba a la derecha:** "Nueva consulta" (usuario), "Revisar pendientes" (experto), "Validar la base" (ingeniero) y "Crear cuenta" (administrador).
- **Verificación visible para todos los roles.** El resultado guardado aparece con fecha y con la traducción a lógica formal.

---

## 8. Operación y pruebas

- **Reinicio para la demostración:** `bash ~/limpieza/reiniciar_demo.sh --aplicar`, con confirmación REINICIAR.
  - Borra consultas, trazas, opiniones, auditoría y las cuentas que no son de demostración.
  - Recarga la base desde `04_carga_conocimiento.sql`.
  - Limpia los sobrantes en la nube.
  - Corre la verificación completa: 48 caminos, 720 combinaciones y 55 pruebas de seguridad.
- **Migraciones de la base:**
  - `05_una_consulta_abierta.sql`: índice de consulta abierta y disparador de estado.
  - `06_roles_y_verificacion.sql`: validador solo para el ingeniero, verificación definitiva y alias.
  - `07_modelo_sin_ciclos.sql`: quita `id_pregunta` redundante y pasa las opiniones a la traza. Se ejecuta sin `-1` y después se vuelve a ejecutar `03_procedimientos.sql`.
  - Todas se pueden ejecutar varias veces sin efecto adicional.
- **Pruebas locales** (PostgreSQL 16 con dobles de Lex, Nova y Automated Reasoning):

| Prueba | Resultado |
|---|---|
| Motor | 68/68 |
| API | 48/48 |
| Servicios de IA | 16/16 |
| Negaciones | 12/12 |
| Seguridad | 55/55 |
| Navegador (cuatro roles, consulta abierta, ajuste 8) | 39/39, 22/22 y 13/13 |
| Desborde en celular | Sin desborde |

- **Pruebas en AWS:** `probar_ajuste7.py` (17/17) y `probar_ajuste8.py` (16/17; la que faltaba se resuelve con el reinicio).
- **Costo.** Todo opera con los créditos gratuitos. Aurora se pausa sin uso y la API tiene límite de peticiones.
- Las credenciales de las 7 cuentas de demostración están solo en `credenciales_demo.txt`, en CloudShell. Nunca se muestran en informes ni en el video.

---

## 9. Cambios de esta sesión (resumen)

| Ajuste | Cambio |
|---|---|
| Limpieza | Reinicio de datos de prueba y limpieza de sobrantes en la nube. Se corrigió el conteo de perfiles fuera de los 7 de demostración. |
| 5 | Rediseño "Rutigym": tres colores, Archivo, barra mínima, barra fija, versión móvil y textos por rol. La verificación se ve en todos los roles. |
| 6 | Intérprete de tres pasos (sinónimos, Lex y Nova) con confirmación, datos adelantados, frases por revisar, métricas completas y numeración visible sin saltos. |
| Parche | Pruebas de seguridad con alias propios: 39 de 39. |
| 7 | Una consulta abierta por perfil, descartar, descarte por inactividad y numeración propia por perfil. |
| 8 | Negaciones escritas, experto con base en solo lectura, frases asignables a la opción correcta, verificación definitiva y alias legibles. |
| 9 | Modelo sin relaciones redundantes ni ciclos de tres tablas: sin `id_pregunta` repetido y opiniones de varios expertos en la traza. Modelo de Workbench alineado. |

---

## 10. Documentos del proyecto y su vigencia

| Documento | Estado |
|---|---|
| `Rutigym_estado_del_proyecto.md` (este) | Vigente. Es la referencia principal del sistema actual. |
| `Arbol_decision_actual.md` | Vigente. Árbol con 32 hojas y 48 reglas, en Mermaid. |
| `SQL_rutinas_entrenamiento_PostgreSQL.sql` | Vigente (actualizado). Script completo 00–07 del modelo de 5 tablas. |
| `MR_rutigym_workbench.sql` | Vigente. Modelo relacional para MySQL Workbench (diagrama), equivalente al de Aurora y sin la tabla técnica de auditoría. |
| `Consultas_granulos.sql` | Vigente (actualizado). Diez consultas sobre el modelo actual, entre ellas la inferencia del top 5 en SQL, que da los mismos porcentajes que el motor. |
| `arbol_decision.png` | **Histórico**: es el árbol de octubre, con 26 hojas y sin P6 ni P7. Lo reemplaza `arbol_decision_actual.png`. |
| `Proyecto_Sistema_Experto_Corregido.pdf` | **Histórico** en las secciones de árbol, reglas y base de datos: describe 26 hipótesis, 30 reglas, las tablas `regla` y `regla_condicion` y el encadenamiento hacia adelante. El problema, los requerimientos, el experto, los niveles, los roles y los casos de uso siguen sirviendo. |
| PDF de clase (1 a 8) y artículos | Material de referencia teórica; no cambia. |
