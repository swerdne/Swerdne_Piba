"""Tools MCP do editor de vídeo, agrupadas por assunto.

Cada módulo define funções async comuns (testáveis diretamente) e uma função
``register(mcp)`` que as publica no servidor. As docstrings viram a descrição
da tool que o modelo lê pra decidir quando chamá-la — mantenha-as completas.
"""

from mcp.server.fastmcp import FastMCP

from . import audio, editing, effects, export, info


def register_all(mcp: FastMCP) -> None:
    for module in (info, editing, audio, effects, export):
        module.register(mcp)
