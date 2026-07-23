"""Ponto de entrada da aplicacao."""
import os
from app import create_app

app = create_app(os.environ.get("FLASK_CONFIG", "default"))

if __name__ == "__main__":
    app.run()
