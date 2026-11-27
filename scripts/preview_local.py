"""Servidor de pre-visualizacao local com banco FALSO (mongomock em memoria),
pra conferir telas sem tocar no banco de producao do .env.

    venv/Scripts/python.exe scripts/preview_local.py

Cria a conta teste@exemplo.com / senha123 com uma comunidade, um ministerio
e uma escala de hoje. Tudo some quando o servidor para.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402

app = create_app("testing")
app.config["RATELIMIT_ENABLED"] = False

with app.app_context():
    db.create_all()
    c = app.test_client()
    c.post("/auth/register", data={"username": "Teste", "email": "teste@exemplo.com",
                                   "password": "senha123", "confirm": "senha123"})
    c.post("/comunidade/nova", data={"nome": "Igreja Exemplo", "descricao": "Comunidade de teste"})
    from app.comunidade.models import Comunidade
    from app.ministerio.models import Ministerio
    com = Comunidade.objects.first()
    if com:
        c.post(f"/ministerio/comunidade/{com.id}/nova", data={"nome": "Louvor"})
    mins = Ministerio.objects.first()
    print("comunidade:", com and com.id, "ministerio:", mins and mins.id, "hoje:", date.today())

app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5055")), debug=False, use_reloader=False)
