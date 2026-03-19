"""
Módulo de Controle de Descargas de Combustível

Permite registrar e acompanhar as descargas de produtos recebidos nos postos,
vinculadas a um frete. Suporta descarga total ou parcial (em etapas) e gera
mensagem formatada para envio em grupos de WhatsApp.
"""

import logging

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required
from datetime import datetime, date
from utils.db import get_db_connection

_log = logging.getLogger(__name__)

bp = Blueprint('descargas', __name__, url_prefix='/descargas')

# ---------------------------------------------------------------------------
# Tabela Volumétrica 15M3 1,91 PLENO
# Índice = altura em cm (1..137), valor = volume em litros
# ---------------------------------------------------------------------------
TABELA_VOLUMETRICA_15M3 = {
    1: 9.73, 2: 27.46, 3: 50.37, 4: 77.43, 5: 108.04,
    6: 141.79, 7: 178.39, 8: 217.60, 9: 259.23, 10: 303.12,
    11: 349.13, 12: 397.15, 13: 447.08, 14: 498.82, 15: 552.29,
    16: 607.41, 17: 664.12, 18: 722.36, 19: 782.07, 20: 843.18,
    21: 905.67, 22: 969.47, 23: 1034.54, 24: 1100.84, 25: 1168.34,
    26: 1236.99, 27: 1306.76, 28: 1377.62, 29: 1449.53, 30: 1522.47,
    31: 1596.40, 32: 1671.30, 33: 1747.13, 34: 1823.88, 35: 1901.52,
    36: 1980.02, 37: 2059.37, 38: 2139.52, 39: 2220.48, 40: 2302.21,
    41: 2384.69, 42: 2467.90, 43: 2551.82, 44: 2636.44, 45: 2721.74,
    46: 2807.68, 47: 2894.27, 48: 2981.48, 49: 3069.29, 50: 3157.69,
    51: 3246.66, 52: 3336.18, 53: 3426.24, 54: 3516.82, 55: 3607.91,
    56: 3699.50, 57: 3791.56, 58: 3884.08, 59: 3977.05, 60: 4070.45,
    61: 4164.28, 62: 4258.51, 63: 4353.13, 64: 4448.13, 65: 4543.50,
    66: 4639.22, 67: 4735.28, 68: 4831.67, 69: 4928.37, 70: 5025.38,
    71: 5122.67, 72: 5220.24, 73: 5318.08, 74: 5416.16, 75: 5514.49,
    76: 5613.04, 77: 5711.82, 78: 5810.79, 79: 5909.96, 80: 6009.31,
    81: 6108.83, 82: 6208.51, 83: 6308.33, 84: 6408.29, 85: 6508.37,
    86: 6608.57, 87: 6708.86, 88: 6809.25, 89: 6909.71, 90: 7010.24,
    91: 7110.83, 92: 7211.46, 93: 7312.13, 94: 7412.81, 95: 7513.51,
    96: 7614.21, 97: 7714.90, 98: 7815.56, 99: 7916.19, 100: 8016.78,
    101: 8117.31, 102: 8217.77, 103: 8318.16, 104: 8418.45, 105: 8518.65,
    106: 8618.73, 107: 8718.69, 108: 8818.51, 109: 8918.19, 110: 9017.71,
    111: 9117.06, 112: 9216.23, 113: 9315.21, 114: 9413.98, 115: 9512.53,
    116: 9610.86, 117: 9708.95, 118: 9806.78, 119: 9904.35, 120: 10001.64,
    121: 10098.65, 122: 10195.35, 123: 10291.74, 124: 10387.80, 125: 10483.52,
    126: 10578.89, 127: 10673.89, 128: 10768.52, 129: 10862.75, 130: 10956.57,
    131: 11049.98, 132: 11142.95, 133: 11235.47, 134: 11327.53, 135: 11419.11,
    136: 11510.20, 137: 11600.78,
}


