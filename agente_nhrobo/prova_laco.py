# -*- coding: utf-8 -*-
"""Prova que o LACO do worker escreve o recibo — inclusive quando da errado.

prova_recibo.py testa a funcao. Esta testa a chamada: que o recibo sai a cada
rodada do worker de verdade, e sai TAMBEM quando a chave e recusada -- que e
justamente a hora em que a pessoa vai olhar a pasta.

Nao passa pelo main(): a trava de instancia unica barraria, porque o agente de
verdade da maquina esta rodando. Aqui se instancia o Worker direto, que e o
mesmo codigo do laco.
"""
import json
import os
import sys
import tempfile
import time

BASE = tempfile.mkdtemp(prefix="prova-laco-")
os.environ["NHROBO_HOME"] = os.path.join(BASE, "home")
os.makedirs(os.environ["NHROBO_HOME"], exist_ok=True)
sys.path.insert(0, os.path.abspath("agente_nhrobo"))
import nhrobo_agente as ag                                   # noqa: E402

pasta = os.path.join(BASE, "pasta do usuario")
os.makedirs(pasta, exist_ok=True)
with open(os.path.join(pasta, "um extrato.ofx"), "w") as f:
    f.write("conteudo de teste")

# Chave falsa de proposito: o servidor devolve 401, o agente entra em
# "chave_invalida" e NAO manda nada para lugar nenhum. E o estado em que o
# recibo mais importa.
with open(ag.CONFIG_PATH, "w", encoding="utf-8") as f:
    json.dump({"servidor": ag.SERVIDOR_PADRAO, "chave": "0" * 64,
               "pastas": [pasta], "intervalo_seg": 60}, f)

falhas = []


def checa(cond, msg):
    print(("OK   " if cond else "FALHA") + "  " + msg)
    if not cond:
        falhas.append(msg)


estado = ag.Estado()
worker = ag.Worker(estado)
worker.start()

alvo = os.path.join(pasta, ag.NOME_RECIBO)
for _ in range(40):                       # ate 20s esperando a 1a rodada
    if os.path.exists(alvo):
        break
    time.sleep(0.5)
worker.parar()
worker.join(timeout=10)

checa(os.path.exists(alvo), "o laco escreveu o recibo sozinho")
if os.path.exists(alvo):
    txt = open(alvo, encoding="utf-8").read()
    print("\n" + "-" * 66)
    print(txt[:txt.find("NAO ACHOU")])
    print("-" * 66 + "\n")
    checa("Conferido agora:" in txt, "tem a hora da conferencia")
    checa("sem autorizacao" in txt or "sem conexao" in txt,
          "com chave recusada, o recibo AVISA em vez de mentir")
    checa("ENVIADOS (0)" in txt, "nao inventa envio que nao houve")
    checa("um extrato.ofx" not in txt, "o arquivo nao enviado NAO aparece como enviado")

# o arquivo do usuario continua intacto e no lugar
checa(os.path.exists(os.path.join(pasta, "um extrato.ofx")),
      "o arquivo do usuario continua onde estava")

print("\n%d falha(s)" % len(falhas))
sys.exit(1 if falhas else 0)
