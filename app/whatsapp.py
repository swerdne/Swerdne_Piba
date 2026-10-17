"""Envio de WhatsApp via Meta Cloud API (WhatsApp Business Platform).

Conta gratuita em developers.facebook.com -- camada gratuita generosa (sem
custo pro volume de uma igreja), diferente do Twilio, que so deixa criar
Templates de mensagem proativa em conta paga. Precisa de META_WHATSAPP_TOKEN
(token de acesso do app) e META_WHATSAPP_PHONE_ID (id do numero configurado
no WhatsApp Business) no .env.
"""
import mongoengine
import requests
from flask import current_app

from app.fuso import hoje_brasilia
from app.sms import normalizar_telefone

# Mesmo raciocinio do timeout em app/emailing.py e app/sms.py.
_TIMEOUT_SEGUNDOS = 12
_API_VERSAO = "v21.0"


class WhatsappNaoEnviadoError(Exception):
    """Levantada quando a mensagem de WhatsApp nao pode ser enviada (config ausente, Meta recusou, etc.)."""


class TemplatesDoDia(mongoengine.Document):
    """Quantos templates (mensagens cobradas) foram tentados em cada dia de
    Brasilia -- base do teto diario (WHATSAPP_LIMITE_TEMPLATES_DIA). No banco,
    nao em memoria, pra valer mesmo depois de reiniciar o servidor."""
    meta = {"collection": "whatsapp_templates_por_dia"}

    dia = mongoengine.StringField(primary_key=True)  # "2026-10-16"
    enviados = mongoengine.IntField(default=0)


def _reservar_template_do_dia():
    """Conta +1 template no dia (atomico -- os envios do Notificar rodam em
    threads) e recusa acima do teto: trava de seguranca contra um bug ou um
    disparo em massa gerar custo inesperado. Conta a TENTATIVA (antes de
    chamar a Meta), entao erra pro lado de mandar menos, nunca mais."""
    limite = current_app.config.get("WHATSAPP_LIMITE_TEMPLATES_DIA") or 0
    if limite <= 0:
        return  # 0 = sem teto
    dia = hoje_brasilia().isoformat()
    contador = TemplatesDoDia.objects(dia=dia).modify(upsert=True, new=True, inc__enviados=1)
    if contador.enviados > limite:
        if contador.enviados == limite + 1:
            current_app.logger.error(
                "Teto diario de templates de WhatsApp atingido (%s em %s): os proximos envios de template "
                "de hoje foram bloqueados. Ajuste WHATSAPP_LIMITE_TEMPLATES_DIA se for esperado.", limite, dia)
        raise WhatsappNaoEnviadoError(f"Teto diario de {limite} templates de WhatsApp atingido.")


def _config_ou_erro():
    token = current_app.config.get("META_WHATSAPP_TOKEN")
    phone_id = current_app.config.get("META_WHATSAPP_PHONE_ID")
    if not token or not phone_id:
        current_app.logger.warning("WhatsApp nao enviado: META_WHATSAPP_TOKEN/META_WHATSAPP_PHONE_ID nao configurados.")
        raise WhatsappNaoEnviadoError(
            "Envio de WhatsApp nao configurado (defina META_WHATSAPP_TOKEN e "
            "META_WHATSAPP_PHONE_ID no .env)."
        )
    return token, phone_id


def _descrever_envio(payload):
    """'template pibachurch_escalado para 5528*****2102' -- pro log, sem o numero inteiro."""
    destino = payload.get("to") or ""
    destino = destino[:4] + "*****" + destino[-4:] if len(destino) > 8 else destino
    if payload.get("type") == "template":
        return f"template {payload['template']['name']} para {destino}"
    return f"texto livre para {destino}"


