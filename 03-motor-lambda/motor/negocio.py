"""CAPA DE NEGOCIO · Motor de inferencia probabilístico y granular.
Sin reglas en el código: todo sale de hechos_hipotesis, una pregunta a la vez."""

EPSILON = 1e-9


DIAS_INACTIVA = 7      # una consulta sin respuestas en este tiempo se descarta sola


# ---------------------------------------------------------------- reglas de la consulta abierta
def consulta_pendiente(repo, id_usuario):
    """Consulta en curso del perfil. Si lleva DIAS_INACTIVA días sin respuestas se
    descarta sola: la situación de la persona pudo cambiar y conviene empezar de nuevo."""
    abierta = repo.consulta_abierta(id_usuario)
    if abierta and abierta["dias_inactiva"] >= DIAS_INACTIVA:
        repo.descartar_consulta(abierta["id_consulta"])
        return None
    return abierta


class ErrorNegocio(Exception):
    def __init__(self, mensaje, estado=400, datos=None):
        super().__init__(mensaje)
        self.estado = estado
        self.datos = datos or {}


class MotorInferencia:
    def __init__(self, repo, redactor=None):
        """redactor (opcional): servicio que redacta la explicación final en lenguaje
        natural. Se inyecta desde la capa de servicio; el motor no depende de él."""
        self.repo = repo
        self.redactor = redactor
        self.preguntas = repo.preguntas()
        self.por_id_pregunta = {p["id_pregunta"]: p for p in self.preguntas}
        self.opciones = {}
        for o in repo.opciones():
            self.opciones.setdefault(o["id_pregunta"], []).append(o)
        self.hipotesis = {h["id_hipotesis"]: h for h in repo.hipotesis()}

    # ------------------------------------------------------------ cálculo
    @staticmethod
    def _factores(granulos, id_hecho):
        """Factor que recibe cada hipótesis si el usuario afirma id_hecho."""
        return {h: 1.0 if id_hecho in g else 1.0 - max(g.values()) for h, g in granulos.items()}

    def _acumular(self, hechos):
        acumulado = {}
        for h in hechos:
            granulos = self.repo.granulos_de_pregunta(h["id_pregunta"])
            for id_hip, f in self._factores(granulos, h["id_hecho"]).items():
                acumulado[id_hip] = acumulado.get(id_hip, 1.0) * f
        return acumulado

    def _puntajes(self, acumulado):
        return {h: float(d["probabilidad_previa"]) * acumulado.get(h, 1.0)
                for h, d in self.hipotesis.items()}

    @staticmethod
    def _lideres(puntajes):
        m = max(puntajes.values())
        return frozenset(h for h, v in puntajes.items() if v >= m * (1 - EPSILON))

    def ranking(self, acumulado, top=5):
        p = self._puntajes(acumulado)
        total = sum(p.values())
        filas = sorted(p.items(), key=lambda x: (-x[1], self.hipotesis[x[0]]["codigo"]))[:top]
        return [{**self._resumen_hipotesis(h), "id_hipotesis": h, "probabilidad": v / total}
                for h, v in filas]

    def _resumen_hipotesis(self, id_hip):
        h = self.hipotesis[id_hip]
        return {k: h[k] for k in ("codigo", "nivel", "equipo", "objetivo", "fase",
                                  "dias_semana", "actividad")}

    def _siguiente(self, hechos, acumulado):
        """Devuelve (pregunta o None, evaluación de cada pregunta para la traza)."""
        respondidas = {h["id_pregunta"] for h in hechos}
        actuales = self._lideres(self._puntajes(acumulado))
        evaluadas = []
        for p in self.preguntas:
            if p["id_pregunta"] in respondidas:
                continue
            granulos = self.repo.granulos_de_pregunta(p["id_pregunta"])
            cambia_con = []
            for o in self.opciones.get(p["id_pregunta"], []):
                f = self._factores(granulos, o["id_hecho"])
                hipotetico = {h: acumulado.get(h, 1.0) * f.get(h, 1.0) for h in self.hipotesis}
                if self._lideres(self._puntajes(hipotetico)) != actuales:
                    cambia_con.append(o["valor"])
            evaluadas.append({"pregunta": p["codigo"], "hipotesis_que_dependen": len(granulos),
                              "puede_cambiar_lider": bool(cambia_con),
                              "respuestas_decisivas": cambia_con})
            if cambia_con:
                return p, evaluadas
        return None, evaluadas

    def _pregunta_para_usuario(self, p):
        return {"id_pregunta": p["id_pregunta"], "codigo": p["codigo"], "texto": p["texto"],
                "ayuda": p["ayuda"], "atributo": p["atributo"],
                "ejemplos": [s for o in self.opciones.get(p["id_pregunta"], [])
                             for s in (o.get("sinonimos") or [])[:1]][:3],
                "opciones": [{"id_respuesta": o["id_respuesta"], "texto": o["texto_opcion"]}
                             for o in self.opciones.get(p["id_pregunta"], [])]}

    def _hecho_legible(self, id_pregunta, id_hecho):
        p = self.por_id_pregunta[id_pregunta]
        o = next(o for o in self.opciones[id_pregunta] if o["id_hecho"] == id_hecho)
        return {"pregunta": p["codigo"], "texto_pregunta": p["texto"], "atributo": p["atributo"],
                "respuesta": o["texto_opcion"], "valor": o["valor"], "hecho": o["codigo_hecho"]}

    # ------------------------------------------------------------ casos de uso
    def consulta_pendiente(self, id_usuario):
        return consulta_pendiente(self.repo, id_usuario)

    def iniciar(self, id_usuario, descartar_pendiente=False):
        """Una sola consulta abierta por perfil (la base también lo garantiza)."""
        abierta = self.consulta_pendiente(id_usuario)
        if abierta:
            if not descartar_pendiente:
                actual = self.repo.consulta(abierta["id_consulta"])
                raise ErrorNegocio(
                    "Ya tienes una consulta sin terminar. Continúala o descártala para empezar otra.", 409,
                    {"pendiente": {"id_consulta": abierta["id_consulta"], "numero": actual["numero"],
                                   "fecha_inicio": str(abierta["fecha_inicio"]),
                                   "respondidas": abierta["respondidas"]}})
            self.repo.descartar_consulta(abierta["id_consulta"])
        id_consulta = self.repo.crear_consulta(id_usuario)
        pregunta, evaluadas = self._siguiente([], {})
        self.repo.registrar_traza(id_consulta, 0, "seleccion_pregunta", {
            "consultas_granulares": self.repo.consultas_granulares,
            "evaluadas": evaluadas, "elegida": pregunta["codigo"] if pregunta else None})
        return self.estado(id_consulta)

    def responder(self, id_consulta, id_respuesta, origen="boton", texto_usuario=None, interpretacion=None):
        consulta = self.repo.consulta(id_consulta)
        if consulta is None:
            raise ErrorNegocio("La consulta no existe", 404)
        if consulta["estado"] != "en_curso":
            raise ErrorNegocio("La consulta ya terminó", 409)
        hechos = self.repo.hechos_de_consulta(id_consulta)
        acumulado = self._acumular(hechos)
        esperada, _ = self._siguiente(hechos, acumulado)
        if esperada is None:
            raise ErrorNegocio("La consulta no tiene preguntas pendientes", 409)
        opcion = next((o for o in self.opciones.get(esperada["id_pregunta"], [])
                       if o["id_respuesta"] == id_respuesta), None)
        return self._registrar_respuesta(id_consulta, hechos, acumulado, esperada, opcion,
                                         origen, texto_usuario, interpretacion)

    def descartar(self, id_consulta):
        consulta = self.repo.consulta(id_consulta)
        if consulta is None:
            raise ErrorNegocio("La consulta no existe", 404)
        if consulta["estado"] != "en_curso" or not self.repo.descartar_consulta(id_consulta):
            raise ErrorNegocio("Solo se puede descartar una consulta en curso", 409)
        return self.estado(id_consulta)

    def pregunta_actual(self, id_consulta):
        """Pregunta pendiente de una consulta en curso (o None)."""
        consulta = self.repo.consulta(id_consulta)
        if consulta is None:
            raise ErrorNegocio("La consulta no existe", 404)
        if consulta["estado"] != "en_curso":
            raise ErrorNegocio("La consulta ya terminó", 409)
        hechos = self.repo.hechos_de_consulta(id_consulta)
        pregunta, _ = self._siguiente(hechos, self._acumular(hechos))
        return pregunta

    def preguntas_pendientes(self, id_consulta, excepto=None):
        """Preguntas aún sin responder (con sus opciones), para detectar datos que el
        usuario adelanta al escribir. El motor sigue decidiendo cuándo se hace cada una."""
        respondidas = {h["id_pregunta"] for h in self.repo.hechos_de_consulta(id_consulta)}
        return [(p, self.opciones.get(p["id_pregunta"], [])) for p in self.preguntas
                if p["id_pregunta"] not in respondidas and p["id_pregunta"] != excepto]

    def id_respuesta_de_hecho(self, id_pregunta, codigo_hecho):
        o = next((o for o in self.opciones.get(id_pregunta, [])
                  if o["codigo_hecho"] == codigo_hecho), None)
        return o["id_respuesta"] if o else None

    def _registrar_respuesta(self, id_consulta, hechos, acumulado, esperada, opcion,
                             origen, texto_usuario, interpretacion=None):
        if opcion is None:
            raise ErrorNegocio(f"La respuesta no corresponde a la pregunta actual ({esperada['codigo']})")

        paso = len(hechos) + 1
        antes = self.ranking(acumulado)
        self.repo.registrar_hecho(id_consulta, paso, esperada["id_pregunta"], opcion["id_hecho"],
                                  origen, texto_usuario)
        granulos = self.repo.granulos_de_pregunta(esperada["id_pregunta"])
        factores = self._factores(granulos, opcion["id_hecho"])
        for h, f in factores.items():
            acumulado[h] = acumulado.get(h, 1.0) * f
        hechos.append({"paso": paso, "id_pregunta": esperada["id_pregunta"],
                       "id_hecho": opcion["id_hecho"]})
        despues = self.ranking(acumulado)
        self.repo.registrar_traza(id_consulta, paso, "respuesta", {
            "hecho": self._hecho_legible(esperada["id_pregunta"], opcion["id_hecho"]),
            "origen": origen, "texto_usuario": texto_usuario, "interpretacion": interpretacion,
            "consulta_granular": f"hechos_hipotesis de la pregunta {esperada['codigo']}",
            "hipotesis_que_dependen": len(granulos),
            "hipotesis_respaldadas": sorted(self.hipotesis[h]["codigo"]
                                            for h, f in factores.items() if f == 1.0),
            "hipotesis_debilitadas": sorted(self.hipotesis[h]["codigo"]
                                            for h, f in factores.items() if f < 1.0),
            "top_antes": [(r["codigo"], round(r["probabilidad"], 4)) for r in antes],
            "top_despues": [(r["codigo"], round(r["probabilidad"], 4)) for r in despues]})

        siguiente, evaluadas = self._siguiente(hechos, acumulado)
        self.repo.registrar_traza(id_consulta, paso, "seleccion_pregunta", {
            "evaluadas": evaluadas, "elegida": siguiente["codigo"] if siguiente else None})
        if siguiente is None:
            self.repo.guardar_diagnostico(id_consulta, despues)
            explicacion = None
            if self.redactor is not None:
                d = self._diagnostico(id_consulta, hechos)
                explicacion = self.redactor.explicacion(d["rutina"], d["respaldo"])
            self.repo.registrar_traza(id_consulta, paso, "conclusion", {
                "explicacion_ia": explicacion,
                "hipotesis": despues[0]["codigo"],
                "probabilidad": round(despues[0]["probabilidad"], 4),
                "motivo": "Ninguna pregunta pendiente puede cambiar la hipótesis líder",
                "consultas_granulares_peticion": self.repo.consultas_granulares,
                "top5": [(r["codigo"], round(r["probabilidad"], 4)) for r in despues]})
        return self.estado(id_consulta)

    def estado(self, id_consulta, incluir_traza=False):
        consulta = self.repo.consulta(id_consulta)
        if consulta is None:
            raise ErrorNegocio("La consulta no existe", 404)
        hechos = self.repo.hechos_de_consulta(id_consulta)
        acumulado = self._acumular(hechos)
        resultado = {
            "id_consulta": id_consulta, "numero": consulta.get("numero"), "estado": consulta["estado"],
            "alias": consulta.get("alias"),
            "fecha_inicio": str(consulta["fecha_inicio"]),
            "fecha_fin": str(consulta["fecha_fin"]) if consulta.get("fecha_fin") else None,
            "verificacion_formal": consulta["verificacion_formal"],
            "hechos": [{**self._hecho_legible(h["id_pregunta"], h["id_hecho"]),
                        "paso": h["paso"], "origen": h["origen"],
                        "texto_usuario": h["texto_usuario"]} for h in hechos],
            "ranking": [{k: v for k, v in r.items() if k != "id_hipotesis"}
                        for r in self.ranking(acumulado)],
        }
        if consulta["estado"] == "en_curso":
            pregunta, _ = self._siguiente(hechos, acumulado)
            resultado["pregunta"] = self._pregunta_para_usuario(pregunta) if pregunta else None
            resultado["progreso"] = {"respondidas": len(hechos)}
        elif consulta["estado"] == "abandonada":
            # Descartada: se conservan las respuestas que alcanzó a dar, sin resultado
            resultado["progreso"] = {"respondidas": len(hechos)}
        else:
            # Una consulta terminada muestra lo que se concluyó en su momento, aunque
            # el conocimiento haya cambiado después
            resultado["diagnostico"] = self._diagnostico(id_consulta, hechos)
            d = resultado["diagnostico"]
            resultado["ranking"] = [{k: v for k, v in d["rutina"].items()
                                     if k != "descripcion_rutina"}] + d["alternativas"]
        if incluir_traza:
            resultado["traza"] = self.repo.traza(id_consulta)
        return resultado

    def _diagnostico(self, id_consulta, hechos):
        guardado = self.repo.diagnostico(id_consulta)
        por_codigo = {h["codigo"]: h for h in self.hipotesis.values()}
        ganadora = por_codigo[guardado[0]["codigo"]]
        # Explicación: qué hechos del usuario respaldan la hipótesis ganadora
        respaldo = []
        for h in hechos:
            g = self.repo.granulos_de_pregunta(h["id_pregunta"]).get(ganadora["id_hipotesis"], {})
            if h["id_hecho"] in g:
                respaldo.append({**self._hecho_legible(h["id_pregunta"], h["id_hecho"]),
                                 "peso": g[h["id_hecho"]]})
        return {
            "explicacion_ia": self.repo.explicacion_ia(id_consulta),
            "rutina": {**self._resumen_hipotesis(ganadora["id_hipotesis"]),
                       "descripcion_rutina": ganadora["descripcion_rutina"],
                       "probabilidad": guardado[0]["probabilidad"]},
            "respaldo": respaldo,
            "alternativas": [{**self._resumen_hipotesis(por_codigo[d["codigo"]]["id_hipotesis"]),
                              "probabilidad": d["probabilidad"]} for d in guardado[1:]],
        }