def _ensure_descargas_tables():
    """Cria as tabelas de descargas se ainda não existirem e aplica migrations (idempotente)."""
    ddl = """
    CREATE TABLE IF NOT EXISTS `descargas` (
        `id`                  INT AUTO_INCREMENT PRIMARY KEY,
        `frete_id`            INT NOT NULL,
        `numero_descarga`     INT NOT NULL DEFAULT 1
            COMMENT 'Número desta etapa (1, 2, 3…)',
        `total_descargas`     INT NOT NULL DEFAULT 1
            COMMENT 'Total de etapas previstas para este frete',
        `data_descarga`       DATE NOT NULL,
        `volume_descarga`     DECIMAL(14,3) NULL
            COMMENT 'Litros descarregados nesta etapa (preenchido pelo usuário em fracionada, ou volume NF em total)',
        -- Medidor eletrônico
        `medidor_antes`       DECIMAL(14,3) NULL,
        `medidor_depois`      DECIMAL(14,3) NULL,
        -- Régua volumétrica
        `regua_antes_cm`      INT NULL,
        `regua_antes_litros`  DECIMAL(14,3) NULL,
        `regua_depois_cm`     INT NULL,
        `regua_depois_litros` DECIMAL(14,3) NULL,
        -- Propriedades físicas
        `temperatura`         DECIMAL(6,2) NULL,
        `densidade`           DECIMAL(8,4) NULL,
        -- Controle
        `status`              ENUM('em_andamento','finalizado') NOT NULL DEFAULT 'em_andamento',
        `observacoes`         TEXT NULL,
        `criado_em`           DATETIME DEFAULT CURRENT_TIMESTAMP,
        `atualizado_em`       DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
        CONSTRAINT `fk_descargas_frete`
            FOREIGN KEY (`frete_id`) REFERENCES `fretes`(`id`) ON DELETE RESTRICT,
        INDEX `idx_descargas_frete`  (`frete_id`),
        INDEX `idx_descargas_data`   (`data_descarga`),
        INDEX `idx_descargas_status` (`status`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    # Columns to add if missing: (column_name, ALTER TABLE … ADD COLUMN … definition)
    # Uses INFORMATION_SCHEMA check instead of "ADD COLUMN IF NOT EXISTS" for MySQL < 8.0.3
    _migrations = [
        ("numero_descarga",
         "ALTER TABLE `descargas` ADD COLUMN `numero_descarga` INT NOT NULL DEFAULT 1 "
         "COMMENT 'Número desta etapa (1, 2, 3…)' AFTER `frete_id`"),
        ("total_descargas",
         "ALTER TABLE `descargas` ADD COLUMN `total_descargas` INT NOT NULL DEFAULT 1 "
         "COMMENT 'Total de etapas previstas para este frete' AFTER `numero_descarga`"),
        ("volume_descarga",
         "ALTER TABLE `descargas` ADD COLUMN `volume_descarga` DECIMAL(14,3) NULL "
         "COMMENT 'Litros descarregados nesta etapa' AFTER `data_descarga`"),
        ("medidor_antes",
         "ALTER TABLE `descargas` ADD COLUMN `medidor_antes` DECIMAL(14,3) NULL"),
        ("medidor_depois",
         "ALTER TABLE `descargas` ADD COLUMN `medidor_depois` DECIMAL(14,3) NULL"),
        ("regua_antes_cm",
         "ALTER TABLE `descargas` ADD COLUMN `regua_antes_cm` INT NULL"),
        ("regua_antes_litros",
         "ALTER TABLE `descargas` ADD COLUMN `regua_antes_litros` DECIMAL(14,3) NULL"),
        ("regua_depois_cm",
         "ALTER TABLE `descargas` ADD COLUMN `regua_depois_cm` INT NULL"),
        ("regua_depois_litros",
         "ALTER TABLE `descargas` ADD COLUMN `regua_depois_litros` DECIMAL(14,3) NULL"),
        ("temperatura",
         "ALTER TABLE `descargas` ADD COLUMN `temperatura` DECIMAL(6,2) NULL"),
        ("densidade",
         "ALTER TABLE `descargas` ADD COLUMN `densidade` DECIMAL(8,4) NULL"),
        ("frentista_id",
         "ALTER TABLE `descargas` ADD COLUMN `frentista_id` INT NULL "
         "COMMENT 'Funcionário/frentista que realizou a descarga' AFTER `observacoes`"),
    ]
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute(ddl)
            # Check existing columns via INFORMATION_SCHEMA (compatible with all MySQL versions)
            cur.execute(
                "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'descargas'"
            )
            existing_cols = {row[0] for row in cur.fetchall()}
            for col_name, alter_sql in _migrations:
                if col_name not in existing_cols:
                    try:
                        cur.execute(alter_sql)
                    except Exception:
                        _log.warning("Falha ao adicionar coluna '%s' em descargas.", col_name, exc_info=True)
            # Fix legacy NOT NULL columns that are no longer in the canonical schema and
            # would block INSERTs (MySQL 1364). Make them nullable so missing values default to NULL.
            # Add any newly-discovered legacy NOT NULL columns to this list.
            _legacy_notnull = ["data_carregamento", "volume_total"]
            if _legacy_notnull:
                placeholders = ",".join(["%s"] * len(_legacy_notnull))
                cur.execute(
                    "SELECT COLUMN_NAME, COLUMN_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'descargas' "
                    f"AND IS_NULLABLE = 'NO' AND COLUMN_NAME IN ({placeholders})",
                    tuple(_legacy_notnull),
                )
                for col_name, col_type in cur.fetchall():
                    # Guard: only process columns we explicitly listed (defence-in-depth)
                    if col_name not in _legacy_notnull:
                        continue
                    try:
                        cur.execute(
                            f"ALTER TABLE `descargas` MODIFY COLUMN `{col_name}` {col_type} NULL"
                        )
                        _log.info("Coluna '%s' em descargas tornada nullable (era NOT NULL sem default).", col_name)
                    except Exception:
                        _log.warning("Falha ao tornar coluna '%s' nullable em descargas.", col_name, exc_info=True)
            conn.commit()
        finally:
            cur.close()
            conn.close()
    except Exception:
        _log.warning(
            "Falha ao criar/migrar tabela descargas (não crítico).", exc_info=True
        )


# Executar migration na importação do módulo
_ensure_descargas_tables()

# Janela de dias para exibição de fretes no módulo de descargas
FRETES_WINDOW_DAYS = 5
# Condição SQL reutilizável (evita número mágico espalhado)
_FRETE_DATE_COND = f"f.data_frete >= CURDATE() - INTERVAL {FRETES_WINDOW_DAYS} DAY"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_clientes_com_produtos():
    """Retorna somente clientes que possuem pelo menos 1 produto ativo vinculado."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT DISTINCT c.id, COALESCE(c.nome_fantasia, c.razao_social) AS nome
            FROM clientes c
            INNER JOIN cliente_produtos cp ON cp.cliente_id = c.id AND cp.ativo = 1
            ORDER BY nome
        """)
        return cursor.fetchall()
    except Exception:
        # fallback: todos os clientes se a tabela cliente_produtos não existir
        try:
            cursor.execute(
                "SELECT id, COALESCE(nome_fantasia, razao_social) AS nome FROM clientes ORDER BY nome"
            )
            return cursor.fetchall()
        except Exception:
            return []
    finally:
        try:
            cursor.close()
            conn.close()
        except Exception:
            pass


def _get_motoristas_por_empresa(cliente_id=None):
    """Retorna motoristas que possuem fretes (últimos 5 dias) para a empresa informada."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        if cliente_id:
            cursor.execute(f"""
                SELECT DISTINCT m.id, m.nome
                FROM motoristas m
                INNER JOIN fretes f ON f.motoristas_id = m.id
                WHERE f.clientes_id = %s
                  AND {_FRETE_DATE_COND}
                ORDER BY m.nome
            """, (cliente_id,))
        else:
            cursor.execute(f"""
                SELECT DISTINCT m.id, m.nome
                FROM motoristas m
                INNER JOIN fretes f ON f.motoristas_id = m.id
                WHERE {_FRETE_DATE_COND}
                ORDER BY m.nome
            """)
        return cursor.fetchall()
    except Exception:
        return []
    finally:
        try:
            cursor.close()
            conn.close()
        except Exception:
            pass