def _chamar_api(token, phone_id, payload):
    """Toda falha vai pro log (WARNING, aparece no log do Azure) com o motivo
    que a Meta devolveu -- quem chama (ex: o botao Notificar) so conta
    "falharam", entao sem isso o porque (template inexistente/nao aprovado,
    numero fora da lista de teste, token vencido...) se perdia."""
    url = f"https://graph.facebook.com/{_API_VERSAO}/{phone_id}/messages"
    try:
        resposta = requests.post(
            url,
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
            timeout=_TIMEOUT_SEGUNDOS,
        )
    except requests.RequestException as erro:
        current_app.logger.warning("WhatsApp nao enviado (%s): erro de rede: %s", _descrever_envio(payload), erro)
        raise WhatsappNaoEnviadoError(f"Falha ao enviar WhatsApp: {erro}") from erro

    if resposta.status_code >= 300:
        current_app.logger.warning("WhatsApp nao enviado (%s): Meta respondeu %s %s",
                                   _descrever_envio(payload), resposta.status_code, resposta.text[:1000])
        raise WhatsappNaoEnviadoError(f"Meta recusou o envio: {resposta.status_code} {resposta.text}")
    current_app.logger.info("WhatsApp enviado (%s).", _descrever_envio(payload))


def enviar_whatsapp(destinatario, corpo):
    """Envia uma mensagem de WhatsApp de texto livre.

    So funciona dentro da janela de 24h de atendimento (a pessoa precisa ter
    mandado mensagem pro numero antes) -- pra notificacao PROATIVA (a igreja
    avisando sem a pessoa ter escrito antes, que e o caso das notificacoes de
    escala), use enviar_whatsapp_template, que usa um Template aprovado pela
    Meta (regra da propria plataforma WhatsApp, nao e limitacao nossa).

    Levanta WhatsappNaoEnviadoError em qualquer falha.
    """
    token, phone_id = _config_ou_erro()

    numero_destino = normalizar_telefone(destinatario)
    if numero_destino is None:
        raise WhatsappNaoEnviadoError(f"Telefone invalido: {destinatario!r}")

    _chamar_api(token, phone_id, {
        "messaging_product": "whatsapp",
        "to": numero_destino.lstrip("+"),
        "type": "text",
        "text": {"body": corpo},
    })


MAX_MIDIA_BYTES = 16 * 1024 * 1024  # limite de audio do proprio WhatsApp


def baixar_midia(media_id):
    """(bytes, mime) de uma midia RECEBIDA (ex: audio da caixa de entrada).
    A Meta da so o id no webhook: primeiro pega a URL (vale poucos minutos),
    depois baixa com o mesmo token. Levanta WhatsappNaoEnviadoError."""
    token, _ = _config_ou_erro()
    cabecalho = {"Authorization": f"Bearer {token}"}
    try:
        info = requests.get(f"https://graph.facebook.com/{_API_VERSAO}/{media_id}", headers=cabecalho,
                            timeout=_TIMEOUT_SEGUNDOS)
        dados = info.json() if info.status_code < 300 else {}
        url = dados.get("url")
        if not url:
            raise WhatsappNaoEnviadoError(f"Meta nao devolveu a midia {media_id}: {info.status_code} {info.text[:300]}")
        if int(dados.get("file_size") or 0) > MAX_MIDIA_BYTES:
            raise WhatsappNaoEnviadoError("Midia maior que o limite.")
        resposta = requests.get(url, headers=cabecalho, timeout=_TIMEOUT_SEGUNDOS * 2, stream=True)
        if resposta.status_code >= 300:
            raise WhatsappNaoEnviadoError(f"Download da midia falhou: {resposta.status_code}")
        partes, total = [], 0
        for pedaco in resposta.iter_content(64 * 1024):
            total += len(pedaco)
            if total > MAX_MIDIA_BYTES:
                raise WhatsappNaoEnviadoError("Midia maior que o limite.")
            partes.append(pedaco)
    except (requests.RequestException, ValueError) as erro:
        raise WhatsappNaoEnviadoError(f"Falha ao baixar midia: {erro}") from erro
    mime = (dados.get("mime_type") or resposta.headers.get("Content-Type") or "application/octet-stream").split(";")[0]
    return b"".join(partes), mime.strip()[:100]


