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
_SEQ = [0]


def linha(tipo, dia, rotulo, detalhe, valor, saldo, resumo=False, conferido=False,
          falta=0.0, vinculos=None, fora=False, mes=8):
    _SEQ[0] += 1
    return dict(tipo=tipo, data=date(2026, mes, dia), rotulo=rotulo, detalhe=detalhe,
                valor=valor, saldo=saldo, resumo=resumo, id=_SEQ[0],
                conferido=(conferido if tipo == 'nota' else None),
                falta=falta, coberta=(falta <= 0.005),
                parcial=(0.005 < falta < valor - 0.005),
                vinculos=(vinculos or []), fora_periodo=fora)


# O periodo do exemplo comeca no proprio corte, entao ninguem tem saldo
# anterior — se tivesse, a foto estaria mostrando algo impossivel.
DADOS = [
    dict(fornecedor_id=7, nome="TDC DISTRIBUIDORA DE COMBUSTIVEIS LTDA",
         cnpj="11.111.111/0001-11", saldo_anterior=0.0,
         comprado=77500.0, pago=80000.0, saldo_final=2500.0, notas_total=2, notas_ok=1, antes=None, saldo_com_antes=None,
         sobra=2500.0, descoberto=0.0, notas_abertas=0,
         linhas=[
             linha("pagamento", 3, "Pagamento", "TED TT WORK SERVICOS", 50000, 50000),
             linha("nota", 3, "NF-e nº 1047/1", "POSTO NOVO HORIZONTE GOIATUBA", 50000, 0, conferido=True),
             linha("pagamento", 10, "Pagamento", "TED TT WORK SERVICOS", 30000, 30000),
             linha("nota", 12, "NF-e nº 1090/1", "POSTO NOVO HORIZONTE GOIATUBA", 27500, 2500, True),
         ]),
    dict(fornecedor_id=5, nome="DISTRIBUIDORA TABOCAO LTDA - EM RECUPERACAO JUDICIAL",
         cnpj="02.284.585/0001-44", saldo_anterior=0.0,
         comprado=31630.0, pago=31630.0, saldo_final=0.0, notas_total=3, notas_ok=3,
         sobra=0.0, descoberto=0.0, notas_abertas=0,
         antes=None, _antes_desativado=dict(total=23200.0, lancamentos=[
             dict(data=date(2026, 7, 30), valor=8700.0, descricao="PIX DISTRIBUIDORA TABOCAO"),
             dict(data=date(2026, 7, 28), valor=14500.0, descricao="PIX DISTRIBUIDORA TABOCAO")]),
         saldo_com_antes=None,
         linhas=[
             linha("pagamento", 28, "Pagamento", "PIX DISTRIBUIDORA TABOCAO", 14500, 14500, fora=True, mes=7),
             linha("pagamento", 30, "Pagamento", "PIX DISTRIBUIDORA TABOCAO", 8700, 23200, fora=True, mes=7),
             linha("nota", 1, "NF-e nº 838/2", "POSTO NOVO HORIZONTE GOIATUBA", 8700, 14500, conferido=True,
                   vinculos=[dict(id=101, data=date(2026, 7, 30), valor=8700.0,
                                  descricao="PIX DISTRIBUIDORA TABOCAO")]),
             linha("nota", 1, "NF-e nº 847/2", "POSTO NOVO HORIZONTE GOIATUBA", 14500, 0, conferido=True,
                   vinculos=[dict(id=102, data=date(2026, 7, 28), valor=14500.0,
                                  descricao="PIX DISTRIBUIDORA TABOCAO")]),
             linha("pagamento", 10, "Pagamento", "Pagamento Pix 02.284.585 0001-44", 8430, 8430),
             linha("nota", 10, "NF-e nº 1047/2", "POSTO NOVO HORIZONTE GOIATUBA", 8430, 0, conferido=True),
         ]),
    dict(fornecedor_id=12, nome="ZILLI COMERCIO DE PNEUS LTDA",
         cnpj="18.910.548/0001-34", saldo_anterior=0.0,
         comprado=2.0, pago=0.0, saldo_final=-2.0, notas_total=1, notas_ok=0, antes=None, saldo_com_antes=None,
         sobra=0.0, descoberto=2.0, notas_abertas=1,
         linhas=[linha("nota", 11, "NF-e nº 215772/1", "POSTO NOVO HORIZONTE GOIATUBA", 2, -2, falta=2)]),
]

CTX = dict(
    dados=DADOS,
    totais=dict(comprado=109132.0, pago=111630.0, saldo=2498.0, orfas=13890.5,
                notas=6, notas_ok=4, descoberto=2.0, sobra=2500.0),
    orfas=[dict(emit_cnpj="44248274000114", emit_nome="DISTRIBUIDORA EXEMPLO S/A",
                notas=2, total=13890.5, ultima=datetime(2026, 8, 11, 9, 2))],
    duplicados=[],
    sem_cnpj=[dict(razao_social="OFICINA DO ZE"), dict(razao_social="BORRACHARIA CENTRAL")],
    empresas=[dict(id=1, nome="POSTO NOVO HORIZONTE GOIATUBA"), dict(id=2, nome="NH TRANSPORTES")],
    fornecedores=[dict(id=7, razao_social="TDC DISTRIBUIDORA DE COMBUSTIVEIS LTDA"),
                  dict(id=12, razao_social="ZILLI COMERCIO DE PNEUS LTDA")],
    data_inicio="2026-08-01", data_fim="2026-08-12",
    cliente_ids=[], fornecedor_ids=[],
    corte="2026-08-01", puxou_pro_corte=False, vinculo_pronto=True, pre_corte_ini="2026-06-02",
    janela=dict(primeira=datetime(2026, 8, 1, 7, 40),
                ultima=datetime(2026, 8, 11, 15, 15), notas=43),
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
  var _p = document.querySelectorAll('#cfd .forn')[1];
  if (_p) { _p.querySelector('.forn__corpo').style.display = 'block'; _p.classList.add('aberto'); }
</script>
""" % (estilos, conteudo))

print("gerado:", SAIDA)