def _get_funcionarios():
    """Retorna funcionários ativos para seleção de frentista."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id, nome FROM funcionarios WHERE ativo = 1 ORDER BY nome")
        return cursor.fetchall()
    except Exception:
        return []
    finally:
        try:
            cursor.close()
            conn.close()
        except Exception:
            pass


def _get_descargas_do_frete(frete_id):
    """Retorna todas as descargas já registradas para um frete (para exibir progresso)."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT d.id, d.numero_descarga, d.status,
                   DATE_FORMAT(d.data_descarga, '%%d/%%m/%%Y') AS data_descarga_fmt,
                   d.volume_descarga,
                   d.medidor_antes, d.medidor_depois
            FROM descargas d
            WHERE d.frete_id = %s
            ORDER BY d.numero_descarga, d.id
        """, (frete_id,))
        return cursor.fetchall()
    except Exception:
        return []
    finally:
        try:
            cursor.close()
            conn.close()
        except Exception:
            pass


def _get_fretes_para_descarga(cliente_id=None, motorista_id=None):
    """Retorna fretes dos últimos 5 dias com informações para o formulário de descarga.

    Filtros opcionais: ``cliente_id`` (empresa) e ``motorista_id``.
    """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        conditions = [_FRETE_DATE_COND]
        params = []
        if cliente_id:
            conditions.append("f.clientes_id = %s")
            params.append(cliente_id)
        if motorista_id:
            conditions.append("f.motoristas_id = %s")
            params.append(motorista_id)
        where = "WHERE " + " AND ".join(conditions)
        cursor.execute(f"""
            SELECT
                f.id,
                f.data_frete,
                DATE_FORMAT(f.data_frete, '%d/%m/%Y') AS data_frete_fmt,
                COALESCE(c.razao_social, '') AS cliente,
                COALESCE(fo.razao_social, '') AS distribuidora,
                COALESCE(p.nome, '') AS produto,
                COALESCE(m.nome, '') AS motorista,
                COALESCE(f.quantidade_manual, 0) AS volume_nf,
                f.clientes_id,
                f.motoristas_id,
                f.fornecedores_id,
                f.produto_id,
                f.status
            FROM fretes f
            LEFT JOIN clientes c ON f.clientes_id = c.id
            LEFT JOIN fornecedores fo ON f.fornecedores_id = fo.id
            LEFT JOIN produto p ON f.produto_id = p.id
            LEFT JOIN motoristas m ON f.motoristas_id = m.id
            {where}
            ORDER BY f.data_frete DESC, f.id DESC
            LIMIT 300
        """, tuple(params) if params else ())
        return cursor.fetchall()
    finally:
        try:
            cursor.close()
            conn.close()
        except Exception:
            pass


def _get_frete(frete_id):
    """Retorna um frete com dados enriquecidos."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT
                f.id,
                f.data_frete,
                DATE_FORMAT(f.data_frete, '%d/%m/%Y') AS data_frete_fmt,
                COALESCE(c.razao_social, '') AS cliente,
                COALESCE(fo.razao_social, '') AS distribuidora,
                COALESCE(p.nome, '') AS produto,
                COALESCE(m.nome, '') AS motorista,
                COALESCE(f.quantidade_manual, 0) AS volume_nf,
                f.clientes_id,
                f.fornecedores_id,
                f.produto_id,
                f.motoristas_id
            FROM fretes f
            LEFT JOIN clientes c ON f.clientes_id = c.id
            LEFT JOIN fornecedores fo ON f.fornecedores_id = fo.id
            LEFT JOIN produto p ON f.produto_id = p.id
            LEFT JOIN motoristas m ON f.motoristas_id = m.id
            WHERE f.id = %s
        """, (frete_id,))
        return cursor.fetchone()
    finally:
        try:
            cursor.close()
            conn.close()
        except Exception:
            pass


def _get_descarga(descarga_id):
    """Retorna uma descarga com dados enriquecidos do frete."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT
                d.*,
                DATE_FORMAT(d.data_descarga, '%d/%m/%Y') AS data_descarga_fmt,
                f.data_frete,
                DATE_FORMAT(f.data_frete, '%d/%m/%Y') AS data_frete_fmt,
                COALESCE(c.razao_social, '') AS cliente,
                COALESCE(fo.razao_social, '') AS distribuidora,
                COALESCE(p.nome, '') AS produto,
                COALESCE(m.nome, '') AS motorista,
                COALESCE(fu.nome, '') AS frentista_nome,
                COALESCE(f.quantidade_manual, 0) AS volume_nf,
                f.clientes_id,
                f.fornecedores_id,
                f.produto_id,
                f.motoristas_id
            FROM descargas d
            JOIN fretes f ON d.frete_id = f.id
            LEFT JOIN clientes c ON f.clientes_id = c.id
            LEFT JOIN fornecedores fo ON f.fornecedores_id = fo.id
            LEFT JOIN produto p ON f.produto_id = p.id
            LEFT JOIN motoristas m ON f.motoristas_id = m.id
            LEFT JOIN funcionarios fu ON d.frentista_id = fu.id
            WHERE d.id = %s
        """, (descarga_id,))
        return cursor.fetchone()
    finally:
        try:
            cursor.close()
            conn.close()
        except Exception:
            pass


def _fmt_num(val, decimals=3):
    """Formata número com separador de milhar pt-BR."""
    if val is None:
        return ''
    try:
        val = float(val)
        fmt = f"{val:,.{decimals}f}"
        # converter vírgula americana para pt-BR
        return fmt.replace(',', 'X').replace('.', ',').replace('X', '.')
    except Exception:
        return str(val)


def _diff_sign(val):
    """Retorna '+N.NNN' ou '-N.NNN' para diferença."""
    if val is None:
        return ''
    try:
        v = float(val)
        s = _fmt_num(abs(v))
        return f"+{s}" if v >= 0 else f"-{s}"
    except Exception:
        return ''


def _gerar_mensagem_whatsapp(descarga, etapas=None):
    """Monta o texto formatado para WhatsApp a partir dos dados da descarga.

    Args:
        descarga: dict com dados da descarga atual.
        etapas:   lista de todas as descargas do mesmo frete (incluindo a atual),
                  usada para montar o histórico de etapas e resumo final.
    """
    d = descarga

    produto       = (d.get('produto')          or '').strip()
    distribuidora = (d.get('distribuidora')     or '').strip()
    empresa       = (d.get('cliente')           or '').strip()
    motorista     = (d.get('motorista')         or '').strip()
    frentista     = (d.get('frentista_nome')    or '').strip()
    data_carg     = (d.get('data_frete_fmt')    or '').strip()
    data_desc     = (d.get('data_descarga_fmt') or '').strip()

    volume_desc = d.get('volume_descarga')
    volume_nf   = d.get('volume_nf')
    volume_ref  = volume_desc if volume_desc is not None else volume_nf

    total  = int(d.get('total_descargas') or 1)
    numero = int(d.get('numero_descarga') or 1)
    status = d.get('status', 'finalizado')
    is_fracionada = (total > 1) or (status == 'em_andamento')

    SEP = "━━━━━━━━━━━━━━━━━━━━━━"
    linhas = []

    # --- Cabeçalho ---
    if is_fracionada:
        linhas.append(f"⛽ *DESCARGA FRACIONADA — {produto.upper()}*")
        if total > 1:
            linhas.append(f"📌 *Etapa {numero} de {total}*")
        else:
            linhas.append(f"📌 *Etapa {numero}*")
    else:
        linhas.append(f"⛽ *DESCARGA COMPLETA — {produto.upper()}*")
    linhas.append(SEP)
    linhas.append("")

    if distribuidora:
        linhas.append(f"🏢 *Distribuidora:* {distribuidora}")
    if empresa:
        linhas.append(f"🏪 *Empresa:* {empresa}")
    if motorista:
        linhas.append(f"👷 *Motorista:* {motorista}")
    if frentista:
        linhas.append(f"🧑‍🔧 *Frentista:* {frentista}")

    # Datas
    if data_carg and data_desc:
        linhas.append(f"📅 Carregamento: {data_carg}  →  Descarga: {data_desc}")
    elif data_carg:
        linhas.append(f"📅 Carregamento: {data_carg}")
    elif data_desc:
        linhas.append(f"📅 Descarga: {data_desc}")

    # Volume desta etapa
    if volume_ref:
        vol_label = "*Volume nesta etapa:*" if is_fracionada else "*Volume descarregado:*"
        vol_str = f"*{_fmt_num(volume_ref, 0)} L*"
        if volume_nf and volume_desc and float(volume_nf) != float(volume_desc):
            vol_str += f"  _(NF total: {_fmt_num(volume_nf, 0)} L)_"
        linhas.append(f"📦 {vol_label} {vol_str}")

    # Temperatura e densidade
    temp = d.get('temperatura')
    dens = d.get('densidade')
    if temp is not None or dens is not None:
        partes = []
        if temp is not None:
            partes.append(f"🌡 Temp: {_fmt_num(temp, 1)}°C")
        if dens is not None:
            partes.append(f"⚖ Dens: {_fmt_num(dens, 4)}")
        linhas.append("   ".join(partes))

    # --- Medidor Eletrônico ---
    med_antes  = d.get('medidor_antes')
    med_depois = d.get('medidor_depois')
    if med_antes is not None or med_depois is not None:
        linhas.append("")
        linhas.append(SEP)
        linhas.append("📊 *MEDIDOR ELETRÔNICO*")
        if med_antes is not None:
            linhas.append(f"├ Antes:  {_fmt_num(med_antes)}")
        if med_depois is not None:
            linhas.append(f"├ Depois: {_fmt_num(med_depois)}")
        if med_antes is not None and med_depois is not None and volume_ref is not None:
            sobra = float(med_depois) - float(volume_ref) - float(med_antes)
            label = "✅ SOBRA/GANHO" if sobra >= 0 else "⚠️ PERDA"
            linhas.append(f"└ {label}: *{_diff_sign(sobra)}*")

    # --- Régua Volumétrica ---
    reg_antes_l   = d.get('regua_antes_litros')
    reg_depois_l  = d.get('regua_depois_litros')
    reg_antes_cm  = d.get('regua_antes_cm')
    reg_depois_cm = d.get('regua_depois_cm')
    if reg_antes_l is not None or reg_depois_l is not None:
        linhas.append("")
        linhas.append(SEP)
        linhas.append("📏 *RÉGUA VOLUMÉTRICA*")
        if reg_antes_l is not None:
            cm_str = f" ({reg_antes_cm} cm)" if reg_antes_cm else ""
            linhas.append(f"├ Antes:  {_fmt_num(reg_antes_l)} L{cm_str}")
        if reg_depois_l is not None:
            cm_str = f" ({reg_depois_cm} cm)" if reg_depois_cm else ""
            linhas.append(f"├ Depois: {_fmt_num(reg_depois_l)} L{cm_str}")
        if reg_antes_l is not None and reg_depois_l is not None and volume_ref is not None:
            diff_reg = float(reg_depois_l) - float(volume_ref) - float(reg_antes_l)
            label = "✅ SOBRA/GANHO" if diff_reg >= 0 else "⚠️ PERDA"
            linhas.append(f"└ {label}: *{_diff_sign(diff_reg)} L*")

    # --- Histórico de etapas anteriores (quando etapa > 1) ---
    if etapas and numero > 1:
        cur_id = d.get('id')
        prev_etapas = [e for e in etapas if e.get('id') != cur_id]
        if prev_etapas:
            linhas.append("")
            linhas.append(SEP)
            linhas.append("📋 *ETAPAS ANTERIORES*")
            total_ant = 0.0
            for e in prev_etapas:
                vol_e = e.get('volume_descarga') or 0
                total_ant += float(vol_e)
                vol_e_fmt = _fmt_num(vol_e, 0) if vol_e else "—"
                data_e = e.get('data_descarga_fmt', '')
                sobra_str = ''
                ma_e = e.get('medidor_antes')
                md_e = e.get('medidor_depois')
                if ma_e is not None and md_e is not None and vol_e:
                    s = float(md_e) - float(vol_e) - float(ma_e)
                    sobra_str = f"  ({'✅' if s >= 0 else '⚠️'} {_diff_sign(s)})"
                linhas.append(f"  Etapa {e.get('numero_descarga', '-')}: {data_e} — {vol_e_fmt} L{sobra_str}")

            # Resumo final acumulado
            total_acum = total_ant + (float(volume_ref) if volume_ref else 0)
            linhas.append("")
            linhas.append(SEP)
            linhas.append("📊 *RESUMO TOTAL DO FRETE*")
            linhas.append(f"├ Descarregado: *{_fmt_num(total_acum, 0)} L*")
            if volume_nf:
                linhas.append(f"├ NF total: {_fmt_num(volume_nf, 0)} L")
                restante = float(volume_nf) - total_acum
                if restante > 0.01:
                    linhas.append(f"└ ⏳ *Falta: {_fmt_num(restante, 0)} L*")
                else:
                    linhas.append("└ ✅ *Descarga concluída!*")

    obs = d.get('observacoes')
    if obs:
        linhas.append("")
        linhas.append(f"📝 *Obs:* {obs}")

    return "\n".join(linhas)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@bp.route('/', methods=['GET'])
@login_required
def lista():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    data_inicio = request.args.get('data_inicio', '')
    data_fim = request.args.get('data_fim', '')
    frete_id_f = request.args.get('frete_id', '').strip()
    status_filtro = request.args.get('status', '').strip()
    cliente_id_filtro = request.args.get('cliente_id', '').strip()

    # Default: últimos 5 dias
    if not data_inicio and not data_fim:
        from datetime import timedelta
        hoje = date.today()
        data_inicio = (hoje - timedelta(days=5)).strftime('%Y-%m-%d')
        data_fim = hoje.strftime('%Y-%m-%d')

    def _parse_date(s):
        try:
            return datetime.strptime(s, '%d/%m/%Y').strftime('%Y-%m-%d')
        except Exception:
            return s

    di = _parse_date(data_inicio) if data_inicio else None
    df = _parse_date(data_fim) if data_fim else None

    # Filtros comuns para descargas
    desc_filters = []
    desc_params = []
    if di:
        desc_filters.append("d.data_descarga >= %s")
        desc_params.append(di)
    if df:
        desc_filters.append("d.data_descarga <= %s")
        desc_params.append(df)
    if frete_id_f:
        desc_filters.append("d.frete_id = %s")
        desc_params.append(frete_id_f)
    if cliente_id_filtro:
        desc_filters.append("f.clientes_id = %s")
        desc_params.append(cliente_id_filtro)

    desc_where = ("WHERE " + " AND ".join(desc_filters)) if desc_filters else ""

    # Obter lista de clientes com produtos configurados (para o filtro e para
    # restringir os fretes em trânsito a empresas com produtos)
    clientes = _get_clientes_com_produtos()
    cliente_ids_com_produtos = tuple(int(c['id']) for c in clientes) if clientes else ()

    try:
        # ── Seção 1: Em Trânsito (fretes sem descarga nos últimos 5 dias) ──
        frete_conds = [_FRETE_DATE_COND]
        frete_params = []
        if cliente_id_filtro:
            frete_conds.append("f.clientes_id = %s")
            frete_params.append(cliente_id_filtro)
        elif cliente_ids_com_produtos:
            # Mostra apenas fretes de empresas que possuem produtos configurados
            placeholders = ','.join(['%s'] * len(cliente_ids_com_produtos))
            frete_conds.append(f"f.clientes_id IN ({placeholders})")
            frete_params.extend(cliente_ids_com_produtos)
        frete_where = "WHERE " + " AND ".join(frete_conds)
        frete_where += " AND NOT EXISTS (SELECT 1 FROM descargas d WHERE d.frete_id = f.id)"
        cursor.execute(f"""
            SELECT
                f.id,
                DATE_FORMAT(f.data_frete, '%d/%m/%Y') AS data_frete_fmt,
                COALESCE(c.razao_social, '') AS cliente,
                COALESCE(fo.razao_social, '') AS distribuidora,
                COALESCE(p.nome, '') AS produto,
                COALESCE(m.nome, '') AS motorista,
                COALESCE(f.quantidade_manual, 0) AS volume_nf
            FROM fretes f
            LEFT JOIN clientes c ON f.clientes_id = c.id
            LEFT JOIN fornecedores fo ON f.fornecedores_id = fo.id
            LEFT JOIN produto p ON f.produto_id = p.id
            LEFT JOIN motoristas m ON f.motoristas_id = m.id
            {frete_where}
            ORDER BY f.data_frete DESC, f.id DESC
        """, tuple(frete_params) if frete_params else ())
        fretes_em_transito = cursor.fetchall()

        # ── Seção 2: Descarregados (status=finalizado) ──
        w2 = desc_where
        p2 = list(desc_params)
        if status_filtro:
            if w2:
                w2 += " AND d.status = %s"
            else:
                w2 = "WHERE d.status = %s"
            p2.append(status_filtro)
        else:
            finalizado_where = (desc_where + " AND d.status = 'finalizado'") if desc_where else "WHERE d.status = 'finalizado'"
            fracionado_where = (desc_where + " AND d.status = 'em_andamento'") if desc_where else "WHERE d.status = 'em_andamento'"

        select_descargas = """
            SELECT
                d.id, d.frete_id, d.numero_descarga, d.total_descargas,
                DATE_FORMAT(d.data_descarga, '%d/%m/%Y') AS data_descarga_fmt,
                d.medidor_antes, d.medidor_depois, d.volume_descarga,
                d.regua_antes_litros, d.regua_depois_litros,
                d.temperatura, d.densidade, d.status,
                COALESCE(c.razao_social, '') AS cliente,
                COALESCE(fo.razao_social, '') AS distribuidora,
                COALESCE(p.nome, '') AS produto,
                COALESCE(m.nome, '') AS motorista,
                COALESCE(f.quantidade_manual, 0) AS volume_nf,
                DATE_FORMAT(f.data_frete, '%d/%m/%Y') AS data_frete_fmt
            FROM descargas d
            JOIN fretes f ON d.frete_id = f.id
            LEFT JOIN clientes c ON f.clientes_id = c.id
            LEFT JOIN fornecedores fo ON f.fornecedores_id = fo.id
            LEFT JOIN produto p ON f.produto_id = p.id
            LEFT JOIN motoristas m ON f.motoristas_id = m.id
        """
        cursor.execute(select_descargas + finalizado_where + " ORDER BY d.data_descarga DESC, d.id DESC", tuple(desc_params))
        descargas_finalizadas = cursor.fetchall()

        cursor.execute(select_descargas + fracionado_where + " ORDER BY d.data_descarga DESC, d.id DESC", tuple(desc_params))
        descargas_fracionadas = cursor.fetchall()

        def _enrich(rows):
            for d in rows:
                vol = d.get('volume_descarga') or d.get('volume_nf')
                ma = d.get('medidor_antes')
                md = d.get('medidor_depois')
                if ma is not None and md is not None and vol is not None:
                    d['diff_medidor'] = float(md) - float(vol) - float(ma)
                else:
                    d['diff_medidor'] = None
                ra = d.get('regua_antes_litros')
                rd = d.get('regua_depois_litros')
                if ra is not None and rd is not None and vol is not None:
                    d['diff_regua'] = float(rd) - float(vol) - float(ra)
                else:
                    d['diff_regua'] = None
                dm = d['diff_medidor']
                dr = d['diff_regua']
                d['diff_med_regua'] = (dr - dm) if (dm is not None and dr is not None) else None

        _enrich(descargas_finalizadas)
        _enrich(descargas_fracionadas)

    except Exception as exc:
        _log.warning("Erro na lista descargas: %s", exc, exc_info=True)
        fretes_em_transito = []
        descargas_finalizadas = []
        descargas_fracionadas = []
        clientes = []
    finally:
        try:
            cursor.close()
            conn.close()
        except Exception:
            pass

    return render_template(
        'descargas/lista.html',
        fretes_em_transito=fretes_em_transito,
        descargas_finalizadas=descargas_finalizadas,
        descargas_fracionadas=descargas_fracionadas,
        clientes=clientes,
        data_inicio=data_inicio,
        data_fim=data_fim,
        frete_id=frete_id_f,
        status_filtro=status_filtro,
        cliente_id_filtro=cliente_id_filtro,
    )


@bp.route('/nova', methods=['GET', 'POST'])
@login_required
def nova():
    if request.method == 'POST':
        conn = get_db_connection()
        try:
            frete_id = request.form.get('frete_id')
            data_descarga = request.form.get('data_descarga')
            # tipo_descarga: 'total' → finalizado, 'fracionada' → em_andamento
            tipo_descarga = request.form.get('tipo_descarga', 'total')
            status = 'finalizado' if tipo_descarga == 'total' else 'em_andamento'
            numero_descarga = 1
            total_descargas = 1
            medidor_antes = request.form.get('medidor_antes') or None
            medidor_depois = request.form.get('medidor_depois') or None
            regua_antes_cm = request.form.get('regua_antes_cm') or None
            regua_antes_litros = request.form.get('regua_antes_litros') or None
            regua_depois_cm = request.form.get('regua_depois_cm') or None
            regua_depois_litros = request.form.get('regua_depois_litros') or None
            temperatura = request.form.get('temperatura') or None
            densidade = request.form.get('densidade') or None
            observacoes = request.form.get('observacoes') or None
            frentista_id = request.form.get('frentista_id') or None
            # volume_descarga: para fracionada = informado pelo usuário;
            # para total = volume NF do frete (enviado como campo hidden)
            volume_descarga = request.form.get('volume_descarga') or None

            if not frete_id or not data_descarga:
                flash('Frete e data de descarga são obrigatórios.', 'danger')
                return redirect(url_for('descargas.nova'))

            def _to_decimal(v):
                if v is None:
                    return None
                try:
                    return float(str(v).replace(',', '.'))
                except Exception:
                    return None

            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO descargas (
                    frete_id, numero_descarga, total_descargas, data_descarga,
                    volume_descarga,
                    medidor_antes, medidor_depois,
                    regua_antes_cm, regua_antes_litros,
                    regua_depois_cm, regua_depois_litros,
                    temperatura, densidade, status, observacoes, frentista_id
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                frete_id, numero_descarga, total_descargas, data_descarga,
                _to_decimal(volume_descarga),
                _to_decimal(medidor_antes), _to_decimal(medidor_depois),
                regua_antes_cm or None, _to_decimal(regua_antes_litros),
                regua_depois_cm or None, _to_decimal(regua_depois_litros),
                _to_decimal(temperatura), _to_decimal(densidade),
                status, observacoes, frentista_id or None,
            ))
            conn.commit()
            new_id = cursor.lastrowid
            cursor.close()
            flash('Descarga registrada com sucesso!', 'success')
            return redirect(url_for('descargas.detalhe', id=new_id))
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            flash(f'Erro ao salvar descarga: {e}', 'danger')
            return redirect(url_for('descargas.nova'))
        finally:
            try:
                conn.close()
            except Exception:
                pass

    # GET
    cliente_id_qs = request.args.get('cliente_id', '').strip()
    motorista_id_qs = request.args.get('motorista_id', '').strip()
    frete_id_qs = request.args.get('frete_id', '')
    frete_pre = None
    descargas_existentes = []
    if frete_id_qs:
        frete_pre = _get_frete(frete_id_qs)
        if frete_pre:
            if not cliente_id_qs:
                cliente_id_qs = str(frete_pre.get('clientes_id', ''))
            if not motorista_id_qs:
                motorista_id_qs = str(frete_pre.get('motoristas_id', ''))
        descargas_existentes = _get_descargas_do_frete(frete_id_qs)

    clientes = _get_clientes_com_produtos()
    motoristas = _get_motoristas_por_empresa(cliente_id_qs if cliente_id_qs else None)
    funcionarios = _get_funcionarios()
    fretes = _get_fretes_para_descarga(
        cliente_id=cliente_id_qs if cliente_id_qs else None,
        motorista_id=motorista_id_qs if motorista_id_qs else None,
    )
    tabela_js = {str(k): v for k, v in TABELA_VOLUMETRICA_15M3.items()}
    hoje = date.today().strftime('%Y-%m-%d')

    return render_template(
        'descargas/nova.html',
        fretes=fretes,
        clientes=clientes,
        motoristas=motoristas,
        funcionarios=funcionarios,
        frete_pre=frete_pre,
        frete_id_qs=frete_id_qs,
        cliente_id_qs=cliente_id_qs,
        motorista_id_qs=motorista_id_qs,
        tabela_volumetrica=tabela_js,
        hoje=hoje,
        descargas_existentes=descargas_existentes,
    )


@bp.route('/editar/<int:id>', methods=['GET', 'POST'])
@login_required
def editar(id):
    descarga = _get_descarga(id)
    if not descarga:
        flash('Descarga não encontrada.', 'danger')
        return redirect(url_for('descargas.lista'))

    if request.method == 'POST':
        conn = get_db_connection()
        try:
            tipo_descarga = request.form.get('tipo_descarga', 'total')
            status = 'finalizado' if tipo_descarga == 'total' else 'em_andamento'
            numero_descarga = request.form.get('numero_descarga') or 1
            total_descargas = request.form.get('total_descargas') or 1
            data_descarga = request.form.get('data_descarga')
            medidor_antes = request.form.get('medidor_antes') or None
            medidor_depois = request.form.get('medidor_depois') or None
            regua_antes_cm = request.form.get('regua_antes_cm') or None
            regua_antes_litros = request.form.get('regua_antes_litros') or None
            regua_depois_cm = request.form.get('regua_depois_cm') or None
            regua_depois_litros = request.form.get('regua_depois_litros') or None
            temperatura = request.form.get('temperatura') or None
            densidade = request.form.get('densidade') or None
            observacoes = request.form.get('observacoes') or None
            volume_descarga = request.form.get('volume_descarga') or None
            frentista_id = request.form.get('frentista_id') or None

            def _to_decimal(v):
                if v is None:
                    return None
                try:
                    return float(str(v).replace(',', '.'))
                except Exception:
                    return None

            cursor = conn.cursor()
            cursor.execute("""
                UPDATE descargas SET
                    numero_descarga=%s, total_descargas=%s, data_descarga=%s,
                    volume_descarga=%s,
                    medidor_antes=%s, medidor_depois=%s,
                    regua_antes_cm=%s, regua_antes_litros=%s,
                    regua_depois_cm=%s, regua_depois_litros=%s,
                    temperatura=%s, densidade=%s,
                    status=%s, observacoes=%s, frentista_id=%s
                WHERE id=%s
            """, (
                numero_descarga, total_descargas, data_descarga,
                _to_decimal(volume_descarga),
                _to_decimal(medidor_antes), _to_decimal(medidor_depois),
                regua_antes_cm or None, _to_decimal(regua_antes_litros),
                regua_depois_cm or None, _to_decimal(regua_depois_litros),
                _to_decimal(temperatura), _to_decimal(densidade),
                status, observacoes, frentista_id or None, id,
            ))
            conn.commit()
            cursor.close()
            flash('Descarga atualizada com sucesso!', 'success')
            return redirect(url_for('descargas.detalhe', id=id))
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            flash(f'Erro ao atualizar descarga: {e}', 'danger')
        finally:
            try:
                conn.close()
            except Exception:
                pass

    tabela_js = {str(k): v for k, v in TABELA_VOLUMETRICA_15M3.items()}
    funcionarios = _get_funcionarios()
    return render_template(
        'descargas/editar.html',
        descarga=descarga,
        tabela_volumetrica=tabela_js,
        funcionarios=funcionarios,
    )


@bp.route('/detalhe/<int:id>', methods=['GET'])
@login_required
def detalhe(id):
    descarga = _get_descarga(id)
    if not descarga:
        flash('Descarga não encontrada.', 'danger')
        return redirect(url_for('descargas.lista'))

    # Buscar todas as descargas do mesmo frete
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT d.*,
                   DATE_FORMAT(d.data_descarga, '%d/%m/%Y') AS data_descarga_fmt
            FROM descargas d
            WHERE d.frete_id = %s
            ORDER BY d.numero_descarga, d.id
        """, (descarga['frete_id'],))
        outras = cursor.fetchall()
    except Exception:
        outras = []
    finally:
        try:
            cursor.close()
            conn.close()
        except Exception:
            pass

    mensagem = _gerar_mensagem_whatsapp(descarga, etapas=outras)

    # Calcular sobra medidor: Depois - Volume - Antes
    diff_medidor = None
    vol = descarga.get('volume_descarga') or descarga.get('volume_nf')
    if (descarga.get('medidor_antes') is not None
            and descarga.get('medidor_depois') is not None
            and vol is not None):
        diff_medidor = float(descarga['medidor_depois']) - float(vol) - float(descarga['medidor_antes'])

    diff_regua = None
    if (descarga.get('regua_antes_litros') is not None
            and descarga.get('regua_depois_litros') is not None
            and vol is not None):
        diff_regua = float(descarga['regua_depois_litros']) - float(vol) - float(descarga['regua_antes_litros'])

    diff_med_regua = None
    if diff_medidor is not None and diff_regua is not None:
        diff_med_regua = diff_regua - diff_medidor

    return render_template(
        'descargas/detalhe.html',
        descarga=descarga,
        outras=outras,
        mensagem=mensagem,
        diff_medidor=diff_medidor,
        diff_regua=diff_regua,
        diff_med_regua=diff_med_regua,
    )


