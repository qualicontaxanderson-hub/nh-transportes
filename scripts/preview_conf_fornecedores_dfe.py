# -*- coding: utf-8 -*-
"""Preview do relatorio Fornecedores x Compras DFe SEM Flask.

Renderiza os blocos `styles` e `content` do template real com dados de exemplo
e grava um HTML autonomo. Serve pra conferir o layout (inclusive no celular)
antes do deploy — nesta maquina nao ha Flask pra subir o app.
"""
import io, os, re
from datetime import date, datetime

import jinja2

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TPL = os.path.join(RAIZ, "templates", "relatorios", "conf_fornecedores_dfe.html")
SAIDA = os.path.join(RAIZ, "preview-conf-fornecedores-dfe.html")

ROTAS = {"index": "/", "conf_fornecedores_dfe.conf_fornecedores_dfe": "/relatorios/conf_fornecedores_dfe"}


def moeda(v):
    return "R$ " + "{:,.2f}".format(float(v or 0)).replace(",", "X").replace(".", ",").replace("X", ".")


def bloco(src, nome):
    padrao = r"\{%\s*block\s+" + nome + r"\s*%\}(.*?)\{%\s*endblock\s*%\}"
    return re.search(padrao, src, re.S).group(1)


# ---------- dados de exemplo (o caso que o Anderson descreveu) ----------
def linha(tipo, dia, rotulo, detalhe, valor, saldo, resumo=False):
    return dict(tipo=tipo, data=date(2026, 8, dia), rotulo=rotulo, detalhe=detalhe,
                valor=valor, saldo=saldo, resumo=resumo)


DADOS = [
    dict(fornecedor_id=7, nome="TDC DISTRIBUIDORA DE COMBUSTIVEIS LTDA",
         cnpj="11.111.111/0001-11", saldo_anterior=8000.0,
         comprado=77500.0, pago=80000.0, saldo_final=10500.0,
         linhas=[
             linha("pagamento", 3, "Pagamento", "TED TT WORK SERVICOS", 50000, 58000),
             linha("nota", 3, "NF-e nº 1047/1", "POSTO NOVO HORIZONTE GOIATUBA", 50000, 8000),
             linha("pagamento", 10, "Pagamento", "TED TT WORK SERVICOS", 30000, 38000),
             linha("nota", 12, "NF-e nº 1090/1", "POSTO NOVO HORIZONTE GOIATUBA", 27500, 10500, True),
         ]),
    dict(fornecedor_id=12, nome="ZILLI COMERCIO DE PNEUS LTDA",
         cnpj="18.910.548/0001-34", saldo_anterior=0.0,
         comprado=2.0, pago=0.0, saldo_final=-2.0,
         linhas=[linha("nota", 11, "NF-e nº 215772/1", "POSTO NOVO HORIZONTE GOIATUBA", 2, -2)]),
    dict(fornecedor_id=21, nome="AUTO POSTO IRMAOS SILVA LTDA",
         cnpj="09.222.333/0001-70", saldo_anterior=-4300.0,
         comprado=0.0, pago=0.0, saldo_final=-4300.0, linhas=[]),
]

CTX = dict(
    dados=DADOS,
    totais=dict(comprado=77502.0, pago=80000.0, saldo=4198.0, orfas=13890.5),
    orfas=[dict(emit_cnpj="44248274000114", emit_nome="DISTRIBUIDORA EXEMPLO S/A",
                notas=2, total=13890.5, ultima=datetime(2026, 8, 11, 9, 2))],
    duplicados=[],
    sem_cnpj=[dict(razao_social="OFICINA DO ZE"), dict(razao_social="BORRACHARIA CENTRAL")],
    empresas=[dict(id=1, nome="POSTO NOVO HORIZONTE GOIATUBA"), dict(id=2, nome="NH TRANSPORTES")],
    fornecedores=[dict(id=7, razao_social="TDC DISTRIBUIDORA DE COMBUSTIVEIS LTDA"),
                  dict(id=12, razao_social="ZILLI COMERCIO DE PNEUS LTDA")],
    data_inicio="2026-08-01", data_fim="2026-08-12",
    cliente_ids=[], fornecedor_ids=[],
)

src = io.open(TPL, encoding="utf-8").read()
env = jinja2.Environment(autoescape=True)
env.globals["url_for"] = lambda ep, **kw: ROTAS.get(ep, "#")
env.filters["formatar_moeda"] = moeda

estilos = env.from_string(bloco(src, "styles")).render(**CTX)
conteudo = env.from_string(bloco(src, "content")).render(**CTX)

io.open(SAIDA, "w", encoding="utf-8").write("""<!doctype html>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Preview — Fornecedores x Compras DFe</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css">
<style>body{background:#eef2f7;margin:0 auto;padding:14px;max-width:430px}</style>
%s
%s
<script>
  /* So no preview: abre o 1o fornecedor pra a linha do tempo aparecer na foto. */
  var _p = document.querySelector('#cfd .forn');
  if (_p) { _p.querySelector('.forn__corpo').style.display = 'block'; _p.classList.add('aberto'); }
</script>
""" % (estilos, conteudo))

print("gerado:", SAIDA)
