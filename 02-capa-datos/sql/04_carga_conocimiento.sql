-- =====================================================================
-- 04. Carga del conocimiento del experto con los mismos procedimientos del ingeniero.
-- =====================================================================
SET search_path = se;

-- ---------------------------------------------------------------------
-- 4.1 Preguntas (peso_base = pesos definidos con el experto)
-- ---------------------------------------------------------------------
INSERT INTO preguntas (codigo, atributo, texto, ayuda, orden, peso_base) VALUES
 ('P1', 'tecnica_dominada',
  '¿Dominas la técnica de los ejercicios básicos (sentadilla, flexión, remo, peso muerto)?',
  'Por ejemplo: bajar en la sentadilla con la espalda recta o hacer flexiones completas sin balancear el cuerpo.',
  1, 0.950),
 ('P2', 'tiempo_entrenando',
  '¿Cuánto tiempo llevas entrenando de forma constante?',
  'Cuenta solo el tiempo en que has entrenado al menos 2 o 3 veces por semana sin pausas largas.',
  2, 0.900),
 ('P3', 'equipo_disponible',
  '¿Con qué equipo cuentas para entrenar?',
  'Básico: peso corporal, bandas o mancuernas. Gimnasio completo: máquinas, barras y discos.',
  3, 0.800),
 ('P4', 'objetivo_principal',
  '¿Cuál es tu objetivo principal?',
  NULL,
  4, 0.850),
 ('P5', 'fase_priorizada',
  '¿Qué quieres priorizar en esta etapa de tu entrenamiento?',
  'Volumen: más series y repeticiones con carga moderada. Intensidad: menos repeticiones con cargas más altas.',
  5, 0.700),
 ('P6', 'dias_semana',
  '¿Cuántos días a la semana puedes dedicarle al entrenamiento?',
  'Piensa en los días que realmente puedes mantener durante varias semanas seguidas.',
  6, 0.750),
 ('P7', 'actividad_actual',
  '¿Cómo describirías tu actividad física actual?',
  'Algo activo: caminas a diario, montas bicicleta o practicas algún deporte de vez en cuando.',
  7, 0.700);

-- ---------------------------------------------------------------------
-- 4.2 Hechos y opciones de respuesta (con sinónimos para Amazon Lex)
-- ---------------------------------------------------------------------
CALL sp_registrar_hecho('HC01', 'P1', 'Sí', 'Sí, los domino',
     ARRAY['sí','si','claro','los domino','sí los domino','domino la técnica','tengo buena técnica'], 1,
     'tecnica_dominada = Sí');
CALL sp_registrar_hecho('HC02', 'P1', 'No', 'No',
     ARRAY['no','no los domino','no domino la técnica','no la domino','no tengo buena técnica','no sé hacerlos','me cuesta la técnica','nunca he entrenado'], 2,
     'tecnica_dominada = No');
CALL sp_registrar_hecho('HC03', 'P1', 'No estoy seguro', 'No estoy seguro',
     ARRAY['no estoy seguro','no sé','tal vez','más o menos','creo que sí','creo que no'], 3,
     'tecnica_dominada = No estoy seguro');
CALL sp_registrar_hecho('HC04', 'P2', 'Menos de 6 meses', 'Menos de 6 meses',
     ARRAY['menos de seis meses','acabo de empezar','unos meses','pocos meses','poco tiempo','un mes','dos meses','tres meses'], 1,
     'tiempo_entrenando = Menos de 6 meses');
CALL sp_registrar_hecho('HC05', 'P2', '6 meses a 2 años', 'Entre 6 meses y 2 años',
     ARRAY['entre seis meses y dos años','un año','como un año','año y medio','dos años','ocho meses','diez meses'], 2,
     'tiempo_entrenando = 6 meses a 2 años');
CALL sp_registrar_hecho('HC06', 'P2', 'Más de 2 años', 'Más de 2 años',
     ARRAY['más de dos años','tres años','cuatro años','cinco años','muchos años','varios años','hace años'], 3,
     'tiempo_entrenando = Más de 2 años');
CALL sp_registrar_hecho('HC07', 'P3', 'Básico o en casa', 'Básico o en casa',
     ARRAY['en casa','casa','mancuernas','bandas','peso corporal','sin equipo','equipo básico','en el parque'], 1,
     'equipo_disponible = Básico o en casa');
