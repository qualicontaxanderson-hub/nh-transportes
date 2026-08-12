# -*- coding: utf-8 -*-
"""Prova: renderiza o TOPO REAL das 7 telas de Migracao a partir dos proprios
templates e mostra que o HTML gerado e o mesmo componente em todas.

Nao usa Flask (a maquina nao tem): monta um Environment Jinja com url_for e os
dados de cada tela stubados, e renderiza o trecho que vai do primeiro
{% set mig_titulo %} ate o {% include 'includes/nav_migracoes.html' %}.
"""
import io, os, re, hashlib, json

RAIZ = r"C:\Users\User\OneDrive\IA Downloads\nh-transportes\templates"
SAIDA = r"C:\Users\User\OneDrive\IA Downloads\nh-transportes\prova-topos-migracao.html"

import jinja2

TELAS = [
    ("Vendas",       "vendas/index.html",              dict(totais=dict(notas=1240, valor=98123.4, canceladas=3))),
    ("Compras",      "dfe_compras/index.html",         dict()),
    ("CT-e",         "dfe_ctes/index.html",            dict(totais=dict(ctes=328, frete=268701.82))),
    ("Estoque",      "estoque/index.html",             dict(totais=dict(leituras=60, descargas=53))),
    ("Conciliação",  "estoque/conciliacao.html",       dict()),
    ("Tempo Real",   "estoque/tempo_real.html",        dict(empresa_nome="POSTO NOVO HORIZONTE", um_empresa=False, agora_hm="22:58")),
    ("Pendente",     "estoque/pendente_descer.html",   dict(totais=dict(notas=0, litros=0))),
]

ROTAS = {
    "vendas.index": "/vendas", "vendas.classificar": "/vendas/classificar",
    "dfe_compras.compras": "/dfe/compras", "dfe_compras.capturar_agora": "#",
    "dfe_ctes.index": "/dfe/ctes", "estoque.index": "/estoque",
    "estoque.conciliacao": "/estoque/conciliacao", "estoque.tempo_real": "/estoque/tempo-real",
    "estoque.pendente_descer": "/estoque/pendente-descer",
}

env = jinja2.Environment(loader=jinja2.FileSystemLoader(RAIZ), autoescape=True)
env.globals["url_for"] = lambda ep, **kw: ROTAS.get(ep, "#")
env.filters["formatar_moeda"] = lambda v: "R$ %s" % ("{:,.2f}".format(float(v or 0))
                                                     .replace(",", "X").replace(".", ",").replace("X", "."))
env.filters["fmtnum"] = lambda v, c=0: "{:,.0f}".format(float(v or 0)).replace(",", ".")

INI = re.compile(r"\{%-?\s*set\s+mig_titulo")
FIM = "{% include 'includes/nav_migracoes.html' %}"

def topo_do_template(rel):
    """Recorta do template REAL o trecho que produz o topo."""
    src = io.open(os.path.join(RAIZ, rel), encoding="utf-8").read()
    m = INI.search(src)
    if not m:
        raise SystemExit("!! %s nao define mig_titulo" % rel)
    fim = src.index(FIM, m.start()) + len(FIM)
    return src[m.start():fim]

def normaliza(html):
    """Troca o que PODE variar (titulo, icone, acoes) por marcadores. O que
    sobrar tem de ser identico entre as telas — e essa a prova."""
    h = re.sub(r"<span class=\"mig-title__t\">.*?</span>", '<span class="mig-title__t">@TITULO@</span>', html, flags=re.S)
    h = re.sub(r'<i class="bi bi-[a-z0-9-]+"></i>\s*</span>\s*\n\s*<span class="mig-title__t">',
               '<i class="bi @ICONE@"></i></span><span class="mig-title__t">', h, flags=re.S)
    h = re.sub(r"<div class=\"mig-acoes\">.*?</div>", '<div class="mig-acoes">@ACOES@</div>', h, flags=re.S)
    h = re.sub(r"<(span|a) class=\"nav-link[^\"]*\"[^>]*>.*?</\1>", "@ABA@", h, flags=re.S)
    return re.sub(r"\s+", " ", h).strip()

# --- render ---------------------------------------------------------------
render, assinaturas = [], {}
for rotulo, rel, ctx in TELAS:
    html = env.from_string(topo_do_template(rel)).render(**ctx)
    corpo = html[html.index("<div class=\"mig-head\">"):] if "mig-head" in html else html
    render.append((rotulo, rel, corpo))
    assinaturas[rotulo] = hashlib.md5(normaliza(corpo).encode("utf-8")).hexdigest()[:12]

