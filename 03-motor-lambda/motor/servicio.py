"""CAPA DE SERVICIO · Entrada de la Lambda: identidad, permisos por rol, rutas y casos de uso."""

import json
import re
import time
import traceback
import unicodedata

from datos import ROLES_BD, BaseIniciando, Repositorio, abrir_conexion
from identidad import GRUPOS, GestorCuentas
from negocio import ErrorNegocio, MotorInferencia, consulta_pendiente
import interprete
from servicios_ia import ClasificadorNova, InterpreteLex, RedactorNova, VerificadorFormal


# ---------------------------------------------------------------- servicios de IA y matriz de permisos
class ServiciosIA:
    """Agrupa los adaptadores externos; las pruebas locales los reemplazan por dobles."""
    def __init__(self):
        self.interprete = InterpreteLex()
        self.clasificador = ClasificadorNova()
        self.redactor = RedactorNova()
        self.verificador = VerificadorFormal()
        self.cuentas = GestorCuentas()


IA = ServiciosIA()

TODOS = {"usuario_final", "experto", "ingeniero_conocimiento", "administrador"}
SUPERVISION = {"experto", "ingeniero_conocimiento", "administrador"}

# Acción -> roles de la aplicación que pueden ejecutarla (matriz de permisos)
PERMISOS = {
    "perfil": TODOS,
    "iniciar_consulta": {"usuario_final"},
    "descartar_consulta": {"usuario_final"},
    "responder": {"usuario_final"},
    "responder_texto": {"usuario_final"},
    "obtener_consulta": TODOS,          # la seguridad por fila decide qué consulta ve cada uno
    "listar_consultas": TODOS,
    "verificar_formal": {"experto", "ingeniero_conocimiento"},
    "validar_diagnostico": {"experto"},
    "metricas": SUPERVISION,
    "base_conocimiento": SUPERVISION,
    # El experto ve la base en solo lectura; validarla y enseñarle frases nuevas es
    # trabajo del ingeniero, que es quien puede corregirla
    "validar_base": {"ingeniero_conocimiento"},
    "frases": {"ingeniero_conocimiento"},
    "actualizar_pregunta": {"ingeniero_conocimiento"},
    "registrar_hecho": {"ingeniero_conocimiento"},
    "eliminar_hecho": {"ingeniero_conocimiento"},
    "registrar_hipotesis": {"ingeniero_conocimiento"},
    "eliminar_hipotesis": {"ingeniero_conocimiento"},
    "asociar_granulo": {"ingeniero_conocimiento"},
    "desasociar_granulo": {"ingeniero_conocimiento"},
    "listar_usuarios": {"administrador"},
    "crear_usuario": {"administrador"},
    "cambiar_rol": {"administrador"},
    "cambiar_estado": {"administrador"},
    "auditoria": {"administrador"},
}