CALL sp_registrar_hecho('HC08', 'P3', 'Gimnasio completo', 'Gimnasio completo',
     ARRAY['gimnasio','gym','gimnasio completo','máquinas','barra olímpica'], 2,
     'equipo_disponible = Gimnasio completo');
CALL sp_registrar_hecho('HC09', 'P4', 'Fuerza', 'Ganar fuerza',
     ARRAY['fuerza','ser más fuerte','levantar más peso'], 1,
     'objetivo_principal = Fuerza');
CALL sp_registrar_hecho('HC10', 'P4', 'Hipertrofia', 'Ganar masa muscular',
     ARRAY['hipertrofia','ganar músculo','masa muscular','aumentar músculo','crecer'], 2,
     'objetivo_principal = Hipertrofia');
CALL sp_registrar_hecho('HC11', 'P4', 'Resistencia', 'Mejorar la resistencia',
     ARRAY['resistencia','aguante','cardio','correr más'], 3,
     'objetivo_principal = Resistencia');
CALL sp_registrar_hecho('HC12', 'P4', 'Pérdida de grasa', 'Perder grasa',
     ARRAY['perder grasa','bajar de peso','adelgazar','definir','quemar grasa'], 4,
     'objetivo_principal = Pérdida de grasa');
CALL sp_registrar_hecho('HC13', 'P4', 'Rendimiento deportivo', 'Rendir mejor en mi deporte',
     ARRAY['rendimiento deportivo','mejorar en mi deporte','deporte','fútbol','atletismo','competir'], 5,
     'objetivo_principal = Rendimiento deportivo');
CALL sp_registrar_hecho('HC14', 'P5', 'Volumen', 'Volumen',
     ARRAY['volumen','más repeticiones','acumulación','muchas series'], 1,
     'fase_priorizada = Volumen');
CALL sp_registrar_hecho('HC15', 'P5', 'Intensidad', 'Intensidad',
     ARRAY['intensidad','cargas máximas','cargas altas','pesado','intensificación'], 2,
     'fase_priorizada = Intensidad');
CALL sp_registrar_hecho('HC16', 'P6', '2 días', '2 días',
     ARRAY['dos días','2 días','dos veces','dos veces por semana','pocos días','solo el fin de semana','fines de semana'], 1,
     'dias_semana = 2 días');
CALL sp_registrar_hecho('HC17', 'P6', '3 o más días', '3 o más días',
     ARRAY['tres días','3 días','tres veces','cuatro días','cinco días','casi todos los días','todos los días','día por medio','varios días'], 2,
     'dias_semana = 3 o más días');
CALL sp_registrar_hecho('HC18', 'P7', 'Sedentario', 'Sedentario: paso la mayor parte del día sentado',
     ARRAY['sedentario','no hago ejercicio','paso sentado','trabajo sentado','casi no me muevo','poca actividad'], 1,
     'actividad_actual = Sedentario');
CALL sp_registrar_hecho('HC19', 'P7', 'Algo activo', 'Algo activo: camino o hago deporte de vez en cuando',
     ARRAY['algo activo','activo','camino bastante','camino a diario','hago deporte a veces','monto bicicleta','juego fútbol a veces'], 2,
     'actividad_actual = Algo activo');

-- ---------------------------------------------------------------------
-- 4.3 Hipótesis (nodos terminales del árbol de decisión)
-- ---------------------------------------------------------------------
CALL sp_registrar_hipotesis('H01', 'Principiante', 'Básico o en casa', NULL, NULL,
    '3 o más días', 'Sedentario',
    '3 días/semana. Circuito de cuerpo completo con peso corporal, bandas y mancuernas livianas: sentadilla, flexión de brazos, remo con banda, puente de glúteo y plancha abdominal. 3x10-15, carga mínima, énfasis total en la técnica antes de progresar.');
CALL sp_registrar_hipotesis('H02', 'Principiante', 'Gimnasio completo', NULL, NULL,
    '3 o más días', 'Sedentario',
    '3 días/semana. Circuito de cuerpo completo con máquinas guiadas y barra con carga ligera: sentadilla en máquina o prensa, press de pecho en máquina, jalón al pecho, puente de glúteo y plancha abdominal. 3x10-15, carga ligera, énfasis total en la técnica.');
