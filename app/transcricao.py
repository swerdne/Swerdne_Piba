"""Fala -> texto pros audios recebidos no WhatsApp (Azure AI Speech).

Usa a "REST API for short audio" do Azure Speech: aceita direto o formato
das mensagens de voz do WhatsApp (OGG/OPUS), sem converter, ate 60 s de
audio. Camada gratuita (F0) cobre cerca de 5 h de audio por mes.

Liga com AZURE_SPEECH_KEY + AZURE_SPEECH_REGION (ex: "brazilsouth") -- ou
AZURE_SPEECH_ENDPOINT (https://<recurso>.cognitiveservices.azure.com) em
vez da regiao. Sem chave, `transcricao_ligada()` e False e o audio segue
como antes (fica na caixa de entrada pra lideranca ouvir).
"""
import requests
from flask import current_app

TIMEOUT_SEGUNDOS = 20
IDIOMA = "pt-BR"
_CAMINHO = "/speech/recognition/conversation/cognitiveservices/v1"


class TranscricaoIndisponivel(Exception):
    """Nao deu pra transcrever (sem config, servico fora, cota acabou...)."""


def transcricao_ligada():
    cfg = current_app.config
    return bool(cfg.get("AZURE_SPEECH_KEY") and (cfg.get("AZURE_SPEECH_REGION") or cfg.get("AZURE_SPEECH_ENDPOINT")))


def _url():
    cfg = current_app.config
    endpoint = (cfg.get("AZURE_SPEECH_ENDPOINT") or "").rstrip("/")
    if endpoint:
        return f"{endpoint}/stt{_CAMINHO}"
    return f"https://{cfg['AZURE_SPEECH_REGION']}.stt.speech.microsoft.com{_CAMINHO}"


def transcrever(conteudo, mime="audio/ogg"):
    """Texto falado no audio, ou None se nao havia fala reconhecivel
    (silencio, ruido, outro idioma). Levanta TranscricaoIndisponivel."""
    if not transcricao_ligada():
        raise TranscricaoIndisponivel("Transcricao nao configurada (AZURE_SPEECH_KEY / AZURE_SPEECH_REGION).")
    if "ogg" in (mime or "ogg"):
        tipo = "audio/ogg; codecs=opus"
    elif "wav" in mime:
        tipo = "audio/wav; codecs=audio/pcm; samplerate=16000"
    else:
        raise TranscricaoIndisponivel(f"Formato de audio nao suportado pela transcricao: {mime}")
    try:
        resposta = requests.post(
            _url(), params={"language": IDIOMA, "format": "simple"}, data=conteudo, timeout=TIMEOUT_SEGUNDOS,
            headers={"Ocp-Apim-Subscription-Key": current_app.config["AZURE_SPEECH_KEY"], "Content-Type": tipo,
                     "Accept": "application/json"},
        )
    except requests.RequestException as erro:
        raise TranscricaoIndisponivel(f"Azure Speech nao respondeu: {erro}") from erro
    if resposta.status_code >= 300:
        raise TranscricaoIndisponivel(f"Azure Speech recusou: {resposta.status_code} {resposta.text[:300]}")
    try:
        dados = resposta.json()
    except ValueError as erro:
        raise TranscricaoIndisponivel("Azure Speech devolveu resposta invalida.") from erro
    status = dados.get("RecognitionStatus")
    if status == "Success":
        return (dados.get("DisplayText") or "").strip() or None
    if status in ("NoMatch", "InitialSilenceTimeout", "BabbleTimeout"):
        return None  # sem fala que de pra entender
    raise TranscricaoIndisponivel(f"Azure Speech: {status}")
