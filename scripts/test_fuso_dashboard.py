# ============================================================
# TESTE READ-ONLY - fuso dos cards da Onda 1 do dashboard
#
# Bug: o servidor roda em UTC; dh_emissao das vendas esta em horario de
# BRASILIA. Com date.today() (data UTC), depois das 21h BRT o "hoje" virava
# o dia seguinte e os cards Vendas do Dia / Ranking / Recebimento zeravam.
#
# Parte A: logica pura (instantes fixos, nao depende do relogio da maquina).
# Parte B: banco real (SELECT COUNT/SUM) comparando janela UTC x janela BR.
# Nao altera NADA.
#
# As janelas vem de utils.fuso - o MESMO codigo que routes/bases.py chama em
# producao. Nada de reimplementar a logica aqui: isso nao provaria nada.
# ============================================================
import os
import sys
from datetime import datetime, date

import pytz
import pymysql

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.fuso import BRASILIA, hoje_brasilia, janelas_dia_mes  # noqa: E402

UTC = pytz.utc

CONN = dict(
    host="centerbeam.proxy.rlwy.net",
    port=56026,
    user="root",
    password="CYTzzRYLVmEJGDexxXpgepWgpvebdSrV",
    database="railway",
    charset="utf8mb4",
    cursorclass=pymysql.cursors.DictCursor,
    read_timeout=30, connect_timeout=15,
)


def janela_dia(d):
    """Janela do dia, direto do codigo de producao."""
    ini_dia, fim_dia, _, _ = janelas_dia_mes(d)
    return ini_dia, fim_dia


def janela_mes(d):
    """Janela do mes, direto do codigo de producao."""
    _, _, ini_mes, fim_mes = janelas_dia_mes(d)
    return ini_mes, fim_mes


def hoje_antigo(instante_utc):
    """O que date.today() retorna num servidor com relogio em UTC."""
    return instante_utc.astimezone(UTC).date()


def hoje_novo(instante_utc):
    """O que _hoje_brasilia() retorna, seja qual for o fuso do servidor."""
    return instante_utc.astimezone(BRASILIA).date()


falhas = []


def check(nome, ok, detalhe=""):
    print(f"  [{'OK ' if ok else 'FALHA'}] {nome}{('  ' + detalhe) if detalhe else ''}")
    if not ok:
        falhas.append(nome)


# ------------------------------------------------------------
# PARTE A - logica pura, instantes fixos
# ------------------------------------------------------------
print("\n=== PARTE A: logica de fuso (instantes fixos) ===\n")

CASOS = [
    # (descricao, instante UTC, data BR esperada)
    ("21:03 BRT (= 00:03 UTC do dia seguinte) -> ainda e o dia 23",
     UTC.localize(datetime(2026, 7, 24, 0, 3)), date(2026, 7, 23)),
    ("23:59 BRT -> ainda e o dia 23",
     UTC.localize(datetime(2026, 7, 24, 2, 59)), date(2026, 7, 23)),
    ("00:05 BRT -> ja e o dia 24",
     UTC.localize(datetime(2026, 7, 24, 3, 5)), date(2026, 7, 24)),
    ("meio-dia BRT -> dia 23 (fuso nao interfere)",
     UTC.localize(datetime(2026, 7, 23, 15, 0)), date(2026, 7, 23)),
    ("VIRADA DE MES: 31/07 21:30 BRT (= 01/08 00:30 UTC) -> ainda e 31/07",
     UTC.localize(datetime(2026, 8, 1, 0, 30)), date(2026, 7, 31)),
    ("VIRADA DE ANO: 31/12 22:00 BRT (= 01/01 01:00 UTC) -> ainda e 31/12",
     UTC.localize(datetime(2027, 1, 1, 1, 0)), date(2026, 12, 31)),
]

for desc, inst, esperado in CASOS:
    antigo, novo = hoje_antigo(inst), hoje_novo(inst)
    check(desc, novo == esperado, f"antigo(UTC)={antigo}  novo(BR)={novo}")

print("\n  Janelas SQL geradas no instante critico 00:03 UTC = 21:03 BRT de 23/07:")
inst = UTC.localize(datetime(2026, 7, 24, 0, 3))
for rotulo, d in (("ANTIGO (UTC)", hoje_antigo(inst)), ("NOVO (Brasilia)", hoje_novo(inst))):
    di, df = janela_dia(d)
    mi, mf = janela_mes(d)
    print(f"    {rotulo:>16}: dia [{di} .. {df})   mes [{mi} .. {mf})")

# A venda das 21:03 BRT so cai na janela do dia se o filtro usar a data BR.
venda = datetime(2026, 7, 23, 21, 3)   # dh_emissao gravado em horario de Brasilia
for rotulo, d in (("ANTIGO (UTC)", hoje_antigo(inst)), ("NOVO (Brasilia)", hoje_novo(inst))):
    di, df = janela_dia(d)
    dentro = di <= venda.strftime('%Y-%m-%d %H:%M:%S') < df
    check(f"venda das 21:03 dentro da janela do dia - {rotulo}",
          dentro if 'NOVO' in rotulo else not dentro,
          f"dentro={dentro}")