CALL sp_registrar_hipotesis('H03', 'Intermedio', 'Básico o en casa', 'Fuerza', NULL,
    NULL, NULL,
    '4 días/semana. Sentadilla búlgara con mancuernas, press militar con mancuernas, remo con mancuerna a una mano y peso muerto rumano con mancuernas. 4x8-10, aumento progresivo de carga.');
CALL sp_registrar_hipotesis('H04', 'Intermedio', 'Básico o en casa', 'Hipertrofia', NULL,
    NULL, NULL,
    '4 días/semana. Zancadas con mancuernas, press inclinado con mancuernas, remo renegado y press de hombro con mancuernas, distribuidos por grupo muscular. 4x10-12, descanso 45-60 s.');
CALL sp_registrar_hipotesis('H05', 'Intermedio', 'Básico o en casa', 'Resistencia', NULL,
    NULL, NULL,
    '5 días/semana. Circuitos de sentadilla con salto, burpees, remo con banda y escaladores, en rondas largas con descansos breves.');
CALL sp_registrar_hipotesis('H06', 'Intermedio', 'Básico o en casa', 'Pérdida de grasa', NULL,
    NULL, NULL,
    '5 días/semana. Circuitos de alta intensidad (HIIT): sentadilla con salto, mountain climbers, remo con banda y plancha dinámica, descansos cortos.');
CALL sp_registrar_hipotesis('H07', 'Intermedio', 'Básico o en casa', 'Rendimiento deportivo', NULL,
    NULL, NULL,
    '4 días/semana. Trabajo de potencia: sentadilla con salto, zancadas con salto, push press con mancuernas y desplazamientos laterales de agilidad con peso corporal, orientado al deporte.');
CALL sp_registrar_hipotesis('H08', 'Intermedio', 'Gimnasio completo', 'Fuerza', NULL,
    NULL, NULL,
    '4 días/semana. Sentadilla con barra, press banca con barra, remo con barra y peso muerto rumano con barra. Rutina dividida empuje/tracción/pierna, 4x6-8, cargas progresivas.');
CALL sp_registrar_hipotesis('H09', 'Intermedio', 'Gimnasio completo', 'Hipertrofia', NULL,
    NULL, NULL,
    '4-5 días/semana. Rutina por grupo muscular: press banca, jalón al pecho, extensión de cuádriceps y curl femoral en máquina. 4x10-12.');
CALL sp_registrar_hipotesis('H10', 'Intermedio', 'Gimnasio completo', 'Resistencia', NULL,
    NULL, NULL,
    '5 días/semana. Circuitos en máquinas (prensa, remo, elíptica) combinados con pesas de carga moderada, series largas.');
CALL sp_registrar_hipotesis('H11', 'Intermedio', 'Gimnasio completo', 'Pérdida de grasa', NULL,
    NULL, NULL,
    '5 días/semana. Circuitos de máquinas (prensa, remo, press) combinados con cardio en cinta o elíptica, descansos cortos.');
CALL sp_registrar_hipotesis('H12', 'Intermedio', 'Gimnasio completo', 'Rendimiento deportivo', NULL,
    NULL, NULL,
    '4 días/semana. Sentadilla con barra a velocidad controlada, arrancada con mancuernas y ejercicios pliométricos, orientado al deporte.');
CALL sp_registrar_hipotesis('H13', 'Avanzado', 'Básico o en casa', 'Fuerza', 'Volumen',
    NULL, NULL,
    '5 días/semana. Sentadilla búlgara pesada, press militar con mancuernas, remo a una mano y peso muerto rumano con mancuernas pesadas. Fase de acumulación: 4-5x8-10, descansos de 90 s.');
CALL sp_registrar_hipotesis('H14', 'Avanzado', 'Básico o en casa', 'Fuerza', 'Intensidad',
    NULL, NULL,
    '5 días/semana. Sentadilla a una pierna con mancuernas pesadas, press militar pesado y peso muerto rumano a carga máxima tolerable. Fase de intensificación: 5x3-5, descansos de 2-3 min.');
CALL sp_registrar_hipotesis('H15', 'Avanzado', 'Básico o en casa', 'Hipertrofia', 'Volumen',
    NULL, NULL,
    '5-6 días/semana. Zancadas búlgaras, press inclinado con mancuernas, remo renegado y elevaciones laterales, distribuidos por grupo muscular. 4-5x10-15, descansos cortos.');
