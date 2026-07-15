# -*- coding: utf-8 -*-
"""
Log de OBSERVABILIDADE da captura de DFe: uma linha por RODADA/CONSULTA.

Existe porque dfe_nsu guarda UMA linha por cliente, SOBRESCRITA a cada rodada:
depois do fato nao ha como saber o que cada ciclo (00:05, 03:05, ...) fez. Pior,
uma rodada PULADA pela trava de cota nao deixava rastro nenhum.

Aqui grava-se TUDO, inclusive o que nao aconteceu:
  evento='consulta'     -> foi a SEFAZ; tem c_stat (138/137/656/...) e x_motivo COMPLETO
  evento='pulado_cota'  -> nem consultou: proximo_permitido ainda no futuro
  evento='pulado_lock'  -> outro worker/deploy ja estava capturando (GET_LOCK)
  evento='erro'         -> excecao (rede, certificado, timeout do subprocess...)

origem = 'agendador' | 'manual' | 'cli'  (quem disparou a rodada)

Serve para os DOIS drivers do projeto (pymysql na captura, mysql-connector no
agendador): ambos usam placeholder %s, entao o mesmo SQL vale para os dois. As
funcoes recebem um CURSOR ja aberto -- quem chama controla conexao/commit.

Gravar log NUNCA pode derrubar a captura: registrar() e best-effort e engole
qualquer excecao (devolve False).
"""

# x_motivo: a xMotivo da SEFAZ e spec'd em ate 255; 300 da folga e evita que a
# mensagem volte a ser cortada justo onde ela diz qual ultNSU usar.
DDL_CONSULTA_LOG = """
CREATE TABLE IF NOT EXISTS dfe_consulta_log (
    id            BIGINT AUTO_INCREMENT PRIMARY KEY,
    momento       DATETIME     NOT NULL,
    origem        VARCHAR(12)  NOT NULL,
    evento        VARCHAR(14)  NOT NULL,
    cliente_id    INT          NULL,
    cnpj          CHAR(14)     NULL,
    ult_nsu_env   BIGINT       NULL,
    c_stat        VARCHAR(6)   NULL,
    x_motivo      VARCHAR(300) NULL,
    ret_ult_nsu   BIGINT       NULL,
    ret_max_nsu   BIGINT       NULL,
    docs          INT          NOT NULL DEFAULT 0,
    notas         INT          NOT NULL DEFAULT 0,
    eventos       INT          NOT NULL DEFAULT 0,
    lote          INT          NULL,
    detalhe       VARCHAR(300) NULL,
    criado_em     TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY ix_momento (momento),
    KEY ix_cstat (c_stat),
    KEY ix_origem_evento (origem, evento)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

_SQL_LOG = (
    "INSERT INTO dfe_consulta_log "
    "(momento, origem, evento, cliente_id, cnpj, ult_nsu_env, c_stat, x_motivo, "
    " ret_ult_nsu, ret_max_nsu, docs, notas, eventos, lote, detalhe) "
    "VALUES (NOW(),%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
)

ORIGENS = ('agendador', 'manual', 'cli')


def garantir_tabela(cur):
    """CREATE TABLE IF NOT EXISTS. Best-effort: nao derruba quem chama."""
    try:
        cur.execute(DDL_CONSULTA_LOG)
        return True
    except Exception:
        return False


def _corta(v, n):
    return None if v is None else str(v)[:n]


def registrar(cur, origem, evento, cliente_id=None, cnpj=None, ult_nsu_env=None,
              c_stat=None, x_motivo=None, ret_ult_nsu=None, ret_max_nsu=None,
              docs=0, notas=0, eventos=0, lote=None, detalhe=None):
    """Grava UMA linha do log. Best-effort: devolve True/False, nunca levanta.

    Nao faz commit -- quem chama decide (a captura ja comita a cada lote; o
    agendador usa conexao autocommit)."""
    try:
        cur.execute(_SQL_LOG, (
            _corta(origem, 12), _corta(evento, 14), cliente_id, _corta(cnpj, 14),
            ult_nsu_env, _corta(c_stat, 6), _corta(x_motivo, 300),
            ret_ult_nsu, ret_max_nsu,
            int(docs or 0), int(notas or 0), int(eventos or 0), lote,
            _corta(detalhe, 300),
        ))
        return True
    except Exception:
        return False
