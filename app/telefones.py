"""Telefone (WhatsApp) das pessoas: formato e PRIVACIDADE.

Onde o numero mora: `Membro.telefone` (diretorio de cada comunidade, e o que
os avisos de SMS/WhatsApp usam) e `User.telefone` (o proprio usuario cadastra
no Perfil; salvar copia pro Membro de cada comunidade com o mesmo e-mail --
ver `propagar_telefone_da_conta`).

Quem pode VER o numero de um Membro (`pode_ver_telefone`, conferido no
servidor -- template so recebe o numero quando pode):
- a propria pessoa (conta com o mesmo e-mail);
- admin da comunidade (Super Admin incluido);
- lider de um ministerio em que a pessoa esta (papel no ministerio ou ja
  escalada nele), se a pessoa nao desligou "Lider pode ver meu telefone"
  (`User.telefone_visivel_lider`, Perfil > Privacidade).
Membro comum e gente de outra comunidade nunca ve. Os avisos automaticos
(SMS/WhatsApp) usam o numero sempre -- e o sistema, nao uma pessoa.
"""
import re

from wtforms.validators import ValidationError

MENSAGEM_INVALIDO = "Telefone invalido. Use DDD + numero, ex: (11) 98765-4321."


def formatar_telefone(texto):
    """"(DD) 9XXXX-XXXX" (celular) ou "(DD) XXXX-XXXX" (fixo). Aceita com ou
    sem +55, espacos, pontos e tracos. Vazio -> None. Invalido -> ValueError."""
    if not texto or not texto.strip():
        return None
    digitos = re.sub(r"\D", "", texto)
    if digitos.startswith("55") and len(digitos) in (12, 13):
        digitos = digitos[2:]
    digitos = digitos.lstrip("0")
    if len(digitos) not in (10, 11) or digitos[0] == "0" or digitos[1] == "0":
        raise ValueError(MENSAGEM_INVALIDO)
    ddd, numero = digitos[:2], digitos[2:]
    if len(numero) == 9:
        if numero[0] != "9":
            raise ValueError(MENSAGEM_INVALIDO)
        return f"({ddd}) {numero[:5]}-{numero[5:]}"
    if numero[0] in "01":
        raise ValueError(MENSAGEM_INVALIDO)
    return f"({ddd}) {numero[:4]}-{numero[4:]}"


def validar_telefone(form, field):
    """Validador WTForms: confere e ja deixa field.data no formato padrao."""
    try:
        field.data = formatar_telefone(field.data)
    except ValueError as erro:
        raise ValidationError(str(erro))


# --- Privacidade ---------------------------------------------------------------

def _conta_do_membro(membro):
    from app.auth.models import User

    if not membro.email:
        return None
    return User.objects(email__iexact=membro.email.strip()).first()


def eh_o_proprio(membro, usuario):
    return bool(membro.email and usuario.email and membro.email.strip().lower() == usuario.email.strip().lower())


def ministerios_em_comum(membro, usuario):
    """Ministerios da comunidade do membro que `usuario` lidera E em que o
    membro esta (papel da conta dele no ministerio ou ja escalado nele)."""
    from app.escala.models import Escala, Funcao
    from app.ministerio.models import Ministerio, UsuarioMinisterio
    from app.ministerio.routes import _eh_lider_do_ministerio

    liderados = [m for m in Ministerio.objects(comunidade_id=membro.comunidade_id)
                 if _eh_lider_do_ministerio(m, usuario)]
    if not liderados:
        return []
    ids = {m.id for m in liderados}
    escalas = Escala.objects(id__in=list({f.escala_id for f in Funcao.objects(membro_id=membro.id).only("escala_id")}),
                             ministerio_id__in=list(ids)).only("ministerio_id")
    em_comum = {e.ministerio_id for e in escalas}
    conta = _conta_do_membro(membro)
    if conta is not None:
        em_comum |= {p.ministerio_id for p in UsuarioMinisterio.objects(usuario_id=conta.id, ministerio_id__in=list(ids))}
    return [m for m in liderados if m.id in em_comum]


def pode_ver_telefone(membro, usuario):
    if usuario is None or not getattr(usuario, "is_authenticated", False):
        return False
    if eh_o_proprio(membro, usuario) or _eh_admin(membro, usuario):
        return True
    if not ministerios_em_comum(membro, usuario):
        return False
    conta = _conta_do_membro(membro)
    return conta is None or conta.telefone_visivel_lider is not False


def pode_editar_telefone(membro, usuario):
    """Admin edita o de qualquer pessoa do diretorio; lider so o de quem esta
    num ministerio dele, e so se pode ver o numero (a pessoa nao escondeu).
    O proprio usuario edita o seu no Perfil da conta (main.salvar_telefone)."""
    if _eh_admin(membro, usuario):
        return True
    return bool(ministerios_em_comum(membro, usuario)) and pode_ver_telefone(membro, usuario)


def _eh_admin(membro, usuario):
    from app.comunidade.models import comunidade_por_id
    from app.comunidade.routes import _eh_admin_da_comunidade

    comunidade = comunidade_por_id(membro.comunidade_id)
    return comunidade is not None and _eh_admin_da_comunidade(comunidade, usuario)


def propagar_telefone_da_conta(usuario):
    """O usuario mudou o proprio numero no Perfil: vale pra todos os
    diretorios em que ele esta (Membro com o mesmo e-mail) -- e o numero que
    os avisos usam."""
    from app.escala.models import Membro

    Membro.da_conta(usuario.email).update(set__telefone=usuario.telefone)