CALL sp_registrar_hipotesis('H16', 'Avanzado', 'Básico o en casa', 'Hipertrofia', 'Intensidad',
    NULL, NULL,
    '5-6 días/semana. Técnicas de intensificación con mancuernas (series descendentes, repeticiones forzadas) en sentadilla búlgara, press y remo. Cargas más altas, menor volumen por sesión.');
CALL sp_registrar_hipotesis('H17', 'Avanzado', 'Básico o en casa', 'Resistencia', NULL,
    NULL, NULL,
    '6 días/semana. Circuitos de alta exigencia alternando bloques de alto volumen y bloques de alta intensidad: sentadilla con salto, burpees, mountain climbers y remo con banda, con planificación por semanas.');
CALL sp_registrar_hipotesis('H18', 'Avanzado', 'Básico o en casa', 'Pérdida de grasa', NULL,
    NULL, NULL,
    '6 días/semana. HIIT avanzado con mancuernas y bandas, alternando semanas de mayor volumen de trabajo metabólico y semanas de mayor intensidad, descansos mínimos.');
CALL sp_registrar_hipotesis('H19', 'Avanzado', 'Básico o en casa', 'Rendimiento deportivo', NULL,
    NULL, NULL,
    '5-6 días/semana. Trabajo de potencia, pliometría y velocidad con peso corporal y bandas, alternando bloques de acumulación de volumen y bloques de máxima intensidad según la fase de la temporada deportiva.');
CALL sp_registrar_hipotesis('H20', 'Avanzado', 'Gimnasio completo', 'Fuerza', 'Volumen',
    NULL, NULL,
    '5 días/semana. Sentadilla frontal, press banca con pausa, peso muerto rumano y remo con barra. Fase de acumulación: 4-5x8-10, descansos de 90 s.');
CALL sp_registrar_hipotesis('H21', 'Avanzado', 'Gimnasio completo', 'Fuerza', 'Intensidad',
    NULL, NULL,
    '5 días/semana. Sentadilla trasera, press banca y peso muerto convencional con barra olímpica. Fase de intensificación: 5x3-5, descansos de 2-3 min, progresión estricta hacia cargas máximas.');
CALL sp_registrar_hipotesis('H22', 'Avanzado', 'Gimnasio completo', 'Hipertrofia', 'Volumen',
    NULL, NULL,
    '5-6 días/semana. Rutina por grupo muscular: press banca, jalón al pecho, extensión de cuádriceps y curl femoral. 4-5x10-15, descansos cortos.');
CALL sp_registrar_hipotesis('H23', 'Avanzado', 'Gimnasio completo', 'Hipertrofia', 'Intensidad',
    NULL, NULL,
    '5-6 días/semana. Técnicas de intensificación (series descendentes, superseries, repeticiones forzadas) en press banca, sentadilla y jalón al pecho. Cargas más altas, menor volumen por sesión.');
CALL sp_registrar_hipotesis('H24', 'Avanzado', 'Gimnasio completo', 'Resistencia', NULL,
    NULL, NULL,
    '6 días/semana. Circuitos en máquinas y pesas alternando bloques de alto volumen y bloques de alta intensidad, con planificación por semanas.');
CALL sp_registrar_hipotesis('H25', 'Avanzado', 'Gimnasio completo', 'Pérdida de grasa', NULL,
    NULL, NULL,
    '6 días/semana. HIIT avanzado con máquinas y barra, alternando semanas de mayor volumen metabólico y semanas de mayor intensidad, descansos mínimos.');
CALL sp_registrar_hipotesis('H26', 'Avanzado', 'Gimnasio completo', 'Rendimiento deportivo', NULL,
    NULL, NULL,
    '5-6 días/semana. Trabajo de potencia con barra (arrancada, sentadilla explosiva) y pliometría, alternando bloques de volumen y bloques de máxima intensidad según la fase de la temporada deportiva.');
CALL sp_registrar_hipotesis('H27', 'Principiante', 'Básico o en casa', NULL, NULL,
    '2 días', 'Sedentario',
    '2 días/semana. Cuerpo completo con peso corporal: sentadilla a una silla, flexiones apoyadas en la pared, remo con banda elástica, puente de glúteo y plancha con rodillas apoyadas. 2x10-12, descansos de 90 s y 5 min de movilidad articular al inicio. Añadir una serie cada dos semanas si la técnica es correcta.');
