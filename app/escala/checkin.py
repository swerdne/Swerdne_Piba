"""Check-in por localizacao: "Presente" so com a pessoa no local.

O endereco de referencia (com latitude/longitude e o raio aceito) fica no
Ministerio ou, se o ministerio nao tiver o proprio, na Comunidade -- ver
local_do_checkin. No dia da escala, quem esta escalado toca em "Fazer
check-in" (Minha escala); o navegador manda a posicao do GPS e o servidor
confere a distancia (avaliar_checkin). Dentro do raio, todas as funcoes da
pessoa naquela escala viram "Presente" com hora/distancia guardadas
(Funcao.checkin_em/...); fora, nada muda.

O proprio escalado nao consegue mais marcar "Presente" na mao (so pelo
check-in). Lider/admin ainda pode marcar alguem presente manualmente (GPS
quebrado, celular sem bateria...) -- fica visivel na escala como "marcado
pelo lider", sem check-in.

Limite conhecido: a posicao vem do aparelho; um celular adulterado consegue
mentir o GPS. A checagem segura o uso normal (marcar de casa), nao fraude
deliberada.
"""
import math
from dataclasses import dataclass
from datetime import timedelta, timezone

RAIO_PADRAO_M = 100
RAIO_MINIMO_M = 30
RAIO_MAXIMO_M = 2000
# GPS com margem de erro maior que isso (dentro de predio, sem "localizacao
# precisa" ligada) nao serve pra afirmar onde a pessoa esta.
PRECISAO_MAXIMA_M = 150


@dataclass
class LocalCheckin:
    endereco: str
    latitude: float
    longitude: float
    raio_m: int
    origem: str  # "ministerio" ou "comunidade"


def _tem_coordenadas(doc):
    return doc is not None and doc.latitude is not None and doc.longitude is not None


def local_do_checkin(ministerio):
    """Local que vale pras escalas do ministerio (o dele, senao o da
    comunidade); None se nenhum dos dois foi cadastrado."""
    if _tem_coordenadas(ministerio):
        return LocalCheckin(ministerio.endereco or "", ministerio.latitude, ministerio.longitude,
                            ministerio.raio_checkin_m or RAIO_PADRAO_M, "ministerio")
    comunidade = ministerio.comunidade if ministerio else None
    if _tem_coordenadas(comunidade):
        return LocalCheckin(comunidade.endereco or "", comunidade.latitude, comunidade.longitude,
                            comunidade.raio_checkin_m or RAIO_PADRAO_M, "comunidade")
    return None


def distancia_m(lat1, lon1, lat2, lon2):
    """Distancia em metros entre dois pontos (formula de haversine)."""
    raio_terra = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * raio_terra * math.asin(math.sqrt(a))


def coordenadas_validas(latitude, longitude):
    return (
        latitude is not None and longitude is not None
        and -90 <= latitude <= 90 and -180 <= longitude <= 180
        and not (latitude == 0 and longitude == 0)
    )


def formatar_distancia(metros):
    return f"{metros / 1000:.1f} km".replace(".", ",") if metros >= 1000 else f"{round(metros)} m"


def situacao_do_dia(escala, hoje):
    """None se o check-in esta liberado hoje; senao, o motivo (texto)."""
    if escala.cancelada:
        return "Esta escala foi cancelada."
    if escala.data is None:
        return "Esta escala ainda não tem data definida."
    if escala.data > hoje:
        return f"O check-in abre no dia da escala ({escala.data.strftime('%d/%m')})."
    if escala.data < hoje:
        return "O dia desta escala já passou."
    return None


def avaliar_checkin(local, latitude, longitude, precisao):
    """(ok, distancia_m ou None, mensagem) -- so calcula, nao grava nada."""
    if local is None:
        return False, None, ("O endereço do local ainda não foi cadastrado. "
                             "Peça ao líder para cadastrar em “Local do check-in”.")
    if not coordenadas_validas(latitude, longitude):
        return False, None, "Não foi possível ler a sua localização. Tente de novo."
    if precisao is not None and precisao > PRECISAO_MAXIMA_M:
        return False, None, (f"A localização do celular está imprecisa (margem de {formatar_distancia(precisao)}). "
                             "Ative a localização precisa ou vá para perto de uma janela e tente de novo.")
    distancia = distancia_m(latitude, longitude, local.latitude, local.longitude)
    if distancia > local.raio_m:
        return False, distancia, (f"Você está a {formatar_distancia(distancia)} do local. "
                                  f"O check-in só é aceito a até {formatar_distancia(local.raio_m)}. "
                                  "Sua presença não foi confirmada.")
    return True, distancia, "Check-in feito! Sua presença foi confirmada."


