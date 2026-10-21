"""Areas de um ministerio (ex: Criativo -> Projecao, Midia, Live) -- ver
ministerio.models.AreaMinisterio.

- A escala continua UMA so por evento; as funcoes ganham `Funcao.area_id` e a
  grade agrupa por area.
- Quem pode o que: o lider do ministerio (e o admin da comunidade) gerencia
  tudo, como sempre. O **lider de area** (`UsuarioMinisterio.areas_lider`)
  gerencia so as funcoes da area dele nas escalas do ministerio -- escalar,
  remover, trocar, status, aprovar troca --, sem criar/excluir escala nem
  mexer nas areas (`pode_gerenciar_funcao`).
- Quem atua na area (`UsuarioMinisterio.areas`) aparece primeiro na hora de
  escalar uma funcao dela; entra sozinho na area ao ser escalado nela.
Ministerio sem areas funciona exatamente como antes.
"""
from app.db_utils import por_requisicao


def areas_do_ministerio(ministerio_id):
    """Areas do ministerio na ordem da tela (1 consulta por requisicao)."""
    from app.ministerio.models import AreaMinisterio

    return por_requisicao(
        ("areas_do_ministerio", ministerio_id),
        lambda: list(AreaMinisterio.objects(ministerio_id=ministerio_id).order_by("ordem", "id")),
    )


def area_por_id(area_id):
    """Uma area pelo id, guardada durante a requisicao (o nome da area vai em
    cada aviso de escalado)."""
    from app.ministerio.models import AreaMinisterio

    return por_requisicao(("area_por_id", area_id), lambda: AreaMinisterio.objects(id=area_id).first())


def papel_no_ministerio(ministerio_id, usuario):
    """Linha UsuarioMinisterio da conta neste ministerio (ou None)."""
    from app.ministerio.models import UsuarioMinisterio

    if usuario is None or not getattr(usuario, "is_authenticated", False):
        return None
    return por_requisicao(
        ("papel_no_ministerio", ministerio_id, usuario.id),
        lambda: UsuarioMinisterio.objects(ministerio_id=ministerio_id, usuario_id=usuario.id).first(),
    )


def areas_lideradas(ministerio_id, usuario):
    """Ids das areas que a conta lidera neste ministerio."""
    linha = papel_no_ministerio(ministerio_id, usuario)
    return set(linha.areas_lider or []) if linha else set()


def pode_gerenciar_funcao(funcao, ministerio, usuario):
    """Lider do ministerio/admin: qualquer funcao. Lider de area: so funcao da
    area dele."""
    from app.ministerio.routes import _eh_lider_do_ministerio

    if _eh_lider_do_ministerio(ministerio, usuario):
        return True
    return bool(funcao.area_id) and funcao.area_id in areas_lideradas(ministerio.id, usuario)


def lideres_da_area(area_id):
    """Contas (User) que lideram a area -- avisadas de troca/status junto com
    os lideres do ministerio."""
    from app.auth.models import User
    from app.ministerio.models import UsuarioMinisterio

    ids = [linha.usuario_id for linha in UsuarioMinisterio.objects(areas_lider=area_id).only("usuario_id")]
    return list(User.objects(id__in=ids)) if ids else []


def incluir_na_area(ministerio_id, usuario_id, area_id):
    """Quem e escalado numa funcao da area passa a constar nela (sem tirar de
    nenhuma outra). So se ja tem papel no ministerio."""
    from app.ministerio.models import UsuarioMinisterio

    if area_id:
        UsuarioMinisterio.objects(ministerio_id=ministerio_id, usuario_id=usuario_id).update(add_to_set__areas=area_id)


def excluir_area(area):
    """Apaga a area sem apagar escala nenhuma: as funcoes dela ficam sem area
    e ninguem mais consta nela nem a lidera."""
    from app.escala.models import Escala, Funcao
    from app.ministerio.models import UsuarioMinisterio

    ids_escalas = [e.id for e in Escala.objects(ministerio_id=area.ministerio_id).only("id")]
    if ids_escalas:
        Funcao.objects(escala_id__in=ids_escalas, area_id=area.id).update(unset__area_id=True)
    UsuarioMinisterio.objects(ministerio_id=area.ministerio_id).update(pull__areas=area.id, pull__areas_lider=area.id)
    area.delete()


def ordenar_por_area(funcoes, areas):
    """Funcoes agrupadas na ordem das areas (as sem area primeiro, como uma
    escala antiga), mantendo a ordem de cada uma dentro do grupo -- funcao
    nova de uma area cai junto das outras dela, nao no fim da grade."""
    if not areas or not any(f.area_id for f in funcoes):
        return funcoes
    posicao = {a.id: i for i, a in enumerate(areas)}
    return sorted(funcoes, key=lambda f: (posicao.get(f.area_id, -1) if f.area_id else -1, f.ordem or 0, f.id))