CALL sp_registrar_hipotesis('H28', 'Principiante', 'Básico o en casa', NULL, NULL,
    '2 días', 'Algo activo',
    '2 días/semana. Cuerpo completo con peso corporal y bandas: sentadilla libre, flexiones con rodillas apoyadas, remo con banda, zancada estática y plancha frontal. 3x10-12, descansos de 60-90 s. Pasar a mancuernas livianas cuando las tres series salgan con buena técnica.');
CALL sp_registrar_hipotesis('H29', 'Principiante', 'Básico o en casa', NULL, NULL,
    '3 o más días', 'Algo activo',
    '3 días/semana. Cuerpo completo alternando dos sesiones (A/B): sentadilla, flexiones, remo con banda, zancada, puente de glúteo y plancha lateral con mancuernas livianas. 3x12-15, descansos de 60 s. Progresión semanal de repeticiones antes de aumentar la carga.');
CALL sp_registrar_hipotesis('H30', 'Principiante', 'Gimnasio completo', NULL, NULL,
    '2 días', 'Sedentario',
    '2 días/semana. Circuito guiado en máquinas: prensa de piernas, press de pecho en máquina, jalón al pecho, curl femoral en máquina y plancha. 2x10-12 con carga ligera, descansos de 90 s y 10 min de caminata en cinta para calentar.');
CALL sp_registrar_hipotesis('H31', 'Principiante', 'Gimnasio completo', NULL, NULL,
    '2 días', 'Algo activo',
    '2 días/semana. Cuerpo completo con máquinas y mancuernas: prensa de piernas, press de pecho en máquina, remo sentado en polea, zancadas con mancuernas livianas y plancha. 3x10-12, descansos de 60-90 s.');
CALL sp_registrar_hipotesis('H32', 'Principiante', 'Gimnasio completo', NULL, NULL,
    '3 o más días', 'Algo activo',
    '3 días/semana. Cuerpo completo alternando sesiones A/B: sentadilla en máquina Smith, press de pecho con mancuernas, jalón al pecho, peso muerto rumano con mancuernas livianas, remo en polea y plancha. 3x10-12, descansos de 60 s y aumento gradual de la carga cada semana manteniendo la técnica.');

