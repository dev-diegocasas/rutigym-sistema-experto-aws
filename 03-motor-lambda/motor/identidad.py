"""CAPA DE DATOS · Cuentas en Amazon Cognito (alineadas con el perfil en la base)."""

import os
import secrets
import string

GRUPOS = ("usuario_final", "experto", "ingeniero_conocimiento", "administrador")


def _cliente():
    import boto3
    return boto3.client("cognito-idp")


def _pool():
    pool = os.environ.get("COGNITO_POOL_ID")
    if not pool:
        raise RuntimeError("COGNITO_POOL_ID no está configurado")
    return pool


def contrasena_temporal():
    """Cumple la política del pool: mayúscula, minúscula, número y símbolo."""
    base = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(10))
    return f"Tmp-{base}7a!"


class GestorCuentas:
    def crear(self, correo, nombre, grupo):
        """Crea la cuenta con el correo verificado y una contraseña temporal que el
        usuario debe cambiar en su primer inicio de sesión. Devuelve (sub, contraseña)."""
        c, pool = _cliente(), _pool()
        temporal = contrasena_temporal()
        r = c.admin_create_user(
            UserPoolId=pool, Username=correo, TemporaryPassword=temporal,
            MessageAction="SUPPRESS",
            UserAttributes=[{"Name": "email", "Value": correo},
                            {"Name": "email_verified", "Value": "true"},
                            {"Name": "name", "Value": nombre}])
        sub = next(a["Value"] for a in r["User"]["Attributes"] if a["Name"] == "sub")
        if grupo != "usuario_final":
            c.admin_add_user_to_group(UserPoolId=pool, Username=correo, GroupName=grupo)
        return sub, temporal

    def eliminar(self, correo):
        _cliente().admin_delete_user(UserPoolId=_pool(), Username=correo)

    def cambiar_grupo(self, correo, grupo_anterior, grupo_nuevo):
        c, pool = _cliente(), _pool()
        if grupo_anterior and grupo_anterior != "usuario_final":
            c.admin_remove_user_from_group(UserPoolId=pool, Username=correo,
                                           GroupName=grupo_anterior)
        if grupo_nuevo != "usuario_final":
            c.admin_add_user_to_group(UserPoolId=pool, Username=correo, GroupName=grupo_nuevo)
        # Cierra las sesiones abiertas: el nuevo rol aplica en el próximo inicio de sesión
        c.admin_user_global_sign_out(UserPoolId=pool, Username=correo)

    def cambiar_estado(self, correo, activo):
        c, pool = _cliente(), _pool()
        if activo:
            c.admin_enable_user(UserPoolId=pool, Username=correo)
        else:
            c.admin_disable_user(UserPoolId=pool, Username=correo)
            c.admin_user_global_sign_out(UserPoolId=pool, Username=correo)
