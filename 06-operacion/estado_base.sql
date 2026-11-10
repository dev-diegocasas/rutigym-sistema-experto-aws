SET search_path = se;
SELECT 'Consultas registradas' AS dato, count(*)::text AS valor FROM consulta
UNION ALL SELECT 'Consultas descartadas', count(*)::text FROM consulta WHERE estado = 'abandonada'
UNION ALL SELECT 'Máximo de consultas abiertas por perfil (debe ser 0 o 1)',
       COALESCE((SELECT max(n) FROM (SELECT count(*) AS n FROM consulta WHERE estado = 'en_curso'
                                      GROUP BY id_usuario) x), 0)::text
UNION ALL SELECT 'Regla «una consulta abierta» instalada',
       CASE WHEN EXISTS (SELECT 1 FROM pg_indexes WHERE schemaname = 'se'
                          AND indexname = 'ux_consulta_abierta') THEN 'sí' ELSE 'NO' END
UNION ALL SELECT 'Filas de traza', count(*)::text FROM traza_inferencia
UNION ALL SELECT 'Opiniones del experto', count(*)::text FROM traza_inferencia WHERE tipo = 'validacion_experto'
UNION ALL SELECT 'Filas de auditoría', count(*)::text FROM auditoria
UNION ALL SELECT 'Perfiles de usuario', count(*)::text FROM usuario
UNION ALL SELECT 'Perfiles fuera de los 7 de demostración', count(*)::text FROM usuario
       WHERE NOT correo LIKE ANY (ARRAY['diego.admin@%', 'simon.ingeniero@%', 'cristian.experto@%',
             'profesor.experto@%', 'laura.usuario@%', 'andres.usuario@%', 'valentina.usuario@%'])
UNION ALL SELECT 'Preguntas (esperado 7)', count(*)::text FROM preguntas
UNION ALL SELECT 'Hechos (esperado 19)', count(*)::text FROM hechos
UNION ALL SELECT 'Hipótesis (esperado 32)', count(*)::text FROM hipotesis
UNION ALL SELECT 'Gránulos (esperado 160)', count(*)::text FROM hechos_hipotesis;
