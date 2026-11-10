"""CAPA DE DATOS · Acceso a Aurora: conexión IAM, transacción por rol y consultas granulares."""
import os
import ssl
from contextlib import contextmanager
from decimal import Decimal

import pg8000.native

AQUI = os.path.dirname(os.path.abspath(__file__))

ROLES_BD = {
    "usuario_final": "rol_usuario",
    "experto": "rol_experto",
    "ingeniero_conocimiento": "rol_ingeniero_conocimiento",
    "administrador": "rol_administrador",
}


# ---------------------------------------------------------------- conexión a Aurora
def _num(v):
    return float(v) if isinstance(v, Decimal) else v


class BaseIniciando(Exception):
    """La base de datos sigue reanudándose (estaba en pausa para no generar costo)."""


def _conectar_una_vez(timeout):
    if os.environ.get("DB_MODO") == "local":                     # solo pruebas locales
        return pg8000.native.Connection(user="app_lambda", database=os.environ["DB_NOMBRE"],
                                        unix_sock=os.environ["DB_SOCKET"], timeout=timeout)
    import boto3
    host = os.environ["DB_HOST"]
    token = boto3.client("rds").generate_db_auth_token(
        DBHostname=host, Port=5432, DBUsername="app_lambda",
        Region=os.environ.get("AWS_REGION", "us-east-1"))
    ctx = ssl.create_default_context()                           # autoridades públicas
    bundle = os.path.join(AQUI, "global-bundle.pem")              # + autoridades de RDS
    if os.path.exists(bundle):
        ctx.load_verify_locations(bundle)
    return pg8000.native.Connection(user="app_lambda", host=host, port=5432,
                                    database="postgres", password=token,
                                    ssl_context=ctx, timeout=timeout)


def abrir_conexion():
    """Conecta con token IAM; si Aurora está reanudándose, reintenta hasta ~23 s."""
    import time
    limite = time.time() + float(os.environ.get("DB_ESPERA_MAX", "23"))
    while True:
        try:
            # Cada intento puede esperar lo que queda del plazo: si Aurora retiene la
            # conexión mientras se reanuda, se completa en cuanto queda lista.
            return _conectar_una_vez(timeout=max(3, limite - time.time()))
        except Exception as e:
            if time.time() + 3 >= limite:
                raise BaseIniciando(str(e)) from e
            time.sleep(2)