def hora_local(momento):
    """"18:42" no horario de Brasilia (offset fixo, igual ao resto do app).
    Datas do Mongo voltam sem fuso -- sao UTC."""
    if momento is None:
        return ""
    if momento.tzinfo is not None:
        momento = momento.astimezone(timezone.utc).replace(tzinfo=None)
    return (momento - timedelta(hours=3)).strftime("%H:%M")


def status_sem_presente(form, status_atual, escala=None):
    """Tira "Presente" do <select> do proprio escalado: so o check-in marca
    (ver escala.routes.atualizar_status). Se ja esta presente, fica. Com o
    check-in desligado nesta escala, a pessoa marca sozinha."""
    if escala is not None and not checkin_ligado(escala, "escala"):
        return form
    if status_atual != "presente":
        form.status.choices = [c for c in form.status.choices if c[0] != "presente"]
    return form


# --- Onde o check-in vale (configuravel) ----------------------------------------
# Ministerio define o padrao (Ministerio.checkin_escala/checkin_ensaio) e cada
# Escala pode sobrepor (Escala.checkin_escala_modo/checkin_ensaio_modo).
PADRAO_POR_TIPO = {"escala": True, "ensaio": False, "culto": False}
MODOS = ("ligado", "desligado")


def checkin_padrao(ministerio, tipo):
    valor = getattr(ministerio, f"checkin_{tipo}", None) if ministerio else None
    return PADRAO_POR_TIPO[tipo] if valor is None else valor


def checkin_ligado(escala, tipo):
    """tipo: "escala" (o dia do evento) ou "ensaio"."""
    modo = getattr(escala, f"checkin_{tipo}_modo", None)
    if modo in MODOS:
        return modo == "ligado"
    return checkin_padrao(escala.ministerio, tipo)


def situacao_do_ensaio(ensaio, escala, hoje):
    """None se o check-in do ensaio esta liberado hoje; senao, o motivo."""
    if not checkin_ligado(escala, "ensaio"):
        return "O check-in não está ligado para os ensaios desta escala."
    if escala.cancelada:
        return "Esta escala foi cancelada."
    if ensaio.cancelado:
        return "Este ensaio foi cancelado."
    if ensaio.data > hoje:
        return f"O check-in abre no dia do ensaio ({ensaio.data.strftime('%d/%m')})."
    if ensaio.data < hoje:
        return "O dia deste ensaio já passou."
    return None


DIAS_SEMANA_LONGOS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]


def situacao_do_culto(ministerio, hoje):
    """None se o check-in de culto do ministerio esta aberto hoje; senao, o
    motivo. Culto = dias de `ministerio.dias_culto` (o dia inteiro, como o
    check-in de escala)."""
    if not checkin_padrao(ministerio, "culto"):
        return "O check-in de culto não está ligado neste ministério."
    dias = ministerio.dias_culto_efetivos
    if not dias:
        return "Os dias de culto ainda não foram definidos."
    if hoje.weekday() not in dias:
        return "Hoje não é dia de culto (" + ", ".join(DIAS_SEMANA_LONGOS[d] for d in dias) + ")."
    return None


def pode_fazer_checkin_culto(ministerio, usuario):
    """Quem participa do ministerio (papel de membro ou lider nele) ou tem
    autoridade de lider sobre ele (admin da comunidade)."""
    from app.ministerio.models import UsuarioMinisterio
    from app.ministerio.routes import _eh_lider_do_ministerio

    if UsuarioMinisterio.objects(ministerio_id=ministerio.id, usuario_id=usuario.id).first():
        return True
    return _eh_lider_do_ministerio(ministerio, usuario)
