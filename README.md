# Meu Projeto Flask

Projeto back-end em Flask com Application Factory, Blueprints, MVC e testes.

## Como rodar

```bash
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt

# inicializa o banco
flask --app run db init
flask --app run db migrate -m "inicial"
flask --app run db upgrade

# executa
flask --app run run
```

## Testes

```bash
pytest
```
