"""
Rota máquina-a-máquina para ingestão de vendas capturadas de XML.

    POST /api/vendas

Um robô externo envia as vendas (cabeçalho + itens) e os cancelamentos.
A rota SÓ escreve nas tabelas novas `vendas_xml` e `vendas_xml_itens`
(e atualiza `situacao` em `vendas_xml` para cancelamentos). NÃO toca em
nenhuma tabela existente do sistema.

Autenticação: header `Authorization: Bearer <token>` comparado em tempo
constante com a variável de ambiente ROBO_VENDAS_TOKEN. NÃO usa login de
sessão — como o app não tem `before_request` global de autenticação e esta
rota não usa @login_required, ela já fica fora de qualquer exigência de
usuário logado.
"""
import os
import hmac

from flask import Blueprint, request, current_app, jsonify

from extensions import csrf
from utils.db import get_db_connection

vendas_api_bp = Blueprint('vendas_api', __name__, url_prefix='')

# Campos do cabeçalho gravados em vendas_xml (na ordem do INSERT).
# vendedor_id fica NULL; situacao/origem usam os defaults da tabela.
_CAMPOS_CABECALHO = (
    'chave', 'modelo', 'serie', 'numero', 'dh_emissao', 'cnpj_emitente',
    'cliente_doc', 'cliente_nome', 'valor_total', 'forma_pagamento',
    'vendedor_raw', 'arquivo',
)

# Campos de cada item gravados em vendas_xml_itens (além de venda_id).
_CAMPOS_ITEM = (
    'n_item', 'produto_xml', 'cod_anp', 'produto_id', 'eh_combustivel',
    'unidade', 'quantidade', 'valor_unitario', 'valor_total',
    'bico', 'bomba', 'tanque', 'enc_ini', 'enc_fin',
)

# Campos NOVOS (JSON key -> default se ausente OU None no JSON).
# NOT NULL no banco -> default 0 (nunca NULL). Nullable -> None.
# A ORDEM aqui casa com a ordem das colunas no INSERT (apos as antigas).
_CABECALHO_NOVOS = (
    ('vlr_desconto', 0), ('vlr_acrescimo', 0), ('vlr_trib_aprox', 0),
    ('troco', 0), ('nat_op', None), ('protocolo', None),
    ('card_bandeira_cod', None), ('card_bandeira', None),
    ('card_credenciadora', None), ('card_autorizacao', None),
    ('card_integrado', None), ('placa', None), ('km', None),
    # --- Fase 2: tributos separados, TEF e endereco do cliente ---
    ('trib_fed', None), ('trib_est', None), ('trib_mun', None),
    ('tef_terminal', None), ('tef_sequencia', None),
    ('cli_logradouro', None), ('cli_bairro', None), ('cli_municipio', None),
    ('cli_uf', None), ('cli_cep', None),
)
_ITEM_NOVOS = (
    ('vlr_desconto', 0), ('vlr_acrescimo', 0), ('pbio', None),
    # --- Fase 2: fiscais do item ---
    ('cprod', None), ('ncm', None), ('cfop', None), ('cst', None), ('icms_mono', None),
)


def _com_defaults(d, campos):
    """Valores de `campos` (lista de (chave, default)) tirados do dict `d`.
    Chave ausente OU None -> usa default. Assim robo antigo (sem os campos)
    nao quebra os INSERTs em colunas NOT NULL."""
    return tuple(default if d.get(k) is None else d.get(k) for k, default in campos)

_SQL_EXISTE = "SELECT id FROM vendas_xml WHERE chave = %s"

_SQL_INSERT_CABECALHO = (
    "INSERT INTO vendas_xml (chave, modelo, serie, numero, dh_emissao, "
    "cnpj_emitente, cliente_doc, cliente_nome, valor_total, forma_pagamento, "
    "vendedor_raw, arquivo, "
    "vlr_desconto, vlr_acrescimo, vlr_trib_aprox, troco, nat_op, protocolo, "
    "card_bandeira_cod, card_bandeira, card_credenciadora, card_autorizacao, "
    "card_integrado, placa, km, "
    "trib_fed, trib_est, trib_mun, tef_terminal, tef_sequencia, "
    "cli_logradouro, cli_bairro, cli_municipio, cli_uf, cli_cep) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
    "%s, %s, %s, %s, %s, %s, "
    "%s, %s, %s, %s, %s, %s, %s, "
    "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
)

_SQL_INSERT_ITEM = (
    "INSERT INTO vendas_xml_itens (venda_id, n_item, produto_xml, cod_anp, "
    "produto_id, eh_combustivel, unidade, quantidade, valor_unitario, "
    "valor_total, bico, bomba, tanque, enc_ini, enc_fin, "
    "vlr_desconto, vlr_acrescimo, pbio, "
    "cprod, ncm, cfop, cst, icms_mono) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
    "%s, %s, %s, "
    "%s, %s, %s, %s, %s)"
)

