"""Formularios Flask-WTF do modulo escala."""
from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed, FileRequired, FileSize
from wtforms import StringField, SelectField, SubmitField, DateField, TimeField, TextAreaField, HiddenField, FloatField, IntegerField
from wtforms.validators import DataRequired, InputRequired, Length, NumberRange, Optional, StopValidation, ValidationError
from wtforms.widgets import Select
from markupsafe import Markup

from app.escala.models import (
    DEPARTAMENTOS, CORES_DISPONIVEIS, TIPOS_ANEXO, TAMANHO_MAXIMO_ANEXO,
    TONS, TONS_MAIORES, TONS_MENORES, eh_tom_valido,
)


class _SelectDeTom(Select):
    """O widget do WTForms poe TODA opcao dentro de um <optgroup> quando ha
    grupos -- inclusive a vazia, que ficaria num grupo sem titulo. Tira esse
    primeiro grupo (sempre o da opcao vazia, ver TomField.iter_groups) pra
    ela aparecer solta no topo."""

    def __call__(self, field, **kwargs):
        html = str(super().__call__(field, **kwargs))
        html = html.replace('<optgroup label="">', "", 1).replace("</optgroup>", "", 1)
        return Markup(html)


class TomField(SelectField):
    """Dropdown com os 24 tons (maiores/menores em grupos), em vez de texto
    livre. `vazio` e o rotulo da opcao "sem tom" (ex: "Tom original").

    Tom ja salvo com outra grafia (A#, Db...) aparece num grupo proprio no
    topo, ja selecionado -- senao o select mostraria "sem tom" e o proximo
    salvar apagaria o tom da musica sem ninguem perceber."""

    def __init__(self, label=None, validators=None, vazio="Tom", **kwargs):
        self.vazio = vazio
        super().__init__(label, validators, choices={
            "": [("", vazio)],
            "Maiores": TONS_MAIORES,
            "Menores": TONS_MENORES,
        }, validate_choice=False, widget=_SelectDeTom(), **kwargs)

    def iter_groups(self):
        grupos = list(super().iter_groups())
        yield grupos[0]  # opcao vazia sempre primeiro (ver _SelectDeTom)
        if self.data and self.data not in TONS:
            yield ("Atual", self._choices_generator([(self.data, self.data)]))
        yield from grupos[1:]

    def pre_validate(self, form):
        if self.data and not eh_tom_valido(self.data):
            raise ValidationError("Escolha um tom da lista.")

# "" (vazio) = usa a cor padrao do departamento (Escala.cor_selecionada fica
# None) -- sempre a 1a opcao, pra nao forcar o usuario a escolher uma cor.
_CHOICES_COR = [("", "Cor do departamento (padrao)")] + [(chave, chave.capitalize()) for chave in CORES_DISPONIVEIS]


class EscalaForm(FlaskForm):
    nome = StringField("Nome da escala", validators=[DataRequired(), Length(max=80)])
    departamento = SelectField(
        "Departamento",
        choices=[(d, d) for d in DEPARTAMENTOS.keys()],
        validators=[DataRequired()],
    )
    data = DateField("Data do ensaio/evento", validators=[Optional()])
    horario = TimeField("Horario de inicio", validators=[Optional()])
    horario_fim = TimeField("Horario de fim", validators=[Optional()])
    cor = SelectField("Cor na lista e no calendario", choices=_CHOICES_COR, validators=[Optional()])
    submit = SubmitField("Criar escala")


class EditarEscalaForm(FlaskForm):
    nome = StringField("Nome da escala", validators=[DataRequired(), Length(max=80)])
    data = DateField("Data do ensaio/evento", validators=[Optional()])
    horario = TimeField("Horario de inicio", validators=[Optional()])
    horario_fim = TimeField("Horario de fim", validators=[Optional()])
    cor = SelectField("Cor na lista e no calendario", choices=_CHOICES_COR, validators=[Optional()])
    submit = SubmitField("Salvar")