def trocar_foto_do_perfil(caminho_imagem, app_id=None):
    """Troca a foto de perfil do numero de WhatsApp Business (comando
    `flask whatsapp-foto-perfil`). A Meta nao aceita a imagem direto no
    perfil: primeiro sobe o arquivo pelo Resumable Upload do APP (precisa do
    id do app -- META_APP_ID ou descoberto pelo proprio token), que devolve um
    "handle", e o handle e o que vai no whatsapp_business_profile.

    Levanta WhatsappNaoEnviadoError em qualquer falha.
    """
    token, phone_id = _config_ou_erro()
    base =f"https://graph.facebook.com/{_API_VERSAO}"
    tipo = "image/png" if caminho_imagem.lower().endswith(".png") else "image/jpeg"
    with open(caminho_imagem, "rb") as arquivo:
        conteudo = arquivo.read()

    def _post_ou_erro(etapa, url, **kwargs):
        try:
            resposta = requests.post(url, timeout=_TIMEOUT_SEGUNDOS * 3, **kwargs)
        except requests.RequestException as erro:
            raise WhatsappNaoEnviadoError(f"{etapa}: {erro}") from erro
        if resposta.status_code >= 300:
            raise WhatsappNaoEnviadoError(f"{etapa}: {resposta.status_code} {resposta.text}")
        return resposta.json()

    app_id = app_id or current_app.config.get("META_APP_ID")
    if not app_id:
        try:
            resposta = requests.get(f"{base}/app", params={"access_token": token}, timeout=_TIMEOUT_SEGUNDOS)
            app_id = resposta.json().get("id") if resposta.status_code < 300 else None
        except (requests.RequestException, ValueError):
            app_id = None
        if not app_id:
            raise WhatsappNaoEnviadoError(
                "Nao deu pra descobrir o id do app pelo token -- passe --app-id (Configuracoes do app > "
                "Basico > ID do aplicativo) ou defina META_APP_ID."
            )

    sessao = _post_ou_erro("Abrir envio da imagem", f"{base}/{app_id}/uploads", params={
        "file_length": len(conteudo), "file_type": tipo, "access_token": token,
    })
    enviado = _post_ou_erro("Enviar a imagem", f"{base}/{sessao['id']}", data=conteudo, headers={
        "Authorization": f"OAuth {token}", "file_offset": "0",
    })
    _post_ou_erro("Trocar a foto do perfil", f"{base}/{phone_id}/whatsapp_business_profile",
                  headers={"Authorization": f"Bearer {token}"},
                  json={"messaging_product": "whatsapp", "profile_picture_handle": enviado["h"]})


def enviar_whatsapp_template(destinatario, nome_template, parametros):
    """Envia uma mensagem via Template aprovado pela Meta -- unico jeito de
    mandar WhatsApp PROATIVO (fora da janela de 24h), ver
    app/escala/routes.py::enviar_notificacoes_da_escala e afins.

    `parametros` e uma lista de strings, na ordem das variaveis {{1}},
    {{2}}... do corpo do template cadastrado no WhatsApp Manager.
    """
    token, phone_id = _config_ou_erro()

    numero_destino = normalizar_telefone(destinatario)
    if numero_destino is None:
        raise WhatsappNaoEnviadoError(f"Telefone invalido: {destinatario!r}")

    try:
        _reservar_template_do_dia()
    except WhatsappNaoEnviadoError:
        current_app.logger.warning("WhatsApp nao enviado (template %s): teto diario atingido.", nome_template)
        raise

    _chamar_api(token, phone_id, {
        "messaging_product": "whatsapp",
        "to": numero_destino.lstrip("+"),
        "type": "template",
        "template": {
            "name": nome_template,
            "language": {"code": "pt_BR"},
            "components": [{
                "type": "body",
                "parameters": [{"type": "text", "text": p} for p in parametros],
            }],
        },
    })