# Virada de mes: venda de 31/07 21:30 BRT tem que continuar no mes de JULHO.
inst_mes = UTC.localize(datetime(2026, 8, 1, 0, 30))
venda_mes = '2026-07-31 21:30:00'
for rotulo, d in (("ANTIGO (UTC)", hoje_antigo(inst_mes)), ("NOVO (Brasilia)", hoje_novo(inst_mes))):
    mi, mf = janela_mes(d)
    dentro = mi <= venda_mes < mf
    check(f"venda de 31/07 21:30 dentro da janela do mes - {rotulo}",
          dentro if 'NOVO' in rotulo else not dentro,
          f"mes [{mi} .. {mf})  dentro={dentro}")

# ------------------------------------------------------------
# PARTE B - banco real, instante de AGORA
# ------------------------------------------------------------
print("\n=== PARTE B: banco real (somente SELECT) ===\n")

agora = datetime.now(UTC)
d_utc, d_br = hoje_antigo(agora), hoje_novo(agora)
print(f"  agora UTC      : {agora.strftime('%Y-%m-%d %H:%M:%S')}   -> date.today() no servidor = {d_utc}")
print(f"  agora Brasilia : {agora.astimezone(BRASILIA).strftime('%Y-%m-%d %H:%M:%S')}   -> hoje_brasilia()       = {d_br}")
check("hoje_brasilia() de producao == data BR do instante atual",
      hoje_brasilia() == d_br, f"producao={hoje_brasilia()}  esperado={d_br}")
print(f"  fusos {'DIVERGEM (janela critica)' if d_utc != d_br else 'coincidem agora'}\n")

SQL = ("SELECT COUNT(*) AS notas, COALESCE(SUM(valor_total),0) AS total "
       "FROM vendas_xml WHERE situacao <> 'cancelada' "
       "AND dh_emissao >= %s AND dh_emissao < %s")

con = pymysql.connect(**CONN)
try:
    with con.cursor() as cur:
        for rotulo, d in (("ANTIGO (UTC)", d_utc), ("NOVO (Brasilia)", d_br)):
            di, df = janela_dia(d)
            cur.execute(SQL, (di, df))
            r = cur.fetchone()
            mi, mf = janela_mes(d)
            cur.execute(SQL, (mi, mf))
            rm = cur.fetchone()
            print(f"  {rotulo:>16}  DIA {di[:10]}: {r['notas']:>4} notas  R$ {float(r['total']):>12,.2f}"
                  f"   |  MES {mi[:7]}: {rm['notas']:>5} notas  R$ {float(rm['total']):>13,.2f}")

        # Vendas da faixa 21:00-23:59 do dia BR: as que o bug fazia sumir.
        di, df = janela_dia(d_br)
        cur.execute(
            "SELECT COUNT(*) AS notas, COALESCE(SUM(valor_total),0) AS total "
            "FROM vendas_xml WHERE situacao <> 'cancelada' "
            "AND dh_emissao >= %s AND dh_emissao < %s AND HOUR(dh_emissao) >= 21",
            (di, df))
        r21 = cur.fetchone()
        print(f"\n  Faixa 21h-23h59 do dia {d_br} (BR): {r21['notas']} notas, "
              f"R$ {float(r21['total']):,.2f} - some do card no calculo antigo.")

        # Ultima venda registrada, para conferir a mao.
        cur.execute("SELECT dh_emissao, valor_total FROM vendas_xml "
                    "WHERE situacao <> 'cancelada' ORDER BY dh_emissao DESC LIMIT 3")
        print("\n  Ultimas 3 vendas (dh_emissao, horario de Brasilia):")
        for r in cur.fetchall():
            print(f"    {r['dh_emissao']}  R$ {float(r['valor_total']):,.2f}")

        # A venda mais recente TEM que estar na janela do dia BR (se for de hoje).
        cur.execute("SELECT MAX(dh_emissao) AS ult FROM vendas_xml WHERE situacao <> 'cancelada'")
        ult = cur.fetchone()['ult']
        if ult and ult.date() == d_br:
            di, df = janela_dia(d_br)
            check("ultima venda (de hoje BR) cai na janela do dia - NOVO",
                  di <= ult.strftime('%Y-%m-%d %H:%M:%S') < df, f"ult={ult}")
        else:
            print(f"\n  (ultima venda {ult} nao e de hoje BR - assercao de banco pulada)")
finally:
    con.close()

print("\n" + ("=" * 60))
print("RESULTADO: TODOS OS TESTES PASSARAM" if not falhas
      else f"RESULTADO: {len(falhas)} FALHA(S): " + "; ".join(falhas))
print("=" * 60)
raise SystemExit(1 if falhas else 0)
