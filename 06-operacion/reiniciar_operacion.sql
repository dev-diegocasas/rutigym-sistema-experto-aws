-- Deja el sistema como recién instalado: sin consultas, sin auditoría y solo
-- con los 7 perfiles de demostración. Los contadores vuelven a empezar en 1.
SET search_path = se;
TRUNCATE consulta_hecho, diagnostico_hipotesis, traza_inferencia, validacion_experto, consulta
         RESTART IDENTITY;
DELETE FROM usuario
 WHERE correo NOT IN ('diego.admin@sistema-experto.test', 'simon.ingeniero@sistema-experto.test',
                      'cristian.experto@sistema-experto.test', 'profesor.experto@sistema-experto.test',
                      'laura.usuario@sistema-experto.test', 'andres.usuario@sistema-experto.test',
                      'valentina.usuario@sistema-experto.test');
SELECT setval(pg_get_serial_sequence('se.usuario', 'id_usuario'),
              (SELECT max(id_usuario) FROM usuario));
TRUNCATE auditoria RESTART IDENTITY;
