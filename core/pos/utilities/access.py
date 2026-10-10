from core.security.session import get_group


def can_print_voucher(request, voucher, permission='view_sale'):
    """Un cliente solo puede imprimir sus propios comprobantes; el personal
    necesita el permiso de consulta en el perfil activo."""
    user = request.user
    if not user.is_authenticated:
        return False
    if user.is_client():
        return voucher.client_id is not None and voucher.client.user_id == user.id
    group = get_group(request)
    return group is not None and group.permissions.filter(codename=permission).exists()
