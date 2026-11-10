"""Pruebas de seguridad por rol (permitido / denegado). Corre en una transacción que se deshace.
Uso: python3 pruebas_seguridad.py local|aurora"""
import sys

from verificar_caminos import conectar

resultados = []


class Sesion:
    def __init__(self, con):
        self.con = con
        self.n = 0

    def como(self, rol, id_usuario=None, correo=None, sub=None):
        self.con.run("RESET ROLE")
        self.con.run(f"SET ROLE {rol}")
        self.con.run("SELECT set_config('app.id_usuario', :v, false)", v=str(id_usuario or ""))
        self.con.run("SELECT set_config('app.correo', :v, false)", v=correo or "")
        self.con.run("SELECT set_config('app.cognito_sub', :v, false)", v=sub or "")

    def _ejecutar(self, sql, params):
        self.n += 1
        self.con.run(f"SAVEPOINT p{self.n}")
        try:
            filas = self.con.run(sql, **params)
            self.con.run(f"RELEASE SAVEPOINT p{self.n}")
            return filas, None
        except Exception as e:
            self.con.run(f"ROLLBACK TO SAVEPOINT p{self.n}")
            msg = e.args[0].get("M", str(e)) if e.args and isinstance(e.args[0], dict) else str(e)
            return None, msg

    def permitido(self, descripcion, sql, comprobar=None, **params):
        filas, error = self._ejecutar(sql, params)
        ok = error is None and (comprobar is None or comprobar(filas))
        resultados.append((ok, "PERMITIDO", descripcion, error or (filas if filas else "")))
        return filas

    def denegado(self, descripcion, sql, fragmento, **params):
        filas, error = self._ejecutar(sql, params)
        ok = error is not None and fragmento.lower() in error.lower()
        resultados.append((ok, "DENEGADO", descripcion, error or "¡se permitió!"))