-- ---------------------------------------------------------------------
-- 4.4 Gránulos: las 48 reglas del árbol como asociaciones hecho -> hipótesis con peso.
-- ---------------------------------------------------------------------
CREATE TEMP TABLE reglas_origen (regla VARCHAR(5), hipotesis VARCHAR(5), condiciones TEXT);
INSERT INTO reglas_origen VALUES
 ('R01', 'H01', 'tecnica_dominada = No; equipo_disponible = Básico o en casa; dias_semana = 3 o más días; actividad_actual = Sedentario'),
 ('R02', 'H02', 'tecnica_dominada = No; equipo_disponible = Gimnasio completo; dias_semana = 3 o más días; actividad_actual = Sedentario'),
 ('R03', 'H01', 'tecnica_dominada = No estoy seguro; equipo_disponible = Básico o en casa; dias_semana = 3 o más días; actividad_actual = Sedentario'),
 ('R04', 'H02', 'tecnica_dominada = No estoy seguro; equipo_disponible = Gimnasio completo; dias_semana = 3 o más días; actividad_actual = Sedentario'),
 ('R05', 'H01', 'tecnica_dominada = Sí; tiempo_entrenando = Menos de 6 meses; equipo_disponible = Básico o en casa; dias_semana = 3 o más días; actividad_actual = Sedentario'),
 ('R06', 'H02', 'tecnica_dominada = Sí; tiempo_entrenando = Menos de 6 meses; equipo_disponible = Gimnasio completo; dias_semana = 3 o más días; actividad_actual = Sedentario'),
 ('R07', 'H03', 'tecnica_dominada = Sí; tiempo_entrenando = 6 meses a 2 años; equipo_disponible = Básico o en casa; objetivo_principal = Fuerza'),
 ('R08', 'H04', 'tecnica_dominada = Sí; tiempo_entrenando = 6 meses a 2 años; equipo_disponible = Básico o en casa; objetivo_principal = Hipertrofia'),
 ('R09', 'H05', 'tecnica_dominada = Sí; tiempo_entrenando = 6 meses a 2 años; equipo_disponible = Básico o en casa; objetivo_principal = Resistencia'),
 ('R10', 'H06', 'tecnica_dominada = Sí; tiempo_entrenando = 6 meses a 2 años; equipo_disponible = Básico o en casa; objetivo_principal = Pérdida de grasa'),
 ('R11', 'H07', 'tecnica_dominada = Sí; tiempo_entrenando = 6 meses a 2 años; equipo_disponible = Básico o en casa; objetivo_principal = Rendimiento deportivo'),
 ('R12', 'H08', 'tecnica_dominada = Sí; tiempo_entrenando = 6 meses a 2 años; equipo_disponible = Gimnasio completo; objetivo_principal = Fuerza'),
 ('R13', 'H09', 'tecnica_dominada = Sí; tiempo_entrenando = 6 meses a 2 años; equipo_disponible = Gimnasio completo; objetivo_principal = Hipertrofia'),
 ('R14', 'H10', 'tecnica_dominada = Sí; tiempo_entrenando = 6 meses a 2 años; equipo_disponible = Gimnasio completo; objetivo_principal = Resistencia'),
 ('R15', 'H11', 'tecnica_dominada = Sí; tiempo_entrenando = 6 meses a 2 años; equipo_disponible = Gimnasio completo; objetivo_principal = Pérdida de grasa'),
 ('R16', 'H12', 'tecnica_dominada = Sí; tiempo_entrenando = 6 meses a 2 años; equipo_disponible = Gimnasio completo; objetivo_principal = Rendimiento deportivo'),
 ('R17', 'H13', 'tecnica_dominada = Sí; tiempo_entrenando = Más de 2 años; equipo_disponible = Básico o en casa; objetivo_principal = Fuerza; fase_priorizada = Volumen'),
 ('R18', 'H14', 'tecnica_dominada = Sí; tiempo_entrenando = Más de 2 años; equipo_disponible = Básico o en casa; objetivo_principal = Fuerza; fase_priorizada = Intensidad'),
 ('R19', 'H15', 'tecnica_dominada = Sí; tiempo_entrenando = Más de 2 años; equipo_disponible = Básico o en casa; objetivo_principal = Hipertrofia; fase_priorizada = Volumen'),
 ('R20', 'H16', 'tecnica_dominada = Sí; tiempo_entrenando = Más de 2 años; equipo_disponible = Básico o en casa; objetivo_principal = Hipertrofia; fase_priorizada = Intensidad'),
 ('R21', 'H17', 'tecnica_dominada = Sí; tiempo_entrenando = Más de 2 años; equipo_disponible = Básico o en casa; objetivo_principal = Resistencia'),
 ('R22', 'H18', 'tecnica_dominada = Sí; tiempo_entrenando = Más de 2 años; equipo_disponible = Básico o en casa; objetivo_principal = Pérdida de grasa'),
 ('R23', 'H19', 'tecnica_dominada = Sí; tiempo_entrenando = Más de 2 años; equipo_disponible = Básico o en casa; objetivo_principal = Rendimiento deportivo'),
 ('R24', 'H20', 'tecnica_dominada = Sí; tiempo_entrenando = Más de 2 años; equipo_disponible = Gimnasio completo; objetivo_principal = Fuerza; fase_priorizada = Volumen'),
 ('R25', 'H21', 'tecnica_dominada = Sí; tiempo_entrenando = Más de 2 años; equipo_disponible = Gimnasio completo; objetivo_principal = Fuerza; fase_priorizada = Intensidad'),
 ('R26', 'H22', 'tecnica_dominada = Sí; tiempo_entrenando = Más de 2 años; equipo_disponible = Gimnasio completo; objetivo_principal = Hipertrofia; fase_priorizada = Volumen'),
 ('R27', 'H23', 'tecnica_dominada = Sí; tiempo_entrenando = Más de 2 años; equipo_disponible = Gimnasio completo; objetivo_principal = Hipertrofia; fase_priorizada = Intensidad'),
 ('R28', 'H24', 'tecnica_dominada = Sí; tiempo_entrenando = Más de 2 años; equipo_disponible = Gimnasio completo; objetivo_principal = Resistencia'),
 ('R29', 'H25', 'tecnica_dominada = Sí; tiempo_entrenando = Más de 2 años; equipo_disponible = Gimnasio completo; objetivo_principal = Pérdida de grasa'),
 ('R30', 'H26', 'tecnica_dominada = Sí; tiempo_entrenando = Más de 2 años; equipo_disponible = Gimnasio completo; objetivo_principal = Rendimiento deportivo'),
 ('R31', 'H27', 'tecnica_dominada = No; equipo_disponible = Básico o en casa; dias_semana = 2 días; actividad_actual = Sedentario'),
 ('R32', 'H28', 'tecnica_dominada = No; equipo_disponible = Básico o en casa; dias_semana = 2 días; actividad_actual = Algo activo'),
 ('R33', 'H29', 'tecnica_dominada = No; equipo_disponible = Básico o en casa; dias_semana = 3 o más días; actividad_actual = Algo activo'),
 ('R34', 'H30', 'tecnica_dominada = No; equipo_disponible = Gimnasio completo; dias_semana = 2 días; actividad_actual = Sedentario'),
 ('R35', 'H31', 'tecnica_dominada = No; equipo_disponible = Gimnasio completo; dias_semana = 2 días; actividad_actual = Algo activo'),
 ('R36', 'H32', 'tecnica_dominada = No; equipo_disponible = Gimnasio completo; dias_semana = 3 o más días; actividad_actual = Algo activo'),
 ('R37', 'H27', 'tecnica_dominada = No estoy seguro; equipo_disponible = Básico o en casa; dias_semana = 2 días; actividad_actual = Sedentario'),
 ('R38', 'H28', 'tecnica_dominada = No estoy seguro; equipo_disponible = Básico o en casa; dias_semana = 2 días; actividad_actual = Algo activo'),
 ('R39', 'H29', 'tecnica_dominada = No estoy seguro; equipo_disponible = Básico o en casa; dias_semana = 3 o más días; actividad_actual = Algo activo'),
 ('R40', 'H30', 'tecnica_dominada = No estoy seguro; equipo_disponible = Gimnasio completo; dias_semana = 2 días; actividad_actual = Sedentario'),
 ('R41', 'H31', 'tecnica_dominada = No estoy seguro; equipo_disponible = Gimnasio completo; dias_semana = 2 días; actividad_actual = Algo activo'),
 ('R42', 'H32', 'tecnica_dominada = No estoy seguro; equipo_disponible = Gimnasio completo; dias_semana = 3 o más días; actividad_actual = Algo activo'),
 ('R43', 'H27', 'tecnica_dominada = Sí; tiempo_entrenando = Menos de 6 meses; equipo_disponible = Básico o en casa; dias_semana = 2 días; actividad_actual = Sedentario'),
 ('R44', 'H28', 'tecnica_dominada = Sí; tiempo_entrenando = Menos de 6 meses; equipo_disponible = Básico o en casa; dias_semana = 2 días; actividad_actual = Algo activo'),
 ('R45', 'H29', 'tecnica_dominada = Sí; tiempo_entrenando = Menos de 6 meses; equipo_disponible = Básico o en casa; dias_semana = 3 o más días; actividad_actual = Algo activo'),
 ('R46', 'H30', 'tecnica_dominada = Sí; tiempo_entrenando = Menos de 6 meses; equipo_disponible = Gimnasio completo; dias_semana = 2 días; actividad_actual = Sedentario'),
 ('R47', 'H31', 'tecnica_dominada = Sí; tiempo_entrenando = Menos de 6 meses; equipo_disponible = Gimnasio completo; dias_semana = 2 días; actividad_actual = Algo activo'),
 ('R48', 'H32', 'tecnica_dominada = Sí; tiempo_entrenando = Menos de 6 meses; equipo_disponible = Gimnasio completo; dias_semana = 3 o más días; actividad_actual = Algo activo');

DO $$
DECLARE
    r       RECORD;
    v_item  TEXT;
    v_hecho TEXT;
BEGIN
    FOR r IN SELECT * FROM reglas_origen ORDER BY regla LOOP
        FOREACH v_item IN ARRAY string_to_array(r.condiciones, ';') LOOP
            SELECT he.codigo INTO v_hecho
              FROM hechos he JOIN preguntas p ON p.id_pregunta = he.id_pregunta
             WHERE p.atributo = btrim(split_part(v_item, '=', 1))
               AND he.valor   = btrim(substr(v_item, strpos(v_item, '=') + 1));
            IF v_hecho IS NULL THEN
                RAISE EXCEPTION 'Regla %: condición sin hecho "%"', r.regla, btrim(v_item);
            END IF;
            CALL sp_asociar_hecho_hipotesis(v_hecho, r.hipotesis);
        END LOOP;
    END LOOP;
END $$;

DROP TABLE reglas_origen;
