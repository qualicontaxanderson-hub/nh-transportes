# -*- coding: utf-8 -*-
"""Cheques do troco PIX: vários por solicitação, com foto da frente e do verso
(20/11/2026).

Fotos
-----
- Ficam no Dropbox (pedido do Anderson: "guardar no dropbox e quando eu desejar
  eu apago"), em <TROCO_CHEQUES_DROPBOX>/AAAA/MM/DD/. O servidor do Railway
  apaga o disco a cada deploy e o banco custa caro por GB, por isso não ficam
  em nenhum dos dois.
- Cada foto nasce num "slot" (troco_pix_fotos) com token aleatório. No
  computador, o slot vira um QR: qualquer celular abre /troco_pix/f/<token>,
  sem login, tira a foto e manda. O token vale 30 minutos e serve UMA vez.
- O servidor regrava toda foto em JPEG (máx. 1600 px): encolhe e garante que
  é imagem de verdade.
- Só para desenvolvimento: TROCO_FOTOS_LOCAL=<pasta> grava em disco local em
  vez do Dropbox. Em produção, sem Dropbox, o envio falha com aviso (nunca grava
  calado num disco que some).
"""
import io
import os
import secrets
from datetime import datetime, timedelta

VALIDADE_MIN = 30
LADOS = ('frente', 'verso')
_tabelas_ok = False


def _base():
    b = (os.environ.get('TROCO_CHEQUES_DROPBOX') or '/CHEQUES TROCO PIX').strip()
    return '/' + b.strip('/')


