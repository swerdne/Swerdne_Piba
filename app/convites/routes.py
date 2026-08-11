"""Controller (C do MVC): rotas do modulo convites.

So o lado de quem RECEBE o convite (ver token, aceitar, recusar). O ENVIO
mora em comunidade.routes/ministerio.routes (cada um dono do seu escopo) --
ver app/convites/CLAUDE.md pro fluxo completo.
"""
from datetime import datetime, timezone

from flask import render_template, redirect, url_for, flash, session
from flask_login import login_required, current_user

from app.extensions import db
from app.convites import bp
from app.convites.forms import AcaoForm
from app.convites.models import Convite, STATUS_PENDENTE, STATUS_ACEITO, STATUS_RECUSADO
from app.comunidade.models import UsuarioComunidade
from app.ministerio.models import UsuarioMinisterio
from app.emailing import enviar_email, EmailNaoEnviadoError


def _enviar_email_de_convite(convite):
    """Compartilhado por comunidade.papeis e ministerio.papeis -- monta e
    envia o e-mail com o link de aceite/recusa. Falha de envio nunca quebra a
    requisicao (mesmo padrao de app/emailing.py em todo o projeto): o convite
    ja foi salvo no banco, o link continua valido, so avisa que o e-mail
    pode nao ter chegado."""
    link = url_for("convites.ver_convite", token=convite.token, _external=True)
    corpo = (
        f'Voce foi convidado(a) para o papel de {convite.papel} em "{convite.escopo_nome}".\n\n'
        f"Acesse o link abaixo para aceitar ou recusar o convite:\n{link}\n\n"
        "Se voce nao esperava este convite, pode ignorar este e-mail."
    )
    try:
        enviar_email(convite.email, f"Convite para {convite.escopo_nome}", corpo)
    except EmailNaoEnviadoError:
        flash(
            f"Convite criado, mas o e-mail nao pode ser enviado agora. "
            f"Compartilhe o link manualmente: {link}",
            "danger",
        )


@bp.route("/<token>")
def ver_convite(token):
    """Publica de proposito (sem @login_required): quem ainda nao tem conta
    precisa ver a tela pra saber que precisa se cadastrar antes de aceitar."""
    convite = Convite.query.filter_by(token=token).first_or_404()

    if convite.status != STATUS_PENDENTE:
        return render_template("convites/ver.html", convite=convite, pode_responder=False)

    if not current_user.is_authenticated:
        # Guarda o link do convite na sessao pra login/register saberem
        # trazer o usuario de volta pra ca depois de autenticar (ver
        # auth.routes -- `next` na query string OU sessao, mesmo padrao).
        session["proximo_apos_login"] = url_for("convites.ver_convite", token=token)
        return render_template(
            "convites/ver.html", convite=convite, pode_responder=False,
            precisa_login=True, tem_conta=bool(convite.usuario_ja_cadastrado),
        )

    email_bate = current_user.email.lower() == convite.email.lower()
    return render_template(
        "convites/ver.html", convite=convite,
        pode_responder=email_bate, email_bate=email_bate,
        acao_form=AcaoForm(),
    )


def _aplicar_papel(convite, usuario):
    """Cria ou atualiza a linha de papel (UsuarioComunidade/UsuarioMinisterio)
    correspondente ao convite aceito. Atualiza em vez de duplicar se a pessoa
    ja tinha um papel nesse escopo (ex: reconvidada com papel diferente)."""
    if convite.escopo_tipo == "comunidade":
        papel_existente = UsuarioComunidade.query.filter_by(
            usuario_id=usuario.id, comunidade_id=convite.escopo_id
        ).first()
        if papel_existente:
            papel_existente.papel = convite.papel
        else:
            db.session.add(UsuarioComunidade(
                usuario_id=usuario.id, comunidade_id=convite.escopo_id, papel=convite.papel
            ))
        return url_for("comunidade.detalhe", comunidade_id=convite.escopo_id)

    papel_existente = UsuarioMinisterio.query.filter_by(
        usuario_id=usuario.id, ministerio_id=convite.escopo_id
    ).first()
    if papel_existente:
        papel_existente.papel = convite.papel
    else:
        db.session.add(UsuarioMinisterio(
            usuario_id=usuario.id, ministerio_id=convite.escopo_id, papel=convite.papel
        ))
    return url_for("ministerio.detalhe", ministerio_id=convite.escopo_id)


@bp.route("/<token>/aceitar", methods=["POST"])
@login_required
def aceitar_convite(token):
    convite = Convite.query.filter_by(token=token).first_or_404()
    form = AcaoForm()

    if not form.validate_on_submit():
        flash("Acao invalida.", "danger")
        return redirect(url_for("convites.ver_convite", token=token))

    if convite.status != STATUS_PENDENTE:
        flash("Este convite ja foi respondido.", "danger")
        return redirect(url_for("convites.ver_convite", token=token))

    if current_user.email.lower() != convite.email.lower():
        flash("Este convite foi enviado para outro e-mail -- entre com a conta certa pra aceitar.", "danger")
        return redirect(url_for("convites.ver_convite", token=token))

    destino = _aplicar_papel(convite, current_user)
    convite.status = STATUS_ACEITO
    convite.respondido_em = datetime.now(timezone.utc)
    db.session.commit()

    flash(f'Convite aceito! Voce agora e "{convite.papel}" em {convite.escopo_nome}.', "success")
    return redirect(destino)


@bp.route("/<token>/recusar", methods=["POST"])
@login_required
def recusar_convite(token):
    convite = Convite.query.filter_by(token=token).first_or_404()
    form = AcaoForm()

    if not form.validate_on_submit():
        flash("Acao invalida.", "danger")
        return redirect(url_for("convites.ver_convite", token=token))

    if convite.status != STATUS_PENDENTE:
        flash("Este convite ja foi respondido.", "danger")
        return redirect(url_for("convites.ver_convite", token=token))

    if current_user.email.lower() != convite.email.lower():
        flash("Este convite foi enviado para outro e-mail.", "danger")
        return redirect(url_for("convites.ver_convite", token=token))

    convite.status = STATUS_RECUSADO
    convite.respondido_em = datetime.now(timezone.utc)
    db.session.commit()

    flash("Convite recusado.", "success")
    return redirect(url_for("main.dashboard"))
