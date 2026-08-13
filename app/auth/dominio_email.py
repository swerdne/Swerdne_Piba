"""Verifica se o dominio de um e-mail realmente aceita mensagens (registro MX).

So confirma que o DOMINIO existe e esta configurado para receber e-mail --
nao confirma que a CAIXA especifica existe (isso so o proprio envio, e o
clique no link de confirmacao, provam de fato). Usado em
app/auth/forms.py::RegisterForm.validate_email.
"""
import dns.resolver


def dominio_aceita_email(dominio):
    """True se o dominio tem registro MX (ou, na falta dele, um registro A --
    RFC 5321 permite entrega direta ao host do registro A quando nao ha MX).
    Erros de rede/timeout do NOSSO lado (nao do dominio) nao bloqueiam o
    cadastro -- só uma instabilidade momentanea de DNS nao deveria impedir
    alguem de se cadastrar com um e-mail legitimo.
    """
    try:
        respostas = dns.resolver.resolve(dominio, "MX", lifetime=5)
        return len(respostas) > 0
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        try:
            dns.resolver.resolve(dominio, "A", lifetime=5)
            return True
        except Exception:
            return False
    except Exception:
        return True