_SQL_CANCELA = "UPDATE vendas_xml SET situacao = 'cancelada' WHERE chave = %s"


def _autenticado():
    """
    Compara o token do header Authorization: Bearer <token> com ROBO_VENDAS_TOKEN
    usando hmac.compare_digest (tempo constante). Retorna True se bater.
    """
    esperado = os.environ.get('ROBO_VENDAS_TOKEN')
    if not esperado:
        # Sem token configurado no ambiente: nega tudo e sinaliza má configuração.
        current_app.logger.error("[api/vendas] ROBO_VENDAS_TOKEN não configurado no ambiente")
        return False

    header = request.headers.get('Authorization', '') or ''
    prefixo = 'Bearer '
    if not header.startswith(prefixo):
        return False
    enviado = header[len(prefixo):].strip()
    if not enviado:
        return False

    return hmac.compare_digest(enviado.encode('utf-8'), esperado.encode('utf-8'))


@vendas_api_bp.route('/api/vendas', methods=['POST'])
@csrf.exempt
def receber_vendas():
    """
    Ingestão de vendas do robô externo. Ver docstring do módulo.

    Body esperado (JSON):
        {
          "notas": [ { <cabeçalho>, "itens": [ {<item>}, ... ] }, ... ],
          "cancelamentos": ["chave44", ...]
        }

    Resposta 200:
        {
          "ok": [chaves gravadas],
          "repetidas": [chaves que já existiam],
          "canceladas": [chaves canceladas],
          "erros": [ {"chave": ..., "erro": ...}, ... ],
          "novas_gravadas": N
        }
    """
    if not _autenticado():
        return jsonify({"ok": False, "erro": "não autorizado"}), 401

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "erro": "JSON inválido ou ausente"}), 400

    notas = payload.get('notas') or []
    cancelamentos = payload.get('cancelamentos') or []
    if not isinstance(notas, list):
        notas = []
    if not isinstance(cancelamentos, list):
        cancelamentos = []

    ok = []
    repetidas = []
    canceladas = []
    erros = []

    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # ---------- NOTAS ----------
        for nota in notas:
            chave = None
            try:
                if not isinstance(nota, dict):
                    erros.append({"chave": None, "erro": "nota não é objeto JSON"})
                    continue

                chave = nota.get('chave')
                if not chave:
                    erros.append({"chave": None, "erro": "chave ausente"})
                    continue

                # Já existe? -> repetida, não insere.
                cur.execute(_SQL_EXISTE, (chave,))
                if cur.fetchone() is not None:
                    repetidas.append(chave)
                    continue

                # Insere cabeçalho + itens numa transação própria desta nota.
                params_cab = (tuple(nota.get(c) for c in _CAMPOS_CABECALHO)
                              + _com_defaults(nota, _CABECALHO_NOVOS))
                cur.execute(_SQL_INSERT_CABECALHO, params_cab)
                venda_id = cur.lastrowid

                itens = nota.get('itens') or []
                if not isinstance(itens, list):
                    itens = []
                for item in itens:
                    if not isinstance(item, dict):
                        raise ValueError("item não é objeto JSON")
                    params_item = ((venda_id,)
                                   + tuple(item.get(c) for c in _CAMPOS_ITEM)
                                   + _com_defaults(item, _ITEM_NOVOS))
                    cur.execute(_SQL_INSERT_ITEM, params_item)

                conn.commit()
                ok.append(chave)
            except Exception as e:
                # Erro em 1 nota: rollback só dela, registra e segue.
                try:
                    conn.rollback()
                except Exception:
                    pass
                current_app.logger.warning("[api/vendas] falha ao gravar nota chave=%s: %s", chave, e)
                erros.append({"chave": chave, "erro": str(e)})

        # ---------- CANCELAMENTOS ----------
        for chave in cancelamentos:
            try:
                if not chave:
                    erros.append({"chave": None, "erro": "cancelamento com chave vazia"})
                    continue
                cur.execute(_SQL_CANCELA, (chave,))
                conn.commit()
                if cur.rowcount and cur.rowcount > 0:
                    canceladas.append(chave)
                else:
                    erros.append({"chave": chave, "erro": "cancelamento: chave não encontrada"})
            except Exception as e:
                try:
                    conn.rollback()
                except Exception:
                    pass
                current_app.logger.warning("[api/vendas] falha ao cancelar chave=%s: %s", chave, e)
                erros.append({"chave": chave, "erro": str(e)})

    except Exception:
        # Falha estrutural (ex.: sem conexão). Não deveria virar 500 silencioso.
        current_app.logger.exception("[api/vendas] erro estrutural processando requisição")
        return jsonify({"ok": False, "erro": "erro interno ao processar vendas"}), 500
    finally:
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        try:
            if conn:
                conn.close()
        except Exception:
            pass

    return jsonify({
        "ok": ok,
        "repetidas": repetidas,
        "canceladas": canceladas,
        "erros": erros,
        "novas_gravadas": len(ok),
    }), 200
