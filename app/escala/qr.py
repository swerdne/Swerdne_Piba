"""Check-in por QR code: alternativa quando o GPS falha dentro da igreja.

1. O lider abre "QR do check-in" na escala (escala.qr_checkin, tela cheia).
   O QR leva o endereco /escala/<id>/qr/<janela>-<codigo> e troca a cada
   JANELA_SEGUNDOS (a tela busca o codigo novo sozinha, escala.qr_atual).
2. A pessoa escalada le o QR com a camera: abre escala.qr_ler, que confere
   o codigo (vale ate VALIDADE_JANELAS janelas atras -- foto antiga do QR
   mandada no grupo nao funciona) e mostra "Confirmar presenca".
3. O POST marca "Presente" nas funcoes dela nesta escala, como o check-in
   por GPS, com Funcao.checkin_metodo = "qr" (sem distancia). Entre ler o QR
   e confirmar a pessoa tem CONFIRMAR_EM_SEGUNDOS (guardado na sessao).

So no dia da escala, de 3 h antes a 3 h depois do horario (sem horario: o
dia todo), com o check-in de escala ligado. O codigo e um HMAC da
SECRET_KEY com o id da escala e a janela: nada guardado no banco.
"""
import hashlib
import hmac
import time
from datetime import datetime, timedelta, timezone

from flask import abort, current_app, flash, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required

from app.db_utils import primeiro_ou_404
from app.escala import bp
from app.extensions import limiter

JANELA_SEGUNDOS = 30
VALIDADE_JANELAS = 2  # a janela atual e as 2 anteriores (ate ~90 s)
CONFIRMAR_EM_SEGUNDOS = 300
MARGEM = timedelta(hours=3)


