"""Tela "Local do check-in" -- a mesma pra Comunidade (admin) e Ministerio
(lider/admin), ver comunidade.routes.local_checkin e
ministerio.routes.local_checkin. A permissao fica nas rotas; aqui so o
formulario. Busca de endereco: buscar_endereco (OpenStreetMap/Nominatim)."""
import requests
from flask import current_app, flash, redirect, render_template, request

from app.escala.checkin import RAIO_PADRAO_M, local_do_checkin
from app.escala.forms import LocalCheckinForm

_NOMINATIM = "https://nominatim.openstreetmap.org/search"


def tela_local_checkin(alvo, titulo, voltar_url, ministerio=None):
    """GET mostra / POST salva o local de `alvo` (Comunidade ou Ministerio).
    Com `ministerio`, o botao "usar o da comunidade" apaga o local proprio."""
    if request.method == "POST" and request.form.get("acao") == "usar_comunidade" and ministerio is not None:
        from app.escala.forms import AcaoForm

        if AcaoForm().validate_on_submit():
            alvo.endereco = alvo.latitude = alvo.longitude = alvo.raio_checkin_m = None
            alvo.save()
            flash("Este ministério agora usa o local da comunidade.", "success")
        return redirect(request.path)

    form = LocalCheckinForm(obj=alvo) if request.method == "GET" else LocalCheckinForm()
    if request.method == "GET" and not alvo.raio_checkin_m:
        form.raio_checkin_m.data = RAIO_PADRAO_M
    if form.validate_on_submit():
        alvo.endereco = (form.endereco.data or "").strip() or None
        alvo.latitude = form.latitude.data
        alvo.longitude = form.longitude.data
        alvo.raio_checkin_m = form.raio_checkin_m.data
        alvo.save()
        flash("Local do check-in salvo.", "success")
        return redirect(voltar_url)

    herdado = None
    if ministerio is not None and alvo.latitude is None:
        herdado = local_do_checkin(ministerio)  # o da comunidade, se houver
    return render_template(
        "escala/local_checkin.html",
        form=form,
        titulo=titulo,
        voltar_url=voltar_url,
        eh_ministerio=ministerio is not None,
        tem_proprio=alvo.latitude is not None,
        herdado=herdado,
    )


def buscar_endereco(texto):
    """Ate 5 enderecos parecidos: [{"rotulo", "latitude", "longitude"}].
    OpenStreetMap (Nominatim): gratuito, sem chave; a politica de uso pede
    identificacao (User-Agent) e poucas buscas -- so o lider usa, ao
    cadastrar o local."""
    texto = " ".join((texto or "").split())[:200]
    if len(texto) < 4:
        return []
    try:
        resposta = requests.get(
            _NOMINATIM,
            params={"q": texto, "format": "jsonv2", "limit": 5, "countrycodes": "br", "accept-language": "pt-BR"},
            headers={"User-Agent": f"TyBenson/1.0 ({current_app.config.get('URL_PUBLICA') or 'pibaswerdne.me'})"},
            timeout=6,
        )
        resposta.raise_for_status()
        itens = resposta.json()
    except (requests.RequestException, ValueError):
        current_app.logger.warning("Busca de endereco falhou", exc_info=True)
        return None
    return [
        {"rotulo": item.get("display_name", ""), "latitude": float(item["lat"]), "longitude": float(item["lon"])}
        for item in itens if item.get("lat") and item.get("lon")
    ]
