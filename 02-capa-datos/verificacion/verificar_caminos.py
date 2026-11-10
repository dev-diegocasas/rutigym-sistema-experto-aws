"""Verifica la base: 48 caminos del árbol, 720 combinaciones y 32 hipótesis alcanzables.
Uso: python3 verificar_caminos.py local|aurora"""

import itertools
import os
import ssl
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "..", "_deps"))
import pg8000.native  # noqa: E402

# Banco de pruebas: las reglas del árbol de decisión validado con el experto
# (R01-R30 del documento + R31-R48 de la rama de principiante ampliada)
import json  # noqa: E402
with open(os.path.join(AQUI, "reglas_arbol.json"), encoding="utf-8") as _f:
    REGLAS = [(r, h, [tuple(c) for c in conds]) for r, h, conds in json.load(_f)]
_OBJ = ["Fuerza", "Hipertrofia", "Resistencia", "Pérdida de grasa", "Rendimiento deportivo"]


def conectar(destino):
    if destino == "local":
        return pg8000.native.Connection(user="app_lambda", database="prueba",
                                        unix_sock="/var/tmp/pgtest/.s.PGSQL.5499")
    import boto3
    rds = boto3.client("rds", region_name="us-east-1")
    host = rds.describe_db_clusters(DBClusterIdentifier="se-rutinas-db")["DBClusters"][0]["Endpoint"]
    token = rds.generate_db_auth_token(DBHostname=host, Port=5432, DBUsername="app_lambda",
                                       Region="us-east-1")
    ctx = ssl.create_default_context()
    bundle = os.path.join(AQUI, "..", "global-bundle.pem")
    if os.path.exists(bundle):
        ctx.load_verify_locations(bundle)
    return pg8000.native.Connection(user="app_lambda", host=host, database="postgres",
                                    password=token, ssl_context=ctx, timeout=60)


class MotorPrototipo:
    """Razonamiento probabilístico con consultas granulares a la base."""

    def __init__(self, con):
        self.con = con
        self.consultas = 0
        self.preguntas = con.run("SELECT id_pregunta, atributo, orden FROM preguntas ORDER BY orden")
        self.hipotesis = {r[0]: (r[1], float(r[2])) for r in con.run(
            "SELECT id_hipotesis, codigo, probabilidad_previa FROM hipotesis")}
        self.opciones = {}
        for idp, idh, valor in con.run(
                "SELECT r.id_pregunta, r.id_hecho, he.valor FROM respuesta_pregunta r "
                "JOIN hechos he ON he.id_hecho = r.id_hecho ORDER BY r.id_pregunta, r.orden"):
            self.opciones.setdefault(idp, []).append((idh, valor))

    def granulos_de_pregunta(self, id_pregunta):
        """Consulta granular: qué hipótesis dependen de esta pregunta y con qué peso."""
        self.consultas += 1
        filas = self.con.run(
            "SELECT hh.id_hipotesis, hh.id_hecho, hh.peso FROM hechos_hipotesis hh "
            "JOIN hechos he ON he.id_hecho = hh.id_hecho WHERE he.id_pregunta = :p",
            p=id_pregunta)
        por_hip = {}
        for idh, hecho, peso in filas:
            por_hip.setdefault(idh, {})[hecho] = float(peso)
        return por_hip

    @staticmethod
    def factores(granulos, id_hecho):
        """Factor de cada hipótesis si el usuario afirma id_hecho."""
        return {h: 1.0 if id_hecho in g else 1.0 - max(g.values())
                for h, g in granulos.items()}

    def puntajes(self, factores_acumulados):
        return {h: prev * factores_acumulados.get(h, 1.0)
                for h, (_, prev) in self.hipotesis.items()}

    @staticmethod
    def lideres(p):
        m = max(p.values())
        return frozenset(h for h, v in p.items() if v >= m * (1 - 1e-9))

    def siguiente_pregunta(self, respondidas, acumulado):
        actuales = self.lideres(self.puntajes(acumulado))
        for idp, atributo, _ in self.preguntas:
            if idp in respondidas:
                continue
            granulos = self.granulos_de_pregunta(idp)
            for id_hecho, _ in self.opciones[idp]:
                f = self.factores(granulos, id_hecho)
                hipotetico = {h: acumulado.get(h, 1.0) * f.get(h, 1.0) for h in self.hipotesis}
                if self.lideres(self.puntajes(hipotetico)) != actuales:
                    return idp, atributo, granulos    # esta pregunta puede cambiar al líder
        return None

    def consultar(self, responder):
        respondidas, acumulado, orden = {}, {}, []
        while True:
            sig = self.siguiente_pregunta(respondidas, acumulado)
            if sig is None:
                break
            idp, atributo, granulos = sig
            valor = responder(atributo)
            if valor is None:
                return orden, None, None
            id_hecho = next(h for h, v in self.opciones[idp] if v == valor)
            respondidas[idp] = id_hecho
            for h, f in self.factores(granulos, id_hecho).items():
                acumulado[h] = acumulado.get(h, 1.0) * f
            orden.append(atributo)
        p = self.puntajes(acumulado)
        total = sum(p.values())
        top = sorted(((self.hipotesis[h][0], v / total) for h, v in p.items()),
                     key=lambda x: -x[1])[:5]
        lideres = self.lideres(p)
        return orden, top, len(lideres) == 1