# ─── tabelas ────────────────────────────────────────────────────────────────
def garantir_tabelas(conn):
    """CREATE TABLE IF NOT EXISTS (DDL faz commit implícito: chamar fora de
    transação com dados)."""
    global _tabelas_ok
    if _tabelas_ok:
        return
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS troco_pix_fotos (
            id INT AUTO_INCREMENT PRIMARY KEY,
            token CHAR(43) NOT NULL,
            criado_por INT NULL,
            criado_em DATETIME NOT NULL,
            expira_em DATETIME NOT NULL,
            enviado_em DATETIME NULL,
            enviado_de VARCHAR(10) NULL,
            caminho VARCHAR(400) NULL,
            bytes INT NULL,
            UNIQUE KEY uk_token (token)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS troco_pix_cheques (
            id INT AUTO_INCREMENT PRIMARY KEY,
            troco_pix_id INT NOT NULL,
            ordem INT NOT NULL,
            valor DECIMAL(10,2) NOT NULL,
            vencimento DATE NULL,
            foto_frente_id INT NULL,
            foto_verso_id INT NULL,
            KEY ix_troco (troco_pix_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    conn.commit()
    cur.close()
    _tabelas_ok = True


# ─── armazenamento ──────────────────────────────────────────────────────────
def _local_dir():
    return (os.environ.get('TROCO_FOTOS_LOCAL') or '').strip()


def _dbx():
    from integrations.dropbox_ofx import _criar_dbx
    return _criar_dbx()


def _gravar(caminho, dados):
    loc = _local_dir()
    if loc:
        p = os.path.join(loc, caminho.lstrip('/').replace('/', os.sep))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'wb') as f:
            f.write(dados)
        return
    import dropbox
    _dbx().files_upload(dados, caminho, mode=dropbox.files.WriteMode('overwrite'))


def ler(caminho):
    loc = _local_dir()
    if loc:
        with open(os.path.join(loc, caminho.lstrip('/').replace('/', os.sep)), 'rb') as f:
            return f.read()
    _, resp = _dbx().files_download(caminho)
    return resp.content


def _renomear(de, para):
    loc = _local_dir()
    if loc:
        a = os.path.join(loc, de.lstrip('/').replace('/', os.sep))
        b = os.path.join(loc, para.lstrip('/').replace('/', os.sep))
        os.replace(a, b)
        return
    import dropbox
    _dbx().files_move_v2(de, para, autorename=True)


def normalizar_imagem(dados):
    """Regrava em JPEG, no máximo 1600 px, respeitando a rotação do celular.
    Levanta ValueError se não for imagem."""
    from PIL import Image, ImageOps
    try:
        img = Image.open(io.BytesIO(dados))
        img = ImageOps.exif_transpose(img)
        img = img.convert('RGB')
    except Exception:
        raise ValueError('O arquivo enviado não é uma imagem.')
    img.thumbnail((1600, 1600))
    out = io.BytesIO()
    img.save(out, format='JPEG', quality=75, optimize=True)
    return out.getvalue()


# ─── slots ──────────────────────────────────────────────────────────────────
def criar_slot(conn, usuario_id):
    garantir_tabelas(conn)
    token = secrets.token_urlsafe(32)[:43]
    agora = datetime.now()
    cur = conn.cursor()
    cur.execute("INSERT INTO troco_pix_fotos (token, criado_por, criado_em, expira_em) "
                "VALUES (%s, %s, %s, %s)",
                (token, usuario_id, agora, agora + timedelta(minutes=VALIDADE_MIN)))
    conn.commit()
    fid = cur.lastrowid
    cur.close()
    return fid, token


def slot_por_token(conn, token):
    garantir_tabelas(conn)
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM troco_pix_fotos WHERE token = %s", (token,))
    r = cur.fetchone()
    cur.close()
    return r


def slot_por_id(conn, foto_id):
    garantir_tabelas(conn)
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM troco_pix_fotos WHERE id = %s", (foto_id,))
    r = cur.fetchone()
    cur.close()
    return r


def situacao(slot):
    if not slot:
        return 'inexistente'
    if slot['enviado_em']:
        return 'enviado'
    if datetime.now() > slot['expira_em']:
        return 'expirado'
    return 'aguardando'


def guardar_foto(conn, slot, dados, origem):
    """Grava a foto do slot (uma vez só). Devolve o caminho."""
    if situacao(slot) != 'aguardando':
        raise ValueError('Este código já foi usado ou venceu. Gere outro no computador.')
    jpg = normalizar_imagem(dados)
    hoje = datetime.now()
    caminho = '%s/%s/foto_%d.jpg' % (_base(), hoje.strftime('%Y/%m/%d'), slot['id'])
    _gravar(caminho, jpg)
    cur = conn.cursor()
    # só grava se ainda estava livre: dois celulares no mesmo QR não trocam a foto
    cur.execute("UPDATE troco_pix_fotos SET enviado_em=%s, enviado_de=%s, caminho=%s, bytes=%s "
                "WHERE id=%s AND enviado_em IS NULL", (hoje, origem, caminho, len(jpg), slot['id']))
    conn.commit()
    ok = cur.rowcount == 1
    cur.close()
    if not ok:
        raise ValueError('Este código já foi usado. Gere outro no computador.')
    return caminho


# ─── cheques do troco ───────────────────────────────────────────────────────
def cheques_do_troco(conn, troco_pix_id):
    garantir_tabelas(conn)
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT c.*, ff.caminho AS frente_caminho, fv.caminho AS verso_caminho
        FROM troco_pix_cheques c
        LEFT JOIN troco_pix_fotos ff ON ff.id = c.foto_frente_id AND ff.caminho IS NOT NULL
        LEFT JOIN troco_pix_fotos fv ON fv.id = c.foto_verso_id AND fv.caminho IS NOT NULL
        WHERE c.troco_pix_id = %s ORDER BY c.ordem
    """, (troco_pix_id,))
    rows = cur.fetchall()
    cur.close()
    for r in rows:
        if not r['frente_caminho']:
            r['foto_frente_id'] = None
        if not r['verso_caminho']:
            r['foto_verso_id'] = None
    return rows


def ler_cheques_do_form(form):
    """[(valor: float, vencimento: str|None, frente_id: int|None, verso_id: int|None), ...]
    Linhas com valor zero são ignoradas."""
    valores = form.getlist('cheque_valor_item')
    vencs = form.getlist('cheque_venc_item')
    frentes = form.getlist('cheque_foto_frente_item')
    versos = form.getlist('cheque_foto_verso_item')
    out = []
    for i, v in enumerate(valores):
        try:
            val = round(float(str(v).replace(',', '.')), 2)
        except ValueError:
            val = 0.0
        if val <= 0:
            continue
        venc = (vencs[i] if i < len(vencs) else '') or None
        fr = frentes[i] if i < len(frentes) else ''
        ve = versos[i] if i < len(versos) else ''
        out.append((val, venc, int(fr) if str(fr).isdigit() else None,
                    int(ve) if str(ve).isdigit() else None))
    return out


def gravar_cheques(conn, troco_pix_id, numero, cheques):
    """Troca os cheques do troco pelos do formulário e dá às fotos um nome que
    se acha no Dropbox (<número> - cheque N frente). Renomear é cortesia: se
    falhar, a foto continua no lugar e ligada ao cheque."""
    garantir_tabelas(conn)
    cur = conn.cursor(dictionary=True)
    cur.execute("DELETE FROM troco_pix_cheques WHERE troco_pix_id = %s", (troco_pix_id,))
    renomear = []
    for n, (val, venc, fr, ve) in enumerate(cheques, start=1):
        # só aceita foto já enviada (e não ligada a outro troco)
        ids = {}
        for lado, fid in (('frente', fr), ('verso', ve)):
            if not fid:
                ids[lado] = None
                continue
            cur.execute("SELECT id, caminho FROM troco_pix_fotos WHERE id=%s AND caminho IS NOT NULL", (fid,))
            f = cur.fetchone()
            ids[lado] = f['id'] if f else None
            if f:
                renomear.append((f['id'], f['caminho'], n, lado))
        cur.execute("INSERT INTO troco_pix_cheques (troco_pix_id, ordem, valor, vencimento, "
                    "foto_frente_id, foto_verso_id) VALUES (%s,%s,%s,%s,%s,%s)",
                    (troco_pix_id, n, val, venc, ids['frente'], ids['verso']))
    conn.commit()
    for fid, caminho, n, lado in renomear:
        if os.path.basename(caminho).startswith('foto_'):
            novo = '%s/%s - cheque %d %s.jpg' % (os.path.dirname(caminho), numero or ('troco %d' % troco_pix_id), n, lado)
            try:
                _renomear(caminho, novo)
                cur.execute("UPDATE troco_pix_fotos SET caminho=%s WHERE id=%s", (novo, fid))
                conn.commit()
            except Exception as e:
                print('[cheque_fotos] renomear %s falhou: %s' % (caminho, e))
    cur.close()