class SelecionarMembroForm(FlaskForm):
    """Escala alguem ja cadastrado no diretorio da comunidade (ver app/comunidade)."""
    membro_id = SelectField("Pessoa", coerce=int, validators=[DataRequired()])
    submit = SubmitField("Adicionar")


class MoverForm(FlaskForm):
    destino_funcao_id = SelectField("Mover para", coerce=int, validators=[DataRequired()])
    submit = SubmitField("Mover")


class StatusForm(FlaskForm):
    status = SelectField(
        "Status",
        choices=[
            ("nao_notificado", "Nao notificado"),
            ("confirmado", "Confirmado"),
            ("presente", "Presente"),
            ("troca_solicitada", "Troca solicitada"),
        ],
        validators=[DataRequired()],
    )
    # Preenchidos so quando status == "troca_solicitada" (ver
    # escala.routes::atualizar_status) -- Optional() nos dois porque sugerir
    # substituto e explicar o motivo sao opcionais pra quem pede a troca.
    troca_motivo = TextAreaField("Motivo (opcional)", validators=[Optional(), Length(max=500)])
    troca_sugestao_membro_id = SelectField(
        "Sugerir substituto (opcional)", coerce=int, validators=[Optional()]
    )


class TrocaAprovarForm(FlaskForm):
    """Usado pelo lider/admin pra aprovar uma solicitacao de troca (ver
    escala.routes::aprovar_troca) -- escolhe quem assume a funcao. Vem
    pre-preenchido com a sugestao de quem pediu a troca, se houver, mas o
    lider pode trocar por qualquer outra pessoa do diretorio."""
    membro_id = SelectField("Quem assume a funcao", coerce=int, validators=[DataRequired()])
    submit = SubmitField("Aprovar troca")


class AcaoForm(FlaskForm):
    """Form vazio, usado so para validar o token CSRF em acoes simples (remover/notificar)."""
    pass


class FuncaoForm(FlaskForm):
    nome = StringField("Nome da funcao", validators=[DataRequired(), Length(max=80)])
    submit = SubmitField("Salvar")


class ItemRepertorioForm(FlaskForm):
    nome_musica = StringField("Nome da musica", validators=[DataRequired(), Length(max=150)])
    tom = TomField("Tom", validators=[Optional(), Length(max=10)])
    link = StringField("Link (cifra, video...)", validators=[Optional(), Length(max=500)])
    submit = SubmitField("Adicionar")


class EnsaioForm(FlaskForm):
    data = DateField("Data do ensaio", validators=[DataRequired(message="Informe a data do ensaio.")])
    horario = TimeField("Inicio", validators=[Optional()])
    horario_fim = TimeField("Fim", validators=[Optional()])
    local = StringField("Local (opcional)", validators=[Optional(), Length(max=120)])
    submit = SubmitField("Adicionar ensaio")


class AnexoForm(FlaskForm):
    arquivo = FileField(
        "Arquivo",
        validators=[
            FileRequired(message="Escolha um arquivo."),
            FileAllowed(list(TIPOS_ANEXO), "Formatos aceitos: PDF, imagem (JPG/PNG), Word ou texto."),
            FileSize(max_size=TAMANHO_MAXIMO_ANEXO, message="O arquivo deve ter no maximo 10 MB."),
        ],
    )
    # 0 = toda a equipe; senao, o id da Funcao (choices montadas na rota).
    funcao_id = SelectField("Para quem", coerce=int, validators=[Optional()])
    submit = SubmitField("Anexar")


class MusicaForm(FlaskForm):
    nome = StringField("Nome da musica", validators=[DataRequired(message="Informe o nome da musica."), Length(max=150)])
    artista = StringField("Artista / ministerio", validators=[Optional(), Length(max=120)])
    tom = TomField("Tom original", validators=[Optional(), Length(max=10)], vazio="Tom")
    tags = StringField("Tags (separadas por virgula)", validators=[Optional(), Length(max=300)])
    link = StringField("Link de referencia (video, cifra...)", validators=[Optional(), Length(max=500)])
    submit = SubmitField("Salvar")