def main():
    destino = sys.argv[1] if len(sys.argv) > 1 else "local"
    con = conectar(destino)
    s = Sesion(con)
    con.run("BEGIN")
    try:
        # --- Sin rol: app_lambda no hereda permisos ---------------------------
        s.con.run("RESET ROLE")
        s.denegado("app_lambda sin SET ROLE no lee la base de conocimiento",
                   "SELECT count(*) FROM se.preguntas", "permission denied")

        # --- Administrador crea los perfiles de prueba --------------------------
        s.como("rol_administrador", correo="admin@prueba")
        ids = {}
        for nombre, alias, rol in [("Diego", "diego", "administrador"),
                                   ("Simón", "simon", "ingeniero_conocimiento"),
                                   ("Cristian", "cristian", "experto"),
                                   ("Profesor", "profesor", "experto"),
                                   ("Laura Prueba", "laura", "usuario_final"),
                                   ("Andrés Prueba", "andres", "usuario_final")]:
            fila = s.permitido(f"Administrador registra a {nombre} ({rol})",
                               "INSERT INTO usuario (cognito_sub, nombre, alias, correo, rol) "
                               "VALUES (:sub, :n, :a, :c, CAST(:r AS t_rol_sistema)) "
                               "RETURNING id_usuario",
                               # alias propio: las 7 cuentas de demostración ya usan "diego", "simon"...
                               sub=f"prueba-{alias}", n=nombre, a=f"prueba-{alias}",
                               c=f"{alias}@prueba.local", r=rol)
            ids[alias] = fila[0][0] if fila else None

        # --- Usuario final ------------------------------------------------------
        s.como("rol_usuario", ids["laura"], "laura@prueba.local", "prueba-laura")
        s.permitido("Usuario final lee la base de conocimiento (el motor la usa)",
                    "SELECT count(*) FROM hechos_hipotesis", lambda f: f[0][0] == 160)
        s.denegado("Usuario final no puede escribir en la base de conocimiento",
                   "INSERT INTO hechos (codigo, id_pregunta, valor) VALUES ('X', 1, 'x')",
                   "permission denied")
        s.denegado("Usuario final no puede ejecutar procedimientos del ingeniero",
                   "CALL sp_eliminar_hipotesis('H01')", "permission denied")
        fila = s.permitido("Usuario final inicia SU consulta",
                           "INSERT INTO consulta (id_usuario) VALUES (:u) RETURNING id_consulta",
                           u=ids["laura"])
        consulta_laura = fila[0][0] if fila else None
        s.permitido("Usuario final registra una respuesta en su consulta",
                    "INSERT INTO consulta_hecho (id_consulta, paso, id_hecho) "
                    "SELECT :c, 1, id_hecho FROM hechos WHERE codigo = 'HC01'",
                    c=consulta_laura)
        s.denegado("No se responde dos veces la misma pregunta (la pregunta sale del hecho)",
                   "INSERT INTO consulta_hecho (id_consulta, paso, id_hecho) "
                   "SELECT :c, 2, id_hecho FROM hechos WHERE codigo = 'HC02'",
                   "ya se respondió", c=consulta_laura)
        s.denegado("Usuario final no puede tener dos consultas abiertas a la vez",
                   "INSERT INTO consulta (id_usuario) VALUES (:u)", "ux_consulta_abierta",
                   u=ids["laura"])
        s.permitido("Usuario final termina su consulta",
                    "UPDATE consulta SET estado = 'terminada', fecha_fin = CURRENT_TIMESTAMP "
                    "WHERE id_consulta = :c RETURNING id_consulta", lambda f: len(f) == 1,
                    c=consulta_laura)
        s.denegado("Una consulta cerrada no se puede volver a abrir",
                   "UPDATE consulta SET estado = 'en_curso', fecha_fin = NULL WHERE id_consulta = :c",
                   "ya está cerrada", c=consulta_laura)
        fila = s.permitido("Usuario final abre otra consulta cuando cierra la anterior",
                           "INSERT INTO consulta (id_usuario) VALUES (:u) RETURNING id_consulta",
                           u=ids["laura"])
        s.permitido("Usuario final descarta su consulta abierta",
                    "UPDATE consulta SET estado = 'abandonada', fecha_fin = CURRENT_TIMESTAMP "
                    "WHERE id_consulta = :c RETURNING id_consulta", lambda f: len(f) == 1,
                    c=fila[0][0] if fila else None)
        s.denegado("Usuario final no registra opiniones del experto",
                   "INSERT INTO traza_inferencia (id_consulta, paso, tipo, detalle) "
                   "VALUES (:c, 1, 'validacion_experto', jsonb_build_object('id_experto', CAST(:u AS INT), 'de_acuerdo', true))",
                   "row-level security", c=consulta_laura, u=ids["laura"])
        s.denegado("Usuario final no puede crear consultas a nombre de otro",
                   "INSERT INTO consulta (id_usuario) VALUES (:u)", "row-level security",
                   u=ids["andres"])
        s.denegado("Usuario final no puede registrarse como administrador",
                   "INSERT INTO usuario (cognito_sub, nombre, alias, correo, rol) "
                   "VALUES ('prueba-laura', 'X', 'x2', 'x2@prueba', 'administrador')",
                   "row-level security")
        s.denegado("Usuario final no puede cambiarse el rol",
                   "UPDATE usuario SET rol = 'administrador' WHERE id_usuario = :u",
                   "permission denied", u=ids["laura"])
        s.denegado("Usuario final no puede ver la auditoría",
                   "SELECT count(*) FROM auditoria", "permission denied")

        s.como("rol_usuario", ids["andres"], "andres@prueba.local", "prueba-andres")
        s.permitido("Otro usuario final NO ve las consultas de Laura",
                    "SELECT count(*) FROM consulta WHERE id_consulta = :c",
                    lambda f: f[0][0] == 0, c=consulta_laura)
        s.permitido("Otro usuario final NO ve las respuestas de Laura",
                    "SELECT count(*) FROM consulta_hecho WHERE id_consulta = :c",
                    lambda f: f[0][0] == 0, c=consulta_laura)

        # --- Experto humano -----------------------------------------------------
        s.como("rol_experto", ids["cristian"], "cristian@prueba.local")
        s.permitido("Experto ve todas las consultas",
                    "SELECT count(*) FROM consulta WHERE id_consulta = :c",
                    lambda f: f[0][0] == 1, c=consulta_laura)
        s.permitido("Experto ve el alias de los usuarios",
                    "SELECT alias FROM usuario WHERE id_usuario = :u", u=ids["laura"])
        s.denegado("Experto NO ve el correo de los usuarios",
                   "SELECT correo FROM usuario", "permission denied")
        s.permitido("Experto valida un diagnóstico a su nombre",
                    "INSERT INTO traza_inferencia (id_consulta, paso, tipo, detalle) "
                    "VALUES (:c, 1, 'validacion_experto', jsonb_build_object('id_experto', CAST(:e AS INT), "
                    "'de_acuerdo', true, 'comentario', 'Coincide con mi criterio'))",
                    c=consulta_laura, e=ids["cristian"])
        s.denegado("Experto no puede validar a nombre de otro",
                   "INSERT INTO traza_inferencia (id_consulta, paso, tipo, detalle) "
                   "VALUES (:c, 1, 'validacion_experto', jsonb_build_object('id_experto', CAST(:e AS INT), 'de_acuerdo', false))",
                   "row-level security", c=consulta_laura, e=ids["simon"])
        s.denegado("Una opinión por experto y consulta (la cambia, no la duplica)",
                   "INSERT INTO traza_inferencia (id_consulta, paso, tipo, detalle) "
                   "VALUES (:c, 1, 'validacion_experto', jsonb_build_object('id_experto', CAST(:e AS INT), 'de_acuerdo', false))",
                   "ux_traza_validacion", c=consulta_laura, e=ids["cristian"])
        s.como("rol_experto", ids["profesor"], "profesor@prueba.local")
        s.permitido("Un segundo experto da su propia opinión sobre la misma consulta",
                    "INSERT INTO traza_inferencia (id_consulta, paso, tipo, detalle) "
                    "VALUES (:c, 1, 'validacion_experto', jsonb_build_object('id_experto', CAST(:e AS INT), "
                    "'de_acuerdo', false))", c=consulta_laura, e=ids["profesor"])
        s.permitido("Un experto no cambia la opinión de otro (la fila no le aparece)",
                    "UPDATE traza_inferencia SET detalle = detalle || '{\"de_acuerdo\": false}' "
                    "WHERE tipo = 'validacion_experto' AND (detalle->>'id_experto')::INT = :e "
                    "RETURNING id_traza", lambda f: len(f) == 0, e=ids["cristian"])
        s.como("rol_experto", ids["cristian"], "cristian@prueba.local")
        s.permitido("Experto ve las dos opiniones registradas",
                    "SELECT count(*) FROM traza_inferencia WHERE tipo = 'validacion_experto' AND id_consulta = :c",
                    lambda f: f[0][0] == 2, c=consulta_laura)
        s.como("rol_usuario", ids["laura"], "laura@prueba.local", "prueba-laura")
        s.permitido("El usuario final no ve la opinión del experto sobre su consulta",
                    "SELECT count(*) FROM traza_inferencia WHERE tipo = 'validacion_experto' AND id_consulta = :c",
                    lambda f: f[0][0] == 0, c=consulta_laura)
        s.como("rol_experto", ids["cristian"], "cristian@prueba.local")
        s.denegado("Experto no puede modificar el conocimiento",
                   "CALL sp_asociar_hecho_hipotesis('HC07', 'H01', 0.5)", "permission denied")
        s.denegado("El validador de la base es del ingeniero (el experto solo consulta)",
                   "SELECT count(*) FROM fn_validar_base()", "permission denied")
        s.permitido("Experto registra la verificación formal de una consulta",
                    "UPDATE consulta SET verificacion_formal = 'VALID', fecha_verificacion = CURRENT_TIMESTAMP "
                    "WHERE id_consulta = :c RETURNING id_consulta", lambda f: len(f) == 1, c=consulta_laura)
        s.denegado("Una verificación con resultado lógico es definitiva",
                   "UPDATE consulta SET verificacion_formal = 'INVALID' WHERE id_consulta = :c",
                   "ya es definitiva", c=consulta_laura)

        # --- Ingeniero del conocimiento -----------------------------------------
        s.como("rol_ingeniero_conocimiento", ids["simon"], "simon@prueba.local")
        s.permitido("Ingeniero ajusta el peso de un gránulo (procedimiento)",
                    "CALL sp_asociar_hecho_hipotesis('HC08', 'H21', 0.82)")
        s.denegado("Ingeniero no puede escribir directo en las tablas",
                   "UPDATE hechos_hipotesis SET peso = 0.5", "permission denied")
        s.denegado("El procedimiento rechaza un gránulo incoherente",
                   "CALL sp_asociar_hecho_hipotesis('HC07', 'H21')", "no corresponde")
        s.denegado("El procedimiento rechaza una hipótesis mal formada",
                   "CALL sp_registrar_hipotesis('H99', 'Principiante', 'Gimnasio completo', "
                   "'Fuerza', NULL, '2 días', 'Sedentario', 'x')", "no se diferencia por objetivo")
        s.denegado("El procedimiento rechaza días por semana en una hipótesis Intermedio",
                   "CALL sp_registrar_hipotesis('H98', 'Intermedio', 'Gimnasio completo', "
                   "'Fuerza', NULL, '2 días', NULL, 'x')", "solo aplican")
        s.denegado("El procedimiento rechaza un gránulo de días ajeno a la hipótesis",
                   "CALL sp_asociar_hecho_hipotesis('HC16', 'H09')", "no aplica a su nivel")
        s.denegado("El procedimiento rechaza un peso fuera de rango",
                   "CALL sp_asociar_hecho_hipotesis('HC08', 'H21', 1.5)", "entre 0 y 1")
        s.denegado("No se puede eliminar un hecho que respalda hipótesis",
                   "CALL sp_eliminar_hecho('HC01')", "asociado")
        s.permitido("Ingeniero ejecuta el validador de la base",
                    "SELECT count(*) FROM fn_validar_base() WHERE resultado = 'FALLO'",
                    lambda f: f[0][0] == 0)
        s.denegado("Ingeniero no ve datos personales",
                   "SELECT correo FROM usuario", "permission denied")
        s.denegado("Ingeniero no gestiona usuarios",
                   "UPDATE usuario SET rol = 'experto' WHERE id_usuario = :u",
                   "permission denied", u=ids["laura"])

        # --- Administrador -------------------------------------------------------
        s.como("rol_administrador", ids["diego"], "diego@prueba.local")
        s.permitido("Administrador cambia el rol de otro usuario",
                    "UPDATE usuario SET rol = 'experto' WHERE id_usuario = :u", u=ids["andres"])
        s.denegado("Administrador no puede cambiar su propio rol",
                   "UPDATE usuario SET rol = 'usuario_final' WHERE id_usuario = :u",
                   "propio rol", u=ids["diego"])
        s.denegado("Administrador no modifica el conocimiento",
                   "CALL sp_asociar_hecho_hipotesis('HC08', 'H21', 0.9)", "permission denied")
        s.permitido("La auditoría registró el cambio del ingeniero con su correo",
                    "SELECT count(*) FROM auditoria WHERE tabla = 'hechos_hipotesis' "
                    "AND usuario_app = 'simon@prueba.local'", lambda f: f[0][0] >= 1)
        s.permitido("La auditoría registró el cambio de rol",
                    "SELECT count(*) FROM auditoria WHERE tabla = 'usuario' AND accion = 'UPDATE'",
                    lambda f: f[0][0] >= 1)
    finally:
        con.run("ROLLBACK")        # no queda ningún dato de prueba
        con.close()

    print("PRUEBAS DE SEGURIDAD POR ROL\n")
    for ok, tipo, desc, detalle in resultados:
        extra = f"  ← {detalle}" if not ok else ""
        print(f"  {'OK   ' if ok else 'FALLO'} [{tipo:9}] {desc}{extra}")
    fallos = sum(not r[0] for r in resultados)
    print(f"\n{len(resultados) - fallos}/{len(resultados)} correctas"
          + (" · TODO CORRECTO" if not fallos else f" · {fallos} FALLOS"))
    sys.exit(1 if fallos else 0)


if __name__ == "__main__":
    main()
