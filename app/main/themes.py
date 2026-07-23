"""Presets de tema do Dashboard.

Cada chave produz um conjunto completo de classes Tailwind. As classes ficam
sempre como strings literais aqui (nunca montadas via f-string/concatenacao no
template) para o scanner do Tailwind conseguir encontra-las e compilar o CSS
correspondente -- ver a diretiva @source em app/static/css/input.css.
"""

THEMES = {
    "indigo": {
        "label": "Claro",
        "page_bg": "bg-gray-50",
        "header_bg": "bg-white",
        "header_border": "border-gray-100",
        "card_bg": "bg-white",
        "card_bg_hover": "hover:bg-gray-50",
        "card_border": "border-gray-100",
        "text_primary": "text-gray-900",
        "text_secondary": "text-gray-500",
        "accent_bg": "bg-indigo-600",
        "accent_bg_hover": "hover:bg-indigo-700",
        "accent_text": "text-indigo-600",
        "accent_border": "border-indigo-600",
        "accent_soft_bg": "bg-indigo-50",
        "accent_soft_bg_strong": "bg-indigo-100",
        "swatch": "bg-indigo-600",
        "placeholder": "placeholder-gray-400",
        "focus_ring": "focus:ring-indigo-600",
        "secondary_bg": "bg-gray-100",
        "secondary_bg_hover": "hover:bg-gray-200",
        "secondary_text": "text-gray-900",
        "icon_hover": "group-hover:text-gray-900",
        "text_hover": "hover:text-gray-900",
    },
    "escuro": {
        "label": "Escuro",
        "page_bg": "bg-gray-950",
        "header_bg": "bg-gray-900",
        "header_border": "border-gray-800",
        "card_bg": "bg-gray-900",
        "card_bg_hover": "hover:bg-gray-800/70",
        "card_border": "border-gray-800",
        "text_primary": "text-white",
        "text_secondary": "text-gray-400",
        "accent_bg": "bg-indigo-500",
        "accent_bg_hover": "hover:bg-indigo-400",
        "accent_text": "text-indigo-400",
        "accent_border": "border-indigo-500",
        "accent_soft_bg": "bg-gray-800",
        "accent_soft_bg_strong": "bg-gray-800",
        "swatch": "bg-gray-900",
        "placeholder": "placeholder-gray-500",
        "focus_ring": "focus:ring-indigo-500",
        "secondary_bg": "bg-gray-800",
        "secondary_bg_hover": "hover:bg-gray-700",
        "secondary_text": "text-white",
        "icon_hover": "group-hover:text-white",
        "text_hover": "hover:text-white",
    },
}

TEMA_PADRAO = "indigo"


def obter_tema(chave):
    return THEMES.get(chave, THEMES[TEMA_PADRAO])