def main():
    destino = sys.argv[1] if len(sys.argv) > 1 else "local"
    con = conectar(destino)
    con.run("SET ROLE rol_usuario")      # el motor lee la base con el rol del usuario final
    motor = MotorPrototipo(con)
    fallos = 0

    print(f"A. Los {len(REGLAS)} caminos del árbol")
    for regla, esperada, conds in REGLAS:
        perfil = dict(conds)
        orden, top, unico = motor.consultar(lambda a: perfil.get(a))
        ok = (top is not None and unico and top[0][0] == esperada
              and orden == [a for a, _ in conds])
        fallos += not ok
        alternativas = ", ".join(f"{c} {p * 100:.1f}%" for c, p in top[1:]) if top else "-"
        print(f"  {'OK ' if ok else 'FALLO'} {regla} → {top[0][0] if top else '?'} "
              f"{top[0][1] * 100:5.1f}% (esperada {esperada}) | {len(orden)} preguntas | "
              f"siguientes: {alternativas}")

    print("\nB. Todas las combinaciones posibles de respuestas")
    dominios = {"tecnica_dominada": ["Sí", "No", "No estoy seguro"],
                "tiempo_entrenando": ["Menos de 6 meses", "6 meses a 2 años", "Más de 2 años"],
                "equipo_disponible": ["Básico o en casa", "Gimnasio completo"],
                "objetivo_principal": _OBJ, "fase_priorizada": ["Volumen", "Intensidad"],
                "dias_semana": ["2 días", "3 o más días"],
                "actividad_actual": ["Sedentario", "Algo activo"]}
    claves = list(dominios)
    combinaciones, alcanzadas, ambiguas, incoherentes = 0, set(), 0, 0
    for valores in itertools.product(*dominios.values()):
        perfil = dict(zip(claves, valores))
        orden, top, unico = motor.consultar(lambda a: perfil[a])
        combinaciones += 1
        if not unico:
            ambiguas += 1
            continue
        ganadora = top[0][0]
        alcanzadas.add(ganadora)
        # Coherencia con el árbol: alguna regla de la ganadora se cumple con lo respondido
        if not any(h == ganadora and all(perfil[a] == v for a, v in c) for _, h, c in REGLAS):
            incoherentes += 1
    print(f"  {combinaciones} combinaciones · ganadora única en {combinaciones - ambiguas} · "
          f"incoherentes con el árbol: {incoherentes}")
    fallos += ambiguas + incoherentes

    print("\nC. Alcanzabilidad")
    faltan = sorted(set(c for c, _ in motor.hipotesis.values()) - alcanzadas)
    print(f"  {len(alcanzadas)}/{len(motor.hipotesis)} hipótesis alcanzables" + (f" · faltan {faltan}" if faltan else ""))
    fallos += len(faltan)

    print(f"\nConsultas granulares ejecutadas: {motor.consultas}")
    print("RESULTADO:", "TODO CORRECTO" if fallos == 0 else f"{fallos} FALLOS")
    con.close()
    sys.exit(1 if fallos else 0)


if __name__ == "__main__":
    main()
