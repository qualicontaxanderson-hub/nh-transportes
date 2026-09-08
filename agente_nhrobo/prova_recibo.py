# -*- coding: utf-8 -*-
"""Prova do recibo: escreve de verdade, confere o conteudo, e prova as duas
regras que sao faceis de errar -- nao reescrever a toa, e nao mandar a si mesmo.
"""
import datetime as dt
import os
import sys
import tempfile
import time

BASE = tempfile.mkdtemp(prefix="prova-recibo-")
os.environ["NHROBO_HOME"] = os.path.join(BASE, "home")
sys.path.insert(0, os.path.abspath("agente_nhrobo"))
import nhrobo_agente as ag                                   # noqa: E402

raiz = os.path.join(BASE, "pasta do usuario")
os.makedirs(os.path.join(raiz, "sub"), exist_ok=True)

reg = ag.Registro(os.path.join(BASE, "home", "registro.json"))


def anota(nome, estado, motivo=None, raiz_=raiz, subpasta=""):
    caminho = os.path.join(raiz_, subpasta, nome)
    with open(caminho, "w", encoding="utf-8") as f:
        f.write(nome * 40)
    # envelhece: a varredura ignora arquivo mexido nos ultimos 5s (meia-copia)
    velho = time.time() - 60
    os.utime(caminho, (velho, velho))
    st = os.stat(caminho)
    sha = ag.Registro.hash_do_arquivo(caminho)
    reg.anotar(caminho, st, sha, estado, motivo, raiz=raiz_)
    return caminho


anota("extrato teste.ofx", "ok")
anota("extrato teste.xlsx", "ok")
anota("planilha da sub.xlsx", "ok", subpasta="sub")
anota("foto do comprovante.jpg", "recusado", "tipo de arquivo nao aceito")

# uma pasta VIZINHA: o recibo desta raiz nao pode listar arquivo dela
outra = os.path.join(BASE, "outra pasta")
os.makedirs(outra, exist_ok=True)
anota("nao deveria aparecer.ofx", "ok", raiz_=outra)

falhas = []


def checa(cond, msg):
    print(("OK   " if cond else "FALHA") + "  " + msg)
    if not cond:
        falhas.append(msg)


# ── 1. conectado ─────────────────────────────────────────────────────────────
snap = {"conexao": "conectado", "detalhe": "", "ultimo_ok": dt.datetime.now()}
ag.escrever_recibo(raiz, reg, snap)
alvo = os.path.join(raiz, ag.NOME_RECIBO)
checa(os.path.exists(alvo), "o recibo foi criado")
txt = open(alvo, encoding="utf-8").read()
print("\n" + "=" * 70)
print(txt)
print("=" * 70 + "\n")

checa("extrato teste.ofx" in txt, "lista o .ofx enviado")
checa("planilha da sub.xlsx" in txt, "lista o arquivo vindo de uma SUBPASTA")
checa("foto do comprovante.jpg" in txt, "lista o recusado")
checa("tipo de arquivo nao aceito" in txt, "diz o motivo da recusa")
checa("nao deveria aparecer" not in txt, "NAO lista arquivo de outra pasta vigiada")
checa("ENVIADOS (3)" in txt, "conta 3 enviados")
checa("NAO ENVIADOS (1)" in txt, "conta 1 recusado")
checa("o robo esta funcionando" in txt, "cabecalho diz que esta funcionando")
# em modo texto o Python ja traduziu \r\n para \n; so o binario prova.
checa(open(alvo, "rb").read().count(b"\r\n") > 20, "usa quebra de linha do Windows")
try:
    txt.encode("ascii")
    checa(True, "e ASCII puro (nao tem acento para o Bloco de Notas errar)")
except UnicodeEncodeError as e:
    checa(False, "e ASCII puro -- achei: %s" % e)

# ── 2. nao reescreve a toa ───────────────────────────────────────────────────
antes = os.path.getmtime(alvo)
time.sleep(1.1)
ag.escrever_recibo(raiz, reg, snap)
checa(os.path.getmtime(alvo) == antes, "sem novidade, NAO reescreve (nao acorda o Dropbox)")

# ── 3. novidade reescreve ────────────────────────────────────────────────────
anota("extrato novo.ofx", "ok")
ag.escrever_recibo(raiz, reg, snap)
checa(os.path.getmtime(alvo) != antes, "com arquivo novo, reescreve")
checa("extrato novo.ofx" in open(alvo, encoding="utf-8").read(), "o novo aparece")

# ── 4. envelheceu: reescreve so para a hora andar ────────────────────────────
velho = time.time() - (ag.RECIBO_IDADE_MAX + 60)
os.utime(alvo, (velho, velho))
ag.escrever_recibo(raiz, reg, snap)
checa(os.path.getmtime(alvo) > velho + 100, "passou de %d min, reescreve mesmo sem novidade"
      % (ag.RECIBO_IDADE_MAX // 60))

# ── 5. os avisos ─────────────────────────────────────────────────────────────
caiu = dt.datetime.now() - dt.timedelta(hours=2)
ag.escrever_recibo(raiz, reg, {"conexao": "sem_conexao", "detalhe": "", "ultimo_ok": caiu})
t = open(alvo, encoding="utf-8").read()
checa("sem conexao com o escritorio desde" in t, "sem internet: diz DESDE quando")
checa(caiu.strftime("%d/%m/%Y %H:%M") in t, "sem internet: mostra a hora certa")
checa("nao precisa fazer nada" in t, "sem internet: diz que nao precisa fazer nada")

ag.escrever_recibo(raiz, reg, {"conexao": "chave_invalida", "detalhe": "", "ultimo_ok": caiu})
t = open(alvo, encoding="utf-8").read()
checa("sem autorizacao" in t, "chave revogada: avisa")
checa("fale com o escritorio" in t, "chave revogada: manda falar com o escritorio")

# ── 6. o recibo NAO se envia ─────────────────────────────────────────────────
ag.escrever_recibo(raiz, reg, snap)
vistos = [os.path.basename(c) for c, _ in ag.arquivos_para_olhar(raiz)]
checa(ag.NOME_RECIBO not in vistos, "a varredura IGNORA o proprio recibo")
checa("extrato teste.ofx" in vistos, "a varredura continua vendo os arquivos de verdade")
checa("planilha da sub.xlsx" in vistos, "a varredura continua entrando na subpasta")

print("\n%d falha(s)" % len(falhas))
sys.exit(1 if falhas else 0)