class Repositorio:
    def __init__(self, con):
        self.con = con
        self._granulos = {}           # caché solo durante una petición
        self.consultas_granulares = 0

    def _q(self, sql, **p):
        return [[_num(v) for v in fila] for fila in self.con.run(sql, **p)]

    def _dicts(self, sql, **p):
        filas = self.con.run(sql, **p)
        cols = [c["name"] for c in self.con.columns]
        return [{c: _num(v) for c, v in zip(cols, f)} for f in filas]

    # ------------------------------------------------------------ transacción
    @contextmanager
    def transaccion(self, rol_bd, id_usuario=None, correo=None, cognito_sub=None):
        """Toda petición corre en una transacción con el rol de quien la hace.
        SET LOCAL y set_config(..., true) se deshacen solos al terminar."""
        self._granulos = {}
        self.con.run("BEGIN")
        try:
            self.con.run(f"SET LOCAL ROLE {rol_bd}")
            self.con.run("SELECT set_config('app.id_usuario', :v, true)", v=str(id_usuario or ""))
            self.con.run("SELECT set_config('app.correo', :v, true)", v=correo or "")
            self.con.run("SELECT set_config('app.cognito_sub', :v, true)", v=cognito_sub or "")
            yield self
            self.con.run("COMMIT")
        except Exception:
            self.con.run("ROLLBACK")
            raise

    def fijar_usuario(self, id_usuario):
        self.con.run("SELECT set_config('app.id_usuario', :v, true)", v=str(id_usuario))

    def cambiar_rol(self, rol_bd):
        self.con.run(f"SET LOCAL ROLE {rol_bd}")

    # ------------------------------------------------------------ usuarios
    def usuario_por_sub(self, sub):
        f = self._dicts("SELECT id_usuario, nombre, alias, correo, rol::TEXT AS rol, activo "
                        "FROM usuario WHERE cognito_sub = :s", s=sub)
        return f[0] if f else None

    def _con_alias_libre(self, alias, insertar):
        """Inserta probando alias, alias2, alias3... El usuario final no puede ver los alias de
        los demás (seguridad por fila), así que se prueba y, si ya existe, se intenta el siguiente."""
        for n in range(1, 100):
            candidato = alias if n == 1 else f"{alias[:27]}{n}"
            self.con.run("SAVEPOINT alias_libre")
            try:
                resultado = insertar(candidato)
                self.con.run("RELEASE SAVEPOINT alias_libre")
                return resultado, candidato
            except Exception as e:
                self.con.run("ROLLBACK TO SAVEPOINT alias_libre")
                d = e.args[0] if e.args and isinstance(e.args[0], dict) else {}
                if d.get("C") != "23505" or "alias" not in d.get("M", "") + d.get("n", ""):
                    raise
        raise RuntimeError("No hay alias disponible")

    def crear_usuario_final(self, sub, nombre, alias, correo):
        return self._con_alias_libre(alias, lambda a: self._q(
            "INSERT INTO usuario (cognito_sub, nombre, alias, correo) "
            "VALUES (:s, :n, :a, :c) RETURNING id_usuario", s=sub, n=nombre, a=a, c=correo)[0][0])[0]

    # ------------------------------------------------------------ base de conocimiento
    def preguntas(self):
        return self._dicts("SELECT id_pregunta, codigo, atributo, texto, ayuda, orden, peso_base "
                           "FROM preguntas ORDER BY orden")

    def opciones(self):
        # La pregunta de cada opción sale de su hecho
        return self._dicts("SELECT r.id_respuesta, he.id_pregunta, r.id_hecho, r.texto_opcion, "
                           "r.sinonimos, r.orden, he.codigo AS codigo_hecho, he.valor "
                           "FROM respuesta_pregunta r JOIN hechos he ON he.id_hecho = r.id_hecho "
                           "ORDER BY he.id_pregunta, r.orden")

    def hipotesis(self):
        return self._dicts("SELECT id_hipotesis, codigo, nivel::TEXT AS nivel, equipo::TEXT AS equipo, "
                           "objetivo::TEXT AS objetivo, fase::TEXT AS fase, "
                           "dias_semana::TEXT AS dias_semana, actividad::TEXT AS actividad, "
                           "descripcion_rutina, probabilidad_previa FROM hipotesis")

    def granulos_de_pregunta(self, id_pregunta):
        """Consulta granular: hipótesis que dependen de una pregunta, con sus pesos.
        Devuelve {id_hipotesis: {id_hecho: peso}}."""
        if id_pregunta not in self._granulos:
            self.consultas_granulares += 1
            por_hip = {}
            for idh, hecho, peso in self._q(
                    "SELECT hh.id_hipotesis, hh.id_hecho, hh.peso FROM hechos_hipotesis hh "
                    "JOIN hechos he ON he.id_hecho = hh.id_hecho WHERE he.id_pregunta = :p",
                    p=id_pregunta):
                por_hip.setdefault(idh, {})[hecho] = peso
            self._granulos[id_pregunta] = por_hip
        return self._granulos[id_pregunta]

    def granulos_completos(self):
        return self._dicts("SELECT he.codigo AS hecho, h.codigo AS hipotesis, hh.peso "
                           "FROM hechos_hipotesis hh JOIN hechos he ON he.id_hecho = hh.id_hecho "
                           "JOIN hipotesis h ON h.id_hipotesis = hh.id_hipotesis "
                           "ORDER BY h.codigo, he.codigo")

    # ------------------------------------------------------------ consultas
    def crear_consulta(self, id_usuario):
        return self._q("INSERT INTO consulta (id_usuario) VALUES (:u) RETURNING id_consulta",
                       u=id_usuario)[0][0]

    def consulta(self, id_consulta):
        # numero: consecutivo propio de cada perfil (1, 2, 3...), independiente de los
        # demás perfiles y de los saltos que tenga la secuencia interna
        f = self._dicts("SELECT c.id_consulta, c.id_usuario, u.alias, c.estado::TEXT AS estado, "
                        "c.fecha_inicio, c.fecha_fin, c.verificacion_formal, "
                        "(SELECT count(*) FROM consulta c2 WHERE c2.id_usuario = c.id_usuario "
                        "   AND c2.id_consulta <= c.id_consulta) AS numero "
                        "FROM consulta c JOIN usuario u ON u.id_usuario = c.id_usuario "
                        "WHERE c.id_consulta = :c", c=id_consulta)
        return f[0] if f else None

    def consulta_abierta(self, id_usuario):
        """La consulta en curso del perfil (a lo sumo una), con su última actividad."""
        f = self._dicts("SELECT c.id_consulta, c.fecha_inicio, "
                        "(SELECT count(*) FROM consulta_hecho ch WHERE ch.id_consulta = c.id_consulta) AS respondidas, "
                        "GREATEST(c.fecha_inicio, (SELECT max(ch.fecha) FROM consulta_hecho ch "
                        "   WHERE ch.id_consulta = c.id_consulta)) AS ultima_actividad, "
                        "EXTRACT(EPOCH FROM CURRENT_TIMESTAMP - GREATEST(c.fecha_inicio, "
                        "   (SELECT max(ch.fecha) FROM consulta_hecho ch WHERE ch.id_consulta = c.id_consulta)))"
                        "   / 86400 AS dias_inactiva "
                        "FROM consulta c WHERE c.id_usuario = :u AND c.estado = 'en_curso'", u=id_usuario)
        return f[0] if f else None

    def descartar_consulta(self, id_consulta):
        """Cierra una consulta en curso sin resultado. Se conserva el registro."""
        return bool(self._q("UPDATE consulta SET estado = 'abandonada', fecha_fin = CURRENT_TIMESTAMP "
                            "WHERE id_consulta = :c AND estado = 'en_curso' RETURNING id_consulta",
                            c=id_consulta))

    def hechos_de_consulta(self, id_consulta):
        return self._dicts("SELECT ch.paso, he.id_pregunta, ch.id_hecho, ch.origen::TEXT AS origen, "
                           "ch.texto_usuario FROM consulta_hecho ch JOIN hechos he ON he.id_hecho = ch.id_hecho "
                           "WHERE ch.id_consulta = :c ORDER BY ch.paso", c=id_consulta)

    def registrar_hecho(self, id_consulta, paso, id_pregunta, id_hecho, origen, texto):
        # id_pregunta no se guarda: sale del hecho (la base impide responder dos veces la misma)
        self.con.run("INSERT INTO consulta_hecho (id_consulta, paso, id_hecho, origen, texto_usuario) "
                     "VALUES (:c, :p, :h, CAST(:o AS t_origen_respuesta), :t)",
                     c=id_consulta, p=paso, h=id_hecho, o=origen, t=texto)

    def registrar_traza(self, id_consulta, paso, tipo, detalle):
        import json
        self.con.run("INSERT INTO traza_inferencia (id_consulta, paso, tipo, detalle) "
                     "VALUES (:c, :p, CAST(:t AS t_tipo_traza), CAST(:d AS JSONB))",
                     c=id_consulta, p=paso, t=tipo, d=json.dumps(detalle, ensure_ascii=False))

    def traza(self, id_consulta):
        return self._dicts("SELECT paso, tipo::TEXT AS tipo, detalle, fecha FROM traza_inferencia "
                           "WHERE id_consulta = :c AND tipo <> 'validacion_experto' ORDER BY id_traza", c=id_consulta)

    def guardar_diagnostico(self, id_consulta, ranking):
        for pos, fila in enumerate(ranking, start=1):
            self.con.run("INSERT INTO diagnostico_hipotesis (id_consulta, posicion, id_hipotesis, "
                         "probabilidad) VALUES (:c, :p, :h, :v)",
                         c=id_consulta, p=pos, h=fila["id_hipotesis"],
                         v=round(fila["probabilidad"], 5))
        self.con.run("UPDATE consulta SET estado = 'terminada', fecha_fin = CURRENT_TIMESTAMP "
                     "WHERE id_consulta = :c", c=id_consulta)

    def diagnostico(self, id_consulta):
        return self._dicts("SELECT d.posicion, d.probabilidad, h.codigo FROM diagnostico_hipotesis d "
                           "JOIN hipotesis h ON h.id_hipotesis = d.id_hipotesis "
                           "WHERE d.id_consulta = :c ORDER BY d.posicion", c=id_consulta)

    def listar_consultas(self, limite=50):
        """La seguridad por fila decide qué ve cada rol."""
        return self._dicts(
            "SELECT c.id_consulta, row_number() OVER (PARTITION BY c.id_usuario ORDER BY c.id_consulta) AS numero, "
            "c.estado::TEXT AS estado, c.fecha_inicio, c.fecha_fin, "
            "c.verificacion_formal, u.alias, "
            "(SELECT h.codigo FROM diagnostico_hipotesis d JOIN hipotesis h "
            "   ON h.id_hipotesis = d.id_hipotesis "
            "  WHERE d.id_consulta = c.id_consulta AND d.posicion = 1) AS hipotesis, "
            "(SELECT d.probabilidad FROM diagnostico_hipotesis d "
            "  WHERE d.id_consulta = c.id_consulta AND d.posicion = 1) AS probabilidad "
            "FROM consulta c JOIN usuario u ON u.id_usuario = c.id_usuario "
            "ORDER BY c.fecha_inicio DESC LIMIT :l", l=limite)

    def explicacion_ia(self, id_consulta):
        f = self._q("SELECT detalle->>'explicacion_ia' FROM traza_inferencia "
                    "WHERE id_consulta = :c AND tipo = 'conclusion' ORDER BY id_traza DESC LIMIT 1",
                    c=id_consulta)
        return f[0][0] if f else None

    def registrar_verificacion(self, id_consulta, resultado, detalle):
        paso = self._q("SELECT COALESCE(MAX(paso), 0) FROM consulta_hecho WHERE id_consulta = :c",
                       c=id_consulta)[0][0]
        self.con.run("UPDATE consulta SET verificacion_formal = :r, "
                     "fecha_verificacion = CURRENT_TIMESTAMP WHERE id_consulta = :c",
                     r=resultado[:30], c=id_consulta)
        self.registrar_traza(id_consulta, paso, "verificacion_formal",
                             {"resultado": resultado, **detalle})

    # ------------------------------------------------------------ experto
    # Opinión del experto: una fila de la traza por experto (tipo validacion_experto)
    def validar_diagnostico(self, id_consulta, id_experto, de_acuerdo, comentario):
        import json
        paso = self._q("SELECT COALESCE(MAX(paso), 0) FROM consulta_hecho WHERE id_consulta = :c",
                       c=id_consulta)[0][0]
        detalle = json.dumps({"id_experto": id_experto, "de_acuerdo": bool(de_acuerdo),
                              "comentario": comentario}, ensure_ascii=False)
        self.con.run("INSERT INTO traza_inferencia (id_consulta, paso, tipo, detalle) "
                     "VALUES (:c, :p, 'validacion_experto', CAST(:d AS JSONB)) "
                     "ON CONFLICT (id_consulta, ((detalle->>'id_experto')::INT)) "
                     "WHERE tipo = 'validacion_experto' "
                     "DO UPDATE SET detalle = EXCLUDED.detalle, fecha = CURRENT_TIMESTAMP",
                     c=id_consulta, p=paso, d=detalle)

    def validaciones(self, id_consulta):
        return self._dicts("SELECT u.alias AS experto, (t.detalle->>'de_acuerdo')::BOOLEAN AS de_acuerdo, "
                           "t.detalle->>'comentario' AS comentario, t.fecha "
                           "FROM traza_inferencia t "
                           "JOIN usuario u ON u.id_usuario = (t.detalle->>'id_experto')::INT "
                           "WHERE t.id_consulta = :c AND t.tipo = 'validacion_experto' "
                           "ORDER BY t.fecha", c=id_consulta)

    def metricas(self):
        """Indicadores del sistema (la seguridad por fila decide qué consultas cuentan)."""
        f = self._dicts(
            "SELECT count(*) AS consultas, "
            "count(*) FILTER (WHERE estado = 'terminada') AS terminadas, "
            "count(*) FILTER (WHERE estado = 'en_curso') AS en_curso, "
            "count(*) FILTER (WHERE estado = 'abandonada') AS descartadas, "
            "count(*) FILTER (WHERE estado = 'terminada' AND verificacion_formal IS NULL) AS pendientes_verificar, "
            "count(*) FILTER (WHERE verificacion_formal IS NOT NULL) AS verificadas, "
            "count(*) FILTER (WHERE verificacion_formal = 'VALID') AS verificadas_valid, "
            "count(*) FILTER (WHERE verificacion_formal = 'INVALID') AS verificadas_invalid "
            "FROM consulta")[0]
        o = self._dicts(
            "SELECT count(*) AS validaciones, "
            "count(*) FILTER (WHERE (detalle->>'de_acuerdo')::BOOLEAN) AS de_acuerdo, "
            "count(DISTINCT id_consulta) AS consultas_con_opinion "
            "FROM traza_inferencia WHERE tipo = 'validacion_experto'")[0]
        f.update(o)
        f["concordancia_experto"] = (round(f["de_acuerdo"] / f["validaciones"], 4)
                                     if f["validaciones"] else None)
        f["por_hipotesis"] = self._dicts(
            "SELECT h.codigo, h.nivel::TEXT AS nivel, h.equipo::TEXT AS equipo, h.objetivo::TEXT AS objetivo, "
            "h.fase::TEXT AS fase, h.dias_semana::TEXT AS dias_semana, h.actividad::TEXT AS actividad, "
            "count(*) AS veces FROM diagnostico_hipotesis d "
            "JOIN hipotesis h ON h.id_hipotesis = d.id_hipotesis WHERE d.posicion = 1 "
            "GROUP BY h.codigo, h.nivel, h.equipo, h.objetivo, h.fase, h.dias_semana, h.actividad "
            "ORDER BY veces DESC, h.codigo")
        return f

    def frases_escritas(self):
        """Frases que el sistema entendió con ayuda de Lex o Nova, o que la persona confirmó.
        Sale de la traza, que registra quién interpretó cada respuesta escrita."""
        return self._dicts(
            "SELECT t.detalle->>'texto_usuario' AS frase, he.codigo AS hecho, "
            "t.detalle->'hecho'->>'pregunta' AS pregunta, t.detalle->'interpretacion'->>'metodo' AS metodo, "
            "r.texto_opcion, r.sinonimos, he.valor, count(*) AS veces, max(t.fecha) AS ultima "
            "FROM traza_inferencia t "
            "JOIN hechos he ON he.codigo = t.detalle->'hecho'->>'hecho' "
            "JOIN respuesta_pregunta r ON r.id_hecho = he.id_hecho "
            "WHERE t.tipo = 'respuesta' AND t.detalle->>'origen' = 'texto_libre' "
            "AND t.detalle->'interpretacion'->>'metodo' IN ('lex', 'nova', 'confirmada') "
            "GROUP BY 1, 2, 3, 4, 5, 6, 7 ORDER BY veces DESC, ultima DESC LIMIT 200")

    # ------------------------------------------------------------ ingeniero del conocimiento
    # Todo cambio pasa por los procedimientos almacenados, que validan la coherencia.
    def actualizar_pregunta(self, codigo, texto, ayuda, peso_base, aplicar_a_granulos):
        self.con.run("CALL sp_actualizar_pregunta(:c, :t, :a, CAST(:p AS NUMERIC), :g)",
                     c=codigo, t=texto, a=ayuda, p=str(peso_base), g=bool(aplicar_a_granulos))

    def registrar_hecho_conocimiento(self, codigo, pregunta, valor, texto_opcion, sinonimos, orden,
                                     descripcion):
        self.con.run("CALL sp_registrar_hecho(:c, :p, :v, :t, CAST(:s AS TEXT[]), :o, :d)",
                     c=codigo, p=pregunta, v=valor, t=texto_opcion, s=list(sinonimos or []),
                     o=int(orden), d=descripcion)

    def descripcion_hecho(self, codigo_pregunta, valor):
        f = self._q("SELECT atributo FROM preguntas WHERE codigo = :c", c=codigo_pregunta)
        return f"{f[0][0]} = {str(valor).strip()}" if f else None

    def eliminar_hecho(self, codigo):
        self.con.run("CALL sp_eliminar_hecho(:c)", c=codigo)

    def registrar_hipotesis(self, codigo, nivel, equipo, objetivo, fase, dias, actividad,
                            descripcion, probabilidad_previa):
        self.con.run("CALL sp_registrar_hipotesis(:c, CAST(:n AS t_nivel), CAST(:e AS t_equipo), "
                     "CAST(:o AS t_objetivo), CAST(:f AS t_fase), CAST(:d AS t_dias_semana), "
                     "CAST(:a AS t_actividad), :t, CAST(:p AS NUMERIC))",
                     c=codigo, n=nivel, e=equipo, o=objetivo, f=fase, d=dias, a=actividad,
                     t=descripcion, p=str(probabilidad_previa))

    def eliminar_hipotesis(self, codigo):
        self.con.run("CALL sp_eliminar_hipotesis(:c)", c=codigo)

    def asociar_granulo(self, hecho, hipotesis, peso):
        self.con.run("CALL sp_asociar_hecho_hipotesis(:h, :p, CAST(:w AS NUMERIC))",
                     h=hecho, p=hipotesis, w=None if peso is None else str(peso))

    def desasociar_granulo(self, hecho, hipotesis):
        self.con.run("CALL sp_desasociar_hecho_hipotesis(:h, :p)", h=hecho, p=hipotesis)

    # ------------------------------------------------------------ administrador
    def listar_usuarios(self):
        return self._dicts("SELECT id_usuario, cognito_sub, nombre, alias, correo, rol::TEXT AS rol, "
                           "activo, fecha_registro FROM usuario ORDER BY rol, alias")

    def usuario_por_id(self, id_usuario):
        f = self._dicts("SELECT id_usuario, cognito_sub, nombre, alias, correo, rol::TEXT AS rol, "
                        "activo FROM usuario WHERE id_usuario = :u", u=id_usuario)
        return f[0] if f else None

    def crear_usuario(self, sub, nombre, alias, correo, rol):
        """Devuelve (id_usuario, alias asignado)."""
        return self._con_alias_libre(alias, lambda a: self._q(
            "INSERT INTO usuario (cognito_sub, nombre, alias, correo, rol) "
            "VALUES (:s, :n, :a, :c, CAST(:r AS t_rol_sistema)) RETURNING id_usuario",
            s=sub, n=nombre, a=a, c=correo, r=rol)[0][0])

    def cambiar_rol(self, id_usuario, rol):
        self.con.run("UPDATE usuario SET rol = CAST(:r AS t_rol_sistema) WHERE id_usuario = :u",
                     r=rol, u=id_usuario)

    def cambiar_estado(self, id_usuario, activo):
        self.con.run("UPDATE usuario SET activo = :a WHERE id_usuario = :u", a=bool(activo),
                     u=id_usuario)

    def auditoria(self, limite=100):
        return self._dicts("SELECT id_auditoria, fecha, usuario_app, rol_bd, tabla, accion, antes, "
                           "despues FROM auditoria ORDER BY fecha DESC LIMIT :l", l=limite)

    def validar_base(self):
        return self._dicts("SELECT * FROM fn_validar_base()")

    def despertar(self):
        return self._q("SELECT 1")[0][0] == 1