iguais = len(set(assinaturas.values())) == 1
print(json.dumps(assinaturas, indent=2, ensure_ascii=False))
print("ESTRUTURA IDENTICA NAS 7 TELAS:", iguais)

# CSS real do include (a mesma folha que o app serve)
css = io.open(os.path.join(RAIZ, "includes/nav_migracoes.html"), encoding="utf-8").read()
css = css[css.index("<style>") + 7:css.index("</style>")]

blocos = "\n".join(
    '<section class="tela"><div class="tela__rot">%s<code>templates/%s</code></div>'
    '<div class="fone"><div class="fone__tela">%s</div></div>'
    '<div class="assin">assinatura da estrutura: <b>%s</b></div></section>' % (r, rel, h, assinaturas[r])
    for r, rel, h in render)

esqueleto = normaliza(render[0][2])
veredito = ('<div class="ver ok"><b>As 7 telas produzem exatamente a mesma estrutura de topo.</b><br>'
            'Trocando título, ícone e ações por marcadores, o HTML das 7 vira a mesma string — '
            'mesma assinatura <code>%s</code>:<pre>%s</pre></div>'
            % (list(assinaturas.values())[0],
               esqueleto.split("<ul")[0].replace("&", "&amp;").replace("<", "&lt;"))) if iguais else \
           '<div class="ver nao"><b>DIVERGIU:</b> %s</div>' % assinaturas

io.open(SAIDA, "w", encoding="utf-8").write("""<!doctype html>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Prova — topo padrão das telas de Migração</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css">
<style>
*{box-sizing:border-box}
body{margin:0;padding:16px;background:#eef2f7;color:#1f2937;
     font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
h1{font-size:1.15rem;margin:0 0 .2rem;color:#07569C}
.sub{color:#6b7280;font-size:.85rem;margin:0 0 1rem;line-height:1.5}
.ver{border-radius:12px;padding:.8rem .9rem;margin-bottom:1.1rem;font-size:.88rem;line-height:1.5}
.ver.ok{background:#e8f5e9;border:1px solid #bcdcbe;color:#2e6b32}
.ver.nao{background:#fcebeb;border:1px solid #eebfbf;color:#a32d2d}
.ver pre{background:#fff;border:1px solid #cfe3d0;border-radius:8px;padding:.55rem .6rem;
  margin:.5rem 0 0;font-size:.68rem;line-height:1.5;color:#2f4f33;overflow-x:auto;white-space:pre-wrap;
  word-break:break-word}
.tela{margin-bottom:1.1rem}
.tela__rot{font-size:.8rem;font-weight:700;color:#07569C;margin-bottom:.35rem;
  display:flex;gap:.5rem;align-items:center;flex-wrap:wrap}
.tela__rot code{font-size:.72rem;font-weight:500;color:#6b7280;background:#fff;
  border:1px solid #dde3ec;border-radius:6px;padding:.05rem .35rem}
.fone{background:#fff;border:1px solid #dde3ec;border-radius:14px;
  box-shadow:0 1px 3px rgba(16,45,80,.08),0 4px 12px rgba(16,45,80,.06);overflow:hidden}
.fone__tela{padding:14px}
.assin{font-size:.72rem;color:#6b7280;margin-top:.3rem}
.assin b{font-family:ui-monospace,monospace;color:#1D63A5}
/* Guia vermelha no ponto onde o TEXTO do titulo comeca (14px de padding +
   2.1rem do icone + .6rem do gap). Se os 7 titulos nascem no mesmo x, a guia
   encosta em todos no mesmo lugar. */
.fone__tela{position:relative}
.fone__tela::after{content:"";position:absolute;top:0;bottom:0;
  left:calc(14px + 2.1rem + .6rem);width:0;border-left:1px dashed rgba(200,40,40,.55);
  pointer-events:none}
/* reset minimo do Bootstrap para .nav (o app ja carrega o Bootstrap inteiro) */
.nav{display:flex;flex-wrap:wrap;padding-left:0;margin-bottom:0;list-style:none}
.nav-link{display:block;text-decoration:none}
/* ---- daqui pra baixo: CSS REAL, copiado de includes/nav_migracoes.html ---- */
%s
</style>
<h1>Prova — topo padrão das telas de Migração</h1>
<p class="sub">Cada bloco abaixo foi <b>renderizado a partir do template real</b> (Jinja), com o CSS real
de <code>includes/nav_migracoes.html</code>. Nenhum HTML foi escrito à mão para esta página.</p>
%s
%s
""" % (css, veredito, blocos))

print("gerado:", SAIDA)
