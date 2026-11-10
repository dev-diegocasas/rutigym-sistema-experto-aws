-- Recarga la base de conocimiento desde la fuente oficial (04_carga_conocimiento.sql).
-- Se ejecuta en una sola transacción: si algo falla, la base queda como estaba.
SET search_path = se;
TRUNCATE consulta_hecho, diagnostico_hipotesis, traza_inferencia, validacion_experto, consulta,
         hechos_hipotesis, respuesta_pregunta, hipotesis, hechos, preguntas
         RESTART IDENTITY CASCADE;
\ir ../fase1/sql/04_carga_conocimiento.sql
