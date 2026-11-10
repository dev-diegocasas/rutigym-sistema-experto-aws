"""Crea las 7 cuentas de demostración en Cognito y las vincula con su perfil en la base.
Uso: python3 cuentas/crear_cuentas.py <UserPoolId>"""

import os
import secrets
import ssl
import string
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "..", "_deps"))
import boto3  # noqa: E402
import pg8000.native  # noqa: E402

REGION = "us-east-1"
ARCHIVO = os.path.join(AQUI, "..", "credenciales_demo.txt")
CUENTAS = [  # correo, nombre, grupo de Cognito (None = usuario final)
    ("diego.admin@sistema-experto.test", "Diego Casas", "administrador"),
    ("simon.ingeniero@sistema-experto.test", "Simón", "ingeniero_conocimiento"),
    ("cristian.experto@sistema-experto.test", "Cristian", "experto"),
    ("profesor.experto@sistema-experto.test", "Profesor revisor", "experto"),
    ("laura.usuario@sistema-experto.test", "Laura Gómez", None),
    ("andres.usuario@sistema-experto.test", "Andrés Rojas", None),
    ("valentina.usuario@sistema-experto.test", "Valentina Ruiz", None),
]

cognito = boto3.client("cognito-idp", region_name=REGION)


def contrasena():
    cuerpo = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(12))
    return f"Se{cuerpo}9#"


def leer_existentes():
    claves = {}
    if os.path.exists(ARCHIVO):
        for linea in open(ARCHIVO, encoding="utf-8"):
            partes = [p.strip() for p in linea.split("|")]
            if len(partes) >= 4 and "@" in partes[1]:
                claves[partes[1]] = partes[3]
    return claves


def asegurar_cuenta(pool, correo, nombre, grupo, clave):
    try:
        r = cognito.admin_get_user(UserPoolId=pool, Username=correo)
        atributos = {a["Name"]: a["Value"] for a in r["UserAttributes"]}
    except cognito.exceptions.UserNotFoundException:
        r = cognito.admin_create_user(
            UserPoolId=pool, Username=correo, MessageAction="SUPPRESS",
            UserAttributes=[{"Name": "email", "Value": correo},
                            {"Name": "email_verified", "Value": "true"},
                            {"Name": "name", "Value": nombre}])
        atributos = {a["Name"]: a["Value"] for a in r["User"]["Attributes"]}
    cognito.admin_set_user_password(UserPoolId=pool, Username=correo, Password=clave,
                                    Permanent=True)
    actuales = {g["GroupName"] for g in cognito.admin_list_groups_for_user(
        UserPoolId=pool, Username=correo)["Groups"]}
    for g in actuales - {grupo}:
        cognito.admin_remove_user_from_group(UserPoolId=pool, Username=correo, GroupName=g)
    if grupo and grupo not in actuales:
        cognito.admin_add_user_to_group(UserPoolId=pool, Username=correo, GroupName=grupo)
    return atributos["sub"]


def conectar_propietario():
    rds = boto3.client("rds", region_name=REGION)
    host = rds.describe_db_clusters(DBClusterIdentifier="se-rutinas-db")["DBClusters"][0]["Endpoint"]
    token = rds.generate_db_auth_token(DBHostname=host, Port=5432, DBUsername="postgres",
                                       Region=REGION)
    ctx = ssl.create_default_context()
    bundle = os.path.join(AQUI, "..", "global-bundle.pem")
    if os.path.exists(bundle):
        ctx.load_verify_locations(bundle)
    con = pg8000.native.Connection(user="postgres", host=host, database="postgres",
                                   password=token, ssl_context=ctx, timeout=60)
    con.run("SET ROLE se_owner")
    return con


def main():
    pool = sys.argv[1]
    claves = leer_existentes()
    con = conectar_propietario()
    filas = []
    try:
        for correo, nombre, grupo in CUENTAS:
            clave = claves.get(correo) or contrasena()
            sub = asegurar_cuenta(pool, correo, nombre, grupo, clave)
            vinculados = con.run("UPDATE se.usuario SET cognito_sub = :s WHERE correo = :c "
                                 "RETURNING alias, rol::TEXT", s=sub, c=correo)
            if not vinculados:
                print(f"   AVISO: {correo} no tiene perfil en la base de datos")
                continue
            alias, rol = vinculados[0]
            filas.append((alias, correo, rol, clave))
            print(f"   OK  {alias:10} {rol:24} {correo}")
    finally:
        con.close()

    with open(ARCHIVO, "w", encoding="utf-8") as f:
        f.write("Cuentas de demostración del sistema experto (no compartir públicamente)\n\n")
        f.write(f"{'alias':10} | {'correo':42} | {'rol':24} | contraseña\n")
        for alias, correo, rol, clave in filas:
            f.write(f"{alias:10} | {correo:42} | {rol:24} | {clave}\n")
    os.chmod(ARCHIVO, 0o600)
    print(f"Cuentas listas: {len(filas)}/{len(CUENTAS)} · contraseñas en credenciales_demo.txt")
    return 0 if len(filas) == len(CUENTAS) else 1


if __name__ == "__main__":
    sys.exit(main())
