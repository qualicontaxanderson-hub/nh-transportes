# Adicione este trecho em app.py (após os imports e após registrar blueprints)
from flask import url_for as flask_url_for, current_app

@app.context_processor
def inject_helpers():
    """
    Mantém registered_blueprints (já existente) e adiciona safe_url_for()
    para construir URLs tentando múltiplos endpoints e detectando nomes
    de parâmetro esperados pelas rules.
    Uso no template:
      {{ safe_url_for(['fretes.importar_pedido','pedidos.importar_pedido'], pedido_id=frete.id, id=frete.id) }}
    Ele tentará cada endpoint e retornará a primeira URL válida; caso nenhum
    funcione retorna '#'.
    """
    # registered_blueprints já é injetado por outro context_processor; mantemos compatibilidade
    def safe_url_for(candidates, **kwargs):
        try:
            for ep in candidates:
                # localizar rules do endpoint
                rules = [r for r in current_app.url_map.iter_rules() if r.endpoint == ep]
                if not rules:
                    continue
                rule = rules[0]
                # nomes de argumentos esperados pela rule
                expected = set(rule.arguments or [])
                # requer que todos os expected estejam presentes em kwargs
                if expected and not expected.issubset(set(kwargs.keys())):
                    continue
                # montar args que este endpoint aceita (interseção)
                args = {k: v for k, v in kwargs.items() if k in expected}
                # chamar url_for com os args corretos
                return flask_url_for(ep, **args) if args or not expected else flask_url_for(ep)
        except Exception:
            pass
        return '#'
    return dict(safe_url_for=safe_url_for)