# Rutas HTTP -> acción. "POST /despertar" es la única ruta pública (sin token).
RUTAS = [
    ("POST", "/despertar", "despertar"),
    ("GET", "/perfil", "perfil"),
    ("POST", "/consultas", "iniciar_consulta"),
    ("GET", "/consultas", "listar_consultas"),
    ("GET", "/consultas/{id}", "obtener_consulta"),
    ("POST", "/consultas/{id}/descartar", "descartar_consulta"),
    ("POST", "/consultas/{id}/respuestas", "responder"),
    ("POST", "/consultas/{id}/mensajes", "responder_texto"),
    ("POST", "/consultas/{id}/verificacion", "verificar_formal"),
    ("POST", "/consultas/{id}/validacion", "validar_diagnostico"),
    ("GET", "/metricas", "metricas"),
    ("GET", "/base-conocimiento", "base_conocimiento"),
    ("GET", "/base-conocimiento/validacion", "validar_base"),
    ("GET", "/base-conocimiento/frases", "frases"),
    ("PUT", "/base-conocimiento/preguntas/{codigo}", "actualizar_pregunta"),
    ("PUT", "/base-conocimiento/hechos/{codigo}", "registrar_hecho"),
    ("DELETE", "/base-conocimiento/hechos/{codigo}", "eliminar_hecho"),
    ("PUT", "/base-conocimiento/hipotesis/{codigo}", "registrar_hipotesis"),
    ("DELETE", "/base-conocimiento/hipotesis/{codigo}", "eliminar_hipotesis"),
    ("PUT", "/base-conocimiento/granulos", "asociar_granulo"),
    ("DELETE", "/base-conocimiento/granulos/{hecho}/{hipotesis}", "desasociar_granulo"),
    ("GET", "/usuarios", "listar_usuarios"),
    ("POST", "/usuarios", "crear_usuario"),
    ("PUT", "/usuarios/{id}/rol", "cambiar_rol"),
    ("PUT", "/usuarios/{id}/estado", "cambiar_estado"),
    ("GET", "/auditoria", "auditoria"),
]
_PATRONES = [(m, re.compile("^" + re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", r) + "/?$"), a)
             for m, r, a in RUTAS]

_conexion = None


# ---------------------------------------------------------------- entrada HTTP: conexión, respuesta y enrutamiento
def _repo():
    """Reutiliza la conexión mientras la Lambda está activa; la reabre si se cayó."""
    global _conexion
    if _conexion is not None:
        try:
            _conexion.run("SELECT 1")
        except Exception:
            _conexion = None
    if _conexion is None:
        _conexion = abrir_conexion()
    return Repositorio(_conexion)


def _respuesta(estado, cuerpo):
    return {"statusCode": estado,
            "headers": {"Content-Type": "application/json; charset=utf-8",
                        "Cache-Control": "no-store"},
            "body": json.dumps(cuerpo, ensure_ascii=False, default=str)}


def _enrutar(metodo, ruta):
    for m, patron, accion in _PATRONES:
        coincide = patron.match(ruta)
        if coincide and m == metodo:
            return accion, coincide.groupdict()
    return None, {}


def _leer_evento(event):
    """Normaliza los dos formatos -> (acción, identidad, parámetros)."""
    if "requestContext" in event and "http" in event["requestContext"]:   # API Gateway
        http = event["requestContext"]["http"]
        accion, params = _enrutar(http["method"], event.get("rawPath") or http.get("path", ""))
        claims = (event["requestContext"].get("authorizer", {}).get("jwt", {})
                  .get("claims", {}))
        grupos = claims.get("cognito:groups", "")
        if isinstance(grupos, str):
            grupos = [g for g in grupos.strip("[]").replace(",", " ").split() if g]
        grupos = [g for g in grupos if g in GRUPOS]
        identidad = {"sub": claims.get("sub"), "correo": claims.get("email"),
                     "nombre": claims.get("name") or (claims.get("email") or "").split("@")[0],
                     "grupo": grupos[0] if grupos else "usuario_final"}
        if event.get("body"):
            try:
                cuerpo = json.loads(event["body"])
            except ValueError:
                raise ErrorNegocio("El cuerpo de la petición no es JSON válido")
            if not isinstance(cuerpo, dict):
                raise ErrorNegocio("El cuerpo de la petición debe ser un objeto JSON")
            params = {**cuerpo, **params}           # los parámetros de la ruta mandan
        if http["method"] == "GET":
            params = {**(event.get("queryStringParameters") or {}), **params}
        return accion, identidad, params
    return event.get("accion"), event.get("identidad") or {}, event.get("parametros") or {}


# ---------------------------------------------------------------- identidad y validación de parámetros
def alias_desde_nombre(nombre, correo):
    """Alias legible desde el nombre de registro: «Juan Pérez» -> juan.p."""
    t = unicodedata.normalize("NFD", str(nombre or "").lower())
    palabras = re.findall(r"[a-z0-9]+", "".join(c for c in t if unicodedata.category(c) != "Mn"))
    if not palabras:
        palabras = re.findall(r"[a-z0-9]+", str(correo).split("@")[0].lower()) or ["usuario"]
    alias = palabras[0] + (f".{palabras[1][0]}" if len(palabras) > 1 else "")
    return alias[:26]


def _resolver_usuario(repo, identidad):
    """Busca al usuario por su identificador de Cognito. Si es la primera vez
    que entra un usuario final, crea su perfil. Su rol en la BD manda."""
    sub = identidad.get("sub")
    if not sub:
        raise ErrorNegocio("Petición sin identidad", 401)
    usuario = repo.usuario_por_sub(sub)
    if usuario is None:
        if identidad.get("grupo", "usuario_final") != "usuario_final":
            raise ErrorNegocio("El perfil no está registrado; contacte al administrador", 403)
        correo = identidad.get("correo") or f"{sub[:12]}@sin-correo.test"
        nombre = (identidad.get("nombre") or correo.split("@")[0])[:120]
        repo.crear_usuario_final(sub, nombre, alias_desde_nombre(nombre, correo), correo)
        usuario = repo.usuario_por_sub(sub)
    if not usuario["activo"]:
        raise ErrorNegocio("La cuenta está desactivada", 403)
    if identidad.get("grupo") and identidad["grupo"] != usuario["rol"]:
        raise ErrorNegocio("El rol de la sesión no coincide con el registrado; "
                           "vuelva a iniciar sesión", 403)
    return usuario


def _requerido(params, *campos):
    faltan = [c for c in campos if params.get(c) in (None, "")]
    if faltan:
        raise ErrorNegocio("Faltan datos: " + ", ".join(faltan))


def _entero(valor, nombre):
    try:
        return int(valor)
    except (TypeError, ValueError):
        raise ErrorNegocio(f"{nombre} debe ser un número entero")


# ---------------------------------------------------------------- casos de uso por rol
def ejecutar(accion, identidad, params):
    if accion == "despertar":                       # ruta pública: solo despierta la base
        return {"listo": _repo().despertar()}
    if accion not in PERMISOS:
        raise ErrorNegocio("Ruta no encontrada", 404)
    repo = _repo()
    # 1) Identificación con el rol mínimo (solo puede leer o crear su propio perfil)
    with repo.transaccion("rol_usuario", cognito_sub=identidad.get("sub"),
                          correo=identidad.get("correo")):
        usuario = _resolver_usuario(repo, identidad)
    if usuario["rol"] not in PERMISOS[accion]:
        raise ErrorNegocio("Su rol no permite esta acción", 403)

    # 2) Caso de uso con el rol de base de datos del usuario
    if accion in ("crear_usuario", "cambiar_rol", "cambiar_estado"):
        return _gestion_usuarios(repo, usuario, accion, params)
    with repo.transaccion(ROLES_BD[usuario["rol"]], usuario["id_usuario"],
                          usuario["correo"], identidad.get("sub")):
        return _caso_de_uso(repo, usuario, accion, params)


def _caso_de_uso(repo, usuario, accion, params):
    if accion == "perfil":
        return {k: usuario[k] for k in ("id_usuario", "nombre", "alias", "correo", "rol")}
    if accion == "listar_consultas":
        if usuario["rol"] == "usuario_final":
            # Antes de mostrarle su lista, se descarta su consulta abierta si quedó inactiva
            consulta_pendiente(repo, usuario["id_usuario"])
        return {"consultas": repo.listar_consultas()}
    if accion == "metricas":
        return repo.metricas()
    if accion == "validar_base":
        return {"validacion": repo.validar_base()}
    if accion == "frases":
        return {"frases": _frases_por_revisar(repo)}
    if accion == "listar_usuarios":
        return {"usuarios": repo.listar_usuarios()}
    if accion == "auditoria":
        return {"auditoria": repo.auditoria(min(_entero(params.get("limite", 100), "limite"), 500))}
    if accion in ("actualizar_pregunta", "registrar_hecho", "eliminar_hecho", "registrar_hipotesis",
                  "eliminar_hipotesis", "asociar_granulo", "desasociar_granulo"):
        _gestion_conocimiento(repo, accion, params)
        return {"ok": True, "accion": accion,
                "validacion": [v for v in repo.validar_base()
                               if v["resultado"] not in ("OK", "INFO")]}

    motor = MotorInferencia(repo, redactor=IA.redactor)
    if accion == "base_conocimiento":
        return {"preguntas": [{**p, "opciones": [
                    {k: o[k] for k in ("id_respuesta", "codigo_hecho", "valor",
                                       "texto_opcion", "sinonimos", "orden")}
                    for o in motor.opciones.get(p["id_pregunta"], [])]}
                    for p in motor.preguntas],
                "hipotesis": sorted(motor.hipotesis.values(), key=lambda h: h["codigo"]),
                "granulos": repo.granulos_completos()}
    if accion == "iniciar_consulta":
        return _con_mensaje(motor.iniciar(usuario["id_usuario"],
                                          params.get("descartar_pendiente") is True))
    id_consulta = _entero(params.get("id") or params.get("id_consulta"), "id de la consulta")
    if accion == "obtener_consulta":
        estado = motor.estado(id_consulta, incluir_traza=True)
        if usuario["rol"] != "usuario_final":
            estado["validaciones"] = repo.validaciones(id_consulta)
        return estado
    if accion == "descartar_consulta":
        return motor.descartar(id_consulta)
    if accion == "responder":
        _requerido(params, "id_respuesta")
        id_respuesta = _entero(params["id_respuesta"], "id_respuesta")
        texto = str(params.get("texto") or "").strip()[:300]
        if texto:
            # Respuesta escrita que el usuario confirmó ("¿Te refieres a...?") o que el
            # sistema propuso a partir de algo que escribió antes
            via = params.get("interpretacion") if params.get("interpretacion") in INTERPRETACIONES else "confirmada"
            return _con_mensaje(motor.responder(id_consulta, id_respuesta, "texto_libre", texto,
                                                {"metodo": via, "confirmada": True}))
        return _con_mensaje(motor.responder(id_consulta, id_respuesta, "boton"))
    if accion == "responder_texto":
        return _responder_texto(motor, id_consulta, str(params.get("texto") or ""))
    if accion == "verificar_formal":
        return _verificar_formal(motor, repo, id_consulta)
    if accion == "validar_diagnostico":
        if not isinstance(params.get("de_acuerdo"), bool):
            raise ErrorNegocio("de_acuerdo debe ser true o false")
        if motor.estado(id_consulta)["estado"] != "terminada":
            raise ErrorNegocio("Solo se pueden validar consultas terminadas", 409)
        repo.validar_diagnostico(id_consulta, usuario["id_usuario"], params["de_acuerdo"],
                                 (str(params.get("comentario") or "")[:500]) or None)
        return {"ok": True, "validaciones": repo.validaciones(id_consulta)}
    raise ErrorNegocio("Acción no implementada", 404)


def _gestion_conocimiento(repo, accion, p):
    """El ingeniero modifica el conocimiento solo a través de los procedimientos
    almacenados, que validan la coherencia y dejan rastro en la auditoría."""
    if accion == "actualizar_pregunta":
        _requerido(p, "codigo", "texto", "peso_base")
        repo.actualizar_pregunta(p["codigo"], p["texto"], p.get("ayuda"), p["peso_base"],
                                 bool(p.get("aplicar_a_granulos")))
    elif accion == "registrar_hecho":
        _requerido(p, "codigo", "pregunta", "valor", "texto_opcion", "orden")
        sinonimos = p.get("sinonimos") or []
        if not isinstance(sinonimos, list):
            raise ErrorNegocio("sinonimos debe ser una lista")
        # La página no envía la descripción: se conserva la forma «atributo = valor»
        descripcion = p.get("descripcion") or repo.descripcion_hecho(p["pregunta"], p["valor"])
        repo.registrar_hecho_conocimiento(p["codigo"], p["pregunta"], p["valor"],
                                          p["texto_opcion"],
                             [str(s) for s in sinonimos], _entero(p["orden"], "orden"),
                             descripcion)
    elif accion == "eliminar_hecho":
        repo.eliminar_hecho(p["codigo"])
    elif accion == "registrar_hipotesis":
        _requerido(p, "codigo", "nivel", "equipo", "descripcion_rutina")
        repo.registrar_hipotesis(p["codigo"], p["nivel"], p["equipo"], p.get("objetivo"),
                                 p.get("fase"), p.get("dias_semana"), p.get("actividad"),
                                 p["descripcion_rutina"], p.get("probabilidad_previa") or 1)
    elif accion == "eliminar_hipotesis":
        repo.eliminar_hipotesis(p["codigo"])
    elif accion == "asociar_granulo":
        _requerido(p, "hecho", "hipotesis")
        repo.asociar_granulo(p["hecho"], p["hipotesis"], p.get("peso"))
    elif accion == "desasociar_granulo":
        repo.desasociar_granulo(p["hecho"], p["hipotesis"])


def _gestion_usuarios(repo, admin, accion, p):
    """Cambios de cuentas: primero la base (valida reglas y audita), luego Cognito.
    Si Cognito falla, la transacción de la base se deshace."""
    with repo.transaccion("rol_administrador", admin["id_usuario"], admin["correo"]):
        if accion == "crear_usuario":
            _requerido(p, "correo", "nombre", "rol")
            if p["rol"] not in GRUPOS:
                raise ErrorNegocio("Rol no válido")
            correo = str(p["correo"]).strip().lower()
            if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", correo):
                raise ErrorNegocio("Correo no válido")
            alias = (alias_desde_nombre(p["alias"], "") if p.get("alias")
                     else alias_desde_nombre(str(p["nombre"]), correo))
            sub, temporal = IA.cuentas.crear(correo, str(p["nombre"])[:120], p["rol"])
            try:
                id_usuario, alias = repo.crear_usuario(sub, str(p["nombre"])[:120], alias, correo, p["rol"])
            except Exception:
                IA.cuentas.eliminar(correo)           # compensación: no deja cuentas huérfanas
                raise
            return {"ok": True, "id_usuario": id_usuario, "correo": correo, "alias": alias,
                    "rol": p["rol"], "contrasena_temporal": temporal,
                    "nota": "Debe cambiarla en su primer inicio de sesión"}
        id_usuario = _entero(p.get("id"), "id del usuario")
        objetivo = repo.usuario_por_id(id_usuario)
        if objetivo is None:
            raise ErrorNegocio("El usuario no existe", 404)
        if accion == "cambiar_rol":
            _requerido(p, "rol")
            if p["rol"] not in GRUPOS:
                raise ErrorNegocio("Rol no válido")
            repo.cambiar_rol(id_usuario, p["rol"])
            IA.cuentas.cambiar_grupo(objetivo["correo"], objetivo["rol"], p["rol"])
        else:
            if not isinstance(p.get("activo"), bool):
                raise ErrorNegocio("activo debe ser true o false")
            repo.cambiar_estado(id_usuario, p["activo"])
            IA.cuentas.cambiar_estado(objetivo["correo"], p["activo"])
        return {"ok": True, "usuario": repo.usuario_por_id(id_usuario)}


# ---------------------------------------------------------------- respuestas escritas (sinónimos, Lex, Nova)
def _con_mensaje(estado):
    """Agrega la frase de transición redactada por Nova (si está disponible)."""
    if estado.get("estado") == "en_curso" and estado.get("pregunta"):
        ultimo = estado["hechos"][-1] if estado.get("hechos") else None
        estado["mensaje"] = IA.redactor.mensaje_pregunta(ultimo, estado["pregunta"])
    return estado


INTERPRETACIONES = {"sinonimos", "lex", "nova", "sugerencia", "confirmada"}
UMBRAL_ACEPTAR, UMBRAL_CONFIRMAR, UMBRAL_SUGERIR = 0.8, 0.5, 0.75


def _responder_texto(motor, id_consulta, texto):
    """Interpreta una respuesta escrita: sinónimos, luego Lex, luego Nova."""
    texto = texto.strip()
    if not texto:
        raise ErrorNegocio("El mensaje está vacío")
    if len(texto) > 300:
        raise ErrorNegocio("El mensaje es demasiado largo (máximo 300 caracteres)")
    pregunta = motor.pregunta_actual(id_consulta)
    if pregunta is None:
        raise ErrorNegocio("La consulta no tiene preguntas pendientes", 409)
    opciones = motor.opciones.get(pregunta["id_pregunta"], [])
    pendientes = motor.preguntas_pendientes(id_consulta, excepto=pregunta["id_pregunta"])
    pasos = []
    # Opciones que la persona negó («no domino la técnica» niega «Sí, los domino»): ningún
    # servicio puede elegirlas, y con una negación en el texto la opción afirmativa se confirma
    negadas = interprete.negadas(texto, opciones)
    hay_negacion = interprete.tiene_negacion(texto)

    def contradice(opcion):
        return opcion["codigo_hecho"] in negadas or (hay_negacion and interprete.es_afirmativa(opcion))

    # 1) Sinónimos y textos de la base de conocimiento
    elegida, interpretacion = None, None
    r = interprete.interpretar(texto, opciones)
    if r and contradice(r["opcion"]) and r["confianza"] < 1:
        r = None            # «claro que no»: afirma y niega a la vez; mejor que lo resuelva Nova
    if r:
        elegida = r["opcion"]
        interpretacion = {"metodo": "sinonimos", "motivo": r["motivo"], "confianza": r["confianza"]}
    pasos.append({"metodo": "sinonimos", "resultado": elegida["codigo_hecho"] if elegida else None})

    # 2) Amazon Lex
    if elegida is None:
        codigo, detalle = IA.interprete.interpretar(id_consulta, pregunta["atributo"], texto)
        if codigo:
            elegida = next((o for o in opciones if o["codigo_hecho"] == codigo), None)
            if elegida and contradice(elegida):
                pasos.append({"metodo": "lex", "resultado": codigo, "descartado": "contradice una negación del texto"})
                elegida = None
            elif elegida:
                interpretacion = {"metodo": "lex", "motivo": "reconocido por Amazon Lex", "detalle": detalle}
        if not pasos or pasos[-1]["metodo"] != "lex":
            pasos.append({"metodo": "lex", "resultado": codigo})

    # 3) Bedrock Nova, solo con las opciones que existen
    nova = None
    if elegida is None:
        nova = IA.clasificador.clasificar(texto, pregunta, opciones, pendientes)
        if nova and nova["codigo"] and nova["codigo"] in negadas:
            nova = {**nova, "codigo": None, "descartado": "contradice una negación del texto"}
        if nova and nova["codigo"]:
            candidata = next(o for o in opciones if o["codigo_hecho"] == nova["codigo"])
            if nova["confianza"] >= UMBRAL_ACEPTAR and not contradice(candidata):
                elegida = candidata
                interpretacion = {"metodo": "nova", "motivo": nova["motivo"], "confianza": nova["confianza"]}
            elif nova["confianza"] >= UMBRAL_CONFIRMAR:
                estado = motor.estado(id_consulta)
                estado.update({
                    "confirmar": {"id_respuesta": candidata["id_respuesta"], "opcion": candidata["texto_opcion"],
                                  "texto": texto, "motivo": nova["motivo"]},
                    "mensaje": f"¿Te refieres a «{candidata['texto_opcion']}»?",
                    "sugerencias": _sugerencias(texto, pendientes, nova)})
                return estado
        pasos.append({"metodo": "nova", "resultado": nova["codigo"] if nova else None,
                      "confianza": nova["confianza"] if nova else None,
                      **({"descartado": nova["descartado"]} if nova and nova.get("descartado") else {})})

    if elegida is None:
        estado = motor.estado(id_consulta)
        ejemplos = [o["texto_opcion"] for o in opciones][:3]
        estado.update({"no_entendido": True, "interpretacion": {"pasos": pasos},
                       "mensaje": f"No logré relacionar «{texto}» con las opciones de esta pregunta. "
                                  f"Elige una o escríbelo de otra forma, por ejemplo: {', '.join('«' + e + '»' for e in ejemplos)}."})
        return estado

    interpretacion["pasos"] = pasos
    # Un mensaje largo puede traer datos de otras preguntas ("llevo 3 años en el gym y quiero
    # ganar fuerza"): si aún no se consultó a Nova, se le pide solo esa extracción
    if nova is None and pendientes and len(texto.split()) >= 6:
        nova = IA.clasificador.clasificar(texto, pregunta, opciones, pendientes)
    sugerencias = _sugerencias(texto, pendientes, nova)
    estado = _con_mensaje(motor.responder(id_consulta, elegida["id_respuesta"], "texto_libre", texto, interpretacion))
    estado["interpretacion"] = interpretacion
    estado["sugerencias"] = sugerencias
    return estado


def _sugerencias(texto, pendientes, nova=None):
    """Datos que el usuario adelantó para preguntas futuras: {atributo: {id_respuesta, opcion}}.
    No se registran solos: la interfaz los propone cuando el motor llegue a esa pregunta."""
    salida = {}
    for atributo, r in interprete.detectar_otros(texto, pendientes).items():
        salida[atributo] = {"id_respuesta": r["opcion"]["id_respuesta"], "opcion": r["opcion"]["texto_opcion"]}
    if nova:
        por_atributo = {p["atributo"]: ops for p, ops in pendientes}
        for atributo, (codigo, confianza) in nova["otros"].items():
            if atributo in salida or confianza < UMBRAL_SUGERIR:
                continue
            o = next((o for o in por_atributo.get(atributo, []) if o["codigo_hecho"] == codigo), None)
            if o:
                salida[atributo] = {"id_respuesta": o["id_respuesta"], "opcion": o["texto_opcion"]}
    return salida


def _frases_por_revisar(repo):
    """Frases escritas que todavía no son sinónimo de su opción: candidatas para que el
    ingeniero las agregue a la base y el sistema las reconozca sin ayuda la próxima vez."""
    # Una frase deja de estar pendiente cuando ya es sinónimo de CUALQUIER opción de su
    # pregunta: así sale de la lista también la que el ingeniero asignó a otra opción
    # porque el sistema la había entendido mal («no domino la técnica» -> No)
    codigo_pregunta = {p["id_pregunta"]: p["codigo"] for p in repo.preguntas()}
    conocidas_por_pregunta = {}
    for o in repo.opciones():
        conocidas_por_pregunta.setdefault(codigo_pregunta[o["id_pregunta"]], set()).update(interprete.frases(o))
    vistas = {}
    for f in repo.frases_escritas():
        conocidas = conocidas_por_pregunta.get(f["pregunta"], set())
        clave = (interprete.normalizar(f["frase"]), f["hecho"])
        # Un sinónimo es una expresión corta; un mensaje largo suele mezclar varios datos
        if clave[0] in conocidas or not clave[0] or len(clave[0].split()) > 6:
            continue
        if clave in vistas:
            vistas[clave]["veces"] += f["veces"]
        else:
            vistas[clave] = {"frase": f["frase"].strip()[:120], "hecho": f["hecho"], "pregunta": f["pregunta"],
                             "metodo": f["metodo"],
                             "opcion": f["texto_opcion"], "veces": f["veces"], "ultima": f["ultima"]}
    return sorted(vistas.values(), key=lambda x: (-x["veces"], x["frase"]))


# Resultados lógicos de Automated Reasoning. Los demás (ERROR, TRANSLATION_AMBIGUOUS,
# NO_TRANSLATIONS, TOO_COMPLEX, SIN_HALLAZGOS...) son fallas técnicas y se pueden reintentar
VERIFICACION_DEFINITIVA = {"VALID", "INVALID", "SATISFIABLE", "IMPOSSIBLE"}


# ---------------------------------------------------------------- verificación formal y errores de la base
def _verificar_formal(motor, repo, id_consulta):
    """Automated Reasoning comprueba que la rutina concluida cumple las reglas del experto."""
    estado = motor.estado(id_consulta)
    if estado["estado"] != "terminada":
        raise ErrorNegocio("Solo se pueden verificar consultas terminadas", 409)
    if estado["verificacion_formal"] in VERIFICACION_DEFINITIVA:
        raise ErrorNegocio(f"Esta consulta ya se verificó ({estado['verificacion_formal']}). La verificación "
                           "es definitiva: sus respuestas y su rutina no cambian, así que daría lo mismo.", 409)
    codigo = estado["diagnostico"]["rutina"]["codigo"]
    resultado, detalle = IA.verificador.verificar(estado["hechos"], codigo)
    repo.registrar_verificacion(id_consulta, resultado, {**detalle, "hipotesis": codigo})
    return {"id_consulta": id_consulta, "hipotesis": codigo, "resultado": resultado,
            "detalle": detalle}


def _error_bd(e):
    """Traduce errores de PostgreSQL a respuestas HTTP con mensaje claro."""
    detalle = e.args[0] if e.args else {}
    if not isinstance(detalle, dict):
        return None
    codigo, mensaje = detalle.get("C"), detalle.get("M", "")
    if codigo == "42501" or "row-level security" in mensaje:
        return 403, "Acceso denegado por la base de datos"
    if codigo == "P0001":                      # RAISE EXCEPTION de los procedimientos
        return (409 if "ya está cerrada" in mensaje or "ya es definitiva" in mensaje else 400), mensaje
    if codigo == "23505" and "ux_consulta_abierta" in mensaje:
        return 409, "Ya tienes una consulta sin terminar. Continúala o descártala para empezar otra."
    if codigo == "23505":
        return 409, "Ya existe un registro con esos datos"
    if codigo in ("23503", "23514", "22P02"):
        return 400, "Datos no válidos para la base de conocimiento"
    return None


# ---------------------------------------------------------------- punto de entrada de la Lambda
def lambda_handler(event, context):
    inicio = time.time()
    # Consulta previa de CORS del navegador: no lleva token ni ejecuta nada.
    # API Gateway agrega las cabeceras CORS configuradas (solo el dominio de la web).
    if event.get("requestContext", {}).get("http", {}).get("method") == "OPTIONS":
        return {"statusCode": 204, "headers": {}, "body": ""}
    try:
        accion, identidad, params = _leer_evento(event)
        cuerpo = ejecutar(accion, identidad, params)
        cuerpo["_ms"] = int((time.time() - inicio) * 1000)
        return _respuesta(200, cuerpo)
    except ErrorNegocio as e:
        return _respuesta(e.estado, {"error": str(e), **e.datos})
    except BaseIniciando:
        return _respuesta(503, {"error": "El sistema se está iniciando. Intenta de nuevo en unos segundos.",
                                "reintentar": True})
    except Exception as e:
        traducido = _error_bd(e)
        if traducido:
            return _respuesta(traducido[0], {"error": traducido[1]})
        nombre = type(e).__name__
        if nombre in ("UsernameExistsException",):
            return _respuesta(409, {"error": "Ya existe una cuenta con ese correo"})
        if nombre in ("InvalidParameterException", "InvalidPasswordException"):
            return _respuesta(400, {"error": "Datos de la cuenta no válidos"})
        traceback.print_exc()
        return _respuesta(500, {"error": "Error interno del sistema experto"})