class LetraProjecaoForm(FlaskForm):
    letra_projecao = TextAreaField("Letra para projecao", validators=[Optional(), Length(max=20000)])
    submit = SubmitField("Salvar projecao")


class CifraLouvorForm(FlaskForm):
    cifra_louvor = TextAreaField("Cifra para o louvor", validators=[Optional(), Length(max=30000)])
    # Preenchido pelo transpositor da tela quando a cifra muda de tom.
    tom = HiddenField(validators=[Optional(), Length(max=10)])
    submit = SubmitField("Salvar cifra")


class ItemDoBancoForm(FlaskForm):
    musica_id = SelectField("Musica", coerce=int, validators=[DataRequired(message="Escolha uma musica.")])
    momento = StringField("Momento", validators=[Optional(), Length(max=60)])
    # Vazio = usa o tom original da musica (ver escala.routes.adicionar_musica_do_banco).
    tom = TomField("Tom do dia", validators=[Optional(), Length(max=10)], vazio="Tom original")
    submit = SubmitField("Adicionar")


class ObservacoesRepertorioForm(FlaskForm):
    observacoes_repertorio = TextAreaField("Observacoes gerais", validators=[Optional(), Length(max=2000)])
    submit = SubmitField("Salvar observacoes")


class _Coordenada(FloatField):
    """Vazio = sem valor, nao "Not a valid float"."""

    def process_formdata(self, valuelist):
        if valuelist and (valuelist[0] or "").strip():
            super().process_formdata(valuelist)
        else:
            self.data = None


class _Metros(IntegerField):
    """Inteiro com erro em portugues ("Not a valid integer value" aparecia
    pra quem digitava 100,5 ou 1.000)."""

    def process_formdata(self, valuelist):
        texto = (valuelist[0] if valuelist else "") or ""
        texto = str(texto).strip()
        if not texto:
            self.data = None
            return
        try:
            self.data = int(texto)
        except ValueError:
            self.data = None
            raise ValueError("Use um número inteiro de metros, entre 30 e 2000.")


class _Preenchida:
    """Como DataRequired, mas 0 vale: DataRequired recusava latitude 0 (a
    linha do Equador passa pelo Amapa e pelo Para)."""

    def __init__(self, message):
        self.message = message

    def __call__(self, form, field):
        if field.data is None:
            raise StopValidation(self.message)


class LocalCheckinForm(FlaskForm):
    """Local do check-in por localizacao (Comunidade ou Ministerio, ver
    app/escala/checkin.py). Latitude/longitude vem da busca do endereco ou
    do botao "usar minha localizacao" (campos escondidos preenchidos pelo JS)."""
    endereco = StringField("Endereço", validators=[Optional(), Length(max=300)])
    latitude = _Coordenada("Latitude", validators=[_Preenchida("Escolha o local no mapa (busque o endereço ou use a sua localização)."),
                                                  NumberRange(min=-90, max=90)])
    longitude = _Coordenada("Longitude", validators=[_Preenchida("Escolha o local no mapa."),
                                                    NumberRange(min=-180, max=180)])
    raio_checkin_m = _Metros("Raio aceito (metros)", default=100,
                             validators=[InputRequired(message="Informe o raio em metros."),
                                         NumberRange(min=30, max=2000, message="Use um número inteiro de metros, entre 30 e 2000.")])


class ConfigEstatisticasForm(FlaskForm):
    """Ajustes das estatisticas de comparecimento do Ministerio (ver
    app/escala/estatisticas.py). InputRequired (e nao DataRequired) porque 0 vale."""
    tolerancia_atraso_min = IntegerField("Tolerância de atraso (minutos)", validators=[
        InputRequired(message="Informe os minutos."), NumberRange(min=0, max=60, message="Use de 0 a 60 minutos.")])
    alerta_faltas_seguidas = IntegerField("Avisar o líder após quantas faltas seguidas", validators=[
        InputRequired(message="Informe o número de faltas."), NumberRange(min=0, max=10, message="Use de 0 a 10 (0 desliga o aviso).")])