@bp.route('/deletar/<int:id>', methods=['POST'])
@login_required
def deletar(id):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM descargas WHERE id = %s", (id,))
        conn.commit()
        flash('Descarga excluída.', 'success')
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        flash(f'Erro ao excluir descarga: {e}', 'danger')
    finally:
        try:
            cursor.close()
            conn.close()
        except Exception:
            pass
    return redirect(url_for('descargas.lista'))


@bp.route('/api/tabela_volumetrica', methods=['GET'])
@login_required
def api_tabela():
    """Retorna a tabela volumétrica como JSON para uso no frontend."""
    return jsonify(TABELA_VOLUMETRICA_15M3)


@bp.route('/api/motoristas_por_empresa/<int:cliente_id>', methods=['GET'])
@login_required
def api_motoristas_por_empresa(cliente_id):
    """Retorna motoristas que têm fretes (últimos 5 dias) para o cliente como JSON."""
    motoristas = _get_motoristas_por_empresa(cliente_id)
    return jsonify([{'id': m['id'], 'nome': m['nome']} for m in motoristas])


@bp.route('/api/fretes_por_empresa/<int:cliente_id>', methods=['GET'])
@login_required
def api_fretes_por_empresa(cliente_id):
    """Retorna fretes (últimos 5 dias) de um cliente como JSON.

    Aceita parâmetro opcional ``?motorista_id=<id>`` para filtrar por motorista.
    """
    motorista_id = request.args.get('motorista_id', '').strip() or None
    fretes = _get_fretes_para_descarga(cliente_id=cliente_id, motorista_id=motorista_id)
    resultado = []
    for f in fretes:
        vol = float(f['volume_nf']) if f['volume_nf'] else 0
        vol_fmt = f"{vol:,.0f}".replace(',', '.') if vol else '—'
        label = (f"{f['data_frete_fmt']} | "
                 f"{f['produto']} | {vol_fmt} L | {f['distribuidora']}")
        resultado.append({
            'id': f['id'],
            'label': label,
            'cliente': f['cliente'],
            'distribuidora': f['distribuidora'],
            'produto': f['produto'],
            'motorista': f['motorista'],
            'motorista_id': f['motoristas_id'],
            'volume_nf': vol,
            'data_frete_fmt': f['data_frete_fmt'],
            'clientes_id': f['clientes_id'],
        })
    return jsonify(resultado)


@bp.route('/api/frete/<int:frete_id>', methods=['GET'])
@login_required
def api_frete(frete_id):
    """Retorna dados de um frete para pré-preenchimento do formulário."""
    frete = _get_frete(frete_id)
    if not frete:
        return jsonify({'error': 'Frete não encontrado'}), 404
    return jsonify({
        'id': frete['id'],
        'cliente': frete['cliente'],
        'distribuidora': frete['distribuidora'],
        'produto': frete['produto'],
        'motorista': frete['motorista'],
        'motoristas_id': frete['motoristas_id'],
        'clientes_id': frete['clientes_id'],
        'volume_nf': float(frete['volume_nf']) if frete['volume_nf'] else 0,
        'data_frete_fmt': frete['data_frete_fmt'],
    })