def _janela_atual():
    return int(time.time() // JANELA_SEGUNDOS)


def codigo(escala_id, janela):
    chave = (current_app.config.get("SECRET_KEY") or "").encode()
    assinatura = hmac.new(chave, f"qr-checkin:{escala_id}:{janela}".encode(), hashlib.sha256).hexdigest()
    return assinatura[:16]


def codigo_valido(escala_id, texto):
    try:
        janela_txt, recebido = texto.split("-", 1)
        janela = int(janela_txt)
    except (ValueError, AttributeError):
        return False
    agora = _janela_atual()
    if not (agora - VALIDADE_JANELAS <= janela <= agora):
        return False
    return hmac.compare_digest(codigo(escala_id, janela), recebido)


def _agora_brasilia():
    return datetime.now(timezone.utc) - timedelta(hours=3)


def motivo_fora_do_horario(escala):
    """None se o QR vale agora; senao, o motivo."""
    from app.escala.checkin import checkin_ligado, situacao_do_dia

    if not checkin_ligado(escala, "escala"):
        return "O check-in está desligado nesta escala."
    agora = _agora_brasilia()
    motivo = situacao_do_dia(escala, agora.date())
    if motivo:
        return motivo
    if escala.horario:
        inicio = datetime.combine(escala.data, escala.horario)
        agora_sem_fuso = agora.replace(tzinfo=None)
        if agora_sem_fuso < inicio - MARGEM:
            return f"O check-in por QR abre às {(inicio - MARGEM).strftime('%H:%M')}."
        if agora_sem_fuso > inicio + MARGEM:
            return "O horário do check-in por QR desta escala já passou."
    return None


def _url_do_qr(escala):
    janela = _janela_atual()
    return url_for("escala.qr_ler", escala_id=escala.id, codigo=f"{janela}-{codigo(escala.id, janela)}", _external=True)


@bp.route("/<int:escala_id>/qr-checkin")
@login_required
def qr_checkin(escala_id):
    """Tela cheia do lider com o QR que troca sozinho."""
    from app.escala.routes import _escala_do_usuario_ou_404

    escala = _escala_do_usuario_ou_404(escala_id)
    return render_template("escala/qr_checkin.html", escala=escala, motivo=motivo_fora_do_horario(escala),
                           url_qr=_url_do_qr(escala), segundos=JANELA_SEGUNDOS)


@bp.route("/<int:escala_id>/qr-checkin/atual")
@login_required
def qr_atual(escala_id):
    from app.escala.routes import _escala_do_usuario_ou_404

    escala = _escala_do_usuario_ou_404(escala_id)
    restante = JANELA_SEGUNDOS - int(time.time()) % JANELA_SEGUNDOS
    return jsonify({"url": _url_do_qr(escala), "motivo": motivo_fora_do_horario(escala), "segundos": restante})


def _minhas_funcoes(escala):
    from app.escala.models import Funcao, Membro

    ids = [m.id for m in Membro.da_conta((current_user.email or "").lower()).only("id")]
    return list(Funcao.objects(escala_id=escala.id, membro_id__in=ids)) if ids else []


@bp.route("/<int:escala_id>/qr/<codigo>", methods=["GET", "POST"])
@login_required
@limiter.limit("30 per minute")
def qr_ler(escala_id, codigo):
    """Quem leu o QR: confere e confirma a presenca (um toque)."""
    from app.escala.models import Escala
    from app.main.forms import AcaoForm

    escala = primeiro_ou_404(Escala.objects(id=escala_id))
    minhas = _minhas_funcoes(escala)
    chave_sessao = f"qr_ok_{escala.id}"
    form = AcaoForm()

    if request.method == "GET":
        erro = None
        if not minhas:
            erro = "Você não está escalado(a) nesta escala, então não há check-in para fazer."
        elif not codigo_valido(escala.id, codigo):
            erro = "Este QR já expirou (ele muda a cada 30 segundos). Leia de novo o QR na tela do líder."
        else:
            erro = motivo_fora_do_horario(escala)
        if not erro:
            session[chave_sessao] = int(time.time())
        return render_template("escala/qr_ler.html", escala=escala, minhas=minhas, erro=erro, acao_form=form,
                               ja_feito=all(f.checkin_em for f in minhas) if minhas else False)

    lido_em = session.get(chave_sessao)
    if not form.validate_on_submit() or not minhas or not lido_em or time.time() - lido_em > CONFIRMAR_EM_SEGUNDOS:
        flash("Leia o QR de novo para confirmar a presença.", "danger")
        return redirect(url_for("main.minha_escala", escala=escala.id))
    motivo = motivo_fora_do_horario(escala)
    if motivo:
        flash(motivo, "danger")
        return redirect(url_for("main.minha_escala", escala=escala.id))
    session.pop(chave_sessao, None)
    marcar_presenca_por_qr(escala, minhas)
    flash("Presença confirmada pelo QR. Bom serviço!", "success")
    return redirect(url_for("main.minha_escala", escala=escala.id))


def marcar_presenca_por_qr(escala, funcoes):
    from app.escala.routes import _notificar_lideres_do_ministerio

    agora = datetime.now(timezone.utc)
    novas = []
    for funcao in funcoes:
        if funcao.checkin_em and funcao.status == "presente":
            continue
        funcao.status = "presente"
        funcao.troca_motivo = None
        funcao.troca_sugestao_membro_id = None
        funcao.troca_aceite = None
        funcao.checkin_em = agora
        funcao.checkin_distancia_m = None
        funcao.checkin_precisao_m = None
        funcao.checkin_metodo = "qr"
        funcao.save()
        novas.append(funcao)
    if novas:
        nome = novas[0].membro.nome
        hora = (agora - timedelta(hours=3)).strftime("%H:%M")
        _notificar_lideres_do_ministerio(
            escala, f"{nome} fez check-in pelo QR ({', '.join(f.nome for f in novas)})",
            f"{nome} fez check-in pelo QR às {hora} em {escala.nome}.", tipo="presente",
        )
    return novas
