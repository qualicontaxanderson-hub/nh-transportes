**Caminho:** `routes/clientes.py`

```python
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from utils.db import get_db_connection
from utils.formatadores import formatar_cnpj, formatar_ie_goias, formatar_telefone, formatar_cep
from utils.decorators import admin_required

bp = Blueprint('clientes', __name__, url_prefix='/clientes')

@bp.route('/')
@login_required
def lista():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    busca = request.args.get('busca', '')
    if busca:
        cursor.execute("""
            SELECT * FROM clientes 
            WHERE razao_social LIKE %s OR cnpj LIKE %s
            ORDER BY razao_social
        """, (f'%{busca}%', f'%{busca}%'))
    else:
        cursor.execute("SELECT * FROM clientes ORDER BY razao_social")
    clientes = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('clientes/lista.html', clientes=clientes, busca=busca)

@bp.route('/novo', methods=['GET', 'POST'])
@login_required
def novo():
    if request.method == 'POST':
        razao_social = request.form.get('razao_social', '').upper()
        nome_fantasia = request.form.get('nome_fantasia', '').upper() or None
        contato = request.form.get('contato', '').upper() or None
        telefone = formatar_telefone(request.form.get('telefone')) or None
        cnpj = formatar_cnpj(request.form.get('cnpj')) or None
        ie = formatar_ie_goias(request.form.get('ie')) or None
        email = request.form.get('email') or None
        endereco = request.form.get('endereco', '').upper() or None
        numero = request.form.get('numero') or None
        complemento = request.form.get('complemento', '').upper() or None
        bairro = request.form.get('bairro', '').upper() or None
        municipio = request.form.get('municipio', '').upper() or None
        uf = request.form.get('uf', '').upper() or None
        cep = formatar_cep(request.form.get('cep')) or None
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO clientes (
                razao_social, nome_fantasia, contato, telefone, cnpj, ie, email,
                endereco, numero, complemento, bairro, municipio, uf, cep
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (razao_social, nome_fantasia, contato, telefone, cnpj, ie, email,
              endereco, numero, complemento, bairro, municipio, uf, cep))
        conn.commit()
        cursor.close()
        conn.close()
        flash('Cliente cadastrado com sucesso!', 'success')
        return redirect(url_for('clientes.lista'))
    return render_template('clientes/novo.html')

@bp.route('/editar/<int:id>', methods=['GET', 'POST'])
@login_required
def editar(id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    if request.method == 'POST':
        razao_social = request.form.get('razao_social', '').upper()
        nome_fantasia = request.form.get('nome_fantasia', '').upper() or None
        contato = request.form.get('contato', '').upper() or None
        telefone = formatar_telefone(request.form.get('telefone')) or None
        cnpj = formatar_cnpj(request.form.get('cnpj')) or None
        ie = formatar_ie_goias(request.form.get('ie')) or None
        email = request.form.get('email') or None
        endereco = request.form.get('endereco', '').upper() or None
        numero = request.form.get('numero') or None
        complemento = request.form.get('complemento', '').upper() or None
        bairro = request.form.get('bairro', '').upper() or None
        municipio = request.form.get('municipio', '').upper() or None
        uf = request.form.get('uf', '').upper() or None
        cep = formatar_cep(request.form.get('cep')) or None
        cursor.execute("""
            UPDATE clientes SET
                razao_social=%s, nome_fantasia=%s, contato=%s, telefone=%s,
                cnpj=%s, ie=%s, email=%s, endereco=%s, numero=%s,
                complemento=%s, bairro=%s, municipio=%s, uf=%s, cep=%s
            WHERE id=%s
        """, (razao_social, nome_fantasia, contato, telefone, cnpj, ie, email,
              endereco, numero, complemento, bairro, municipio, uf, cep, id))
        conn.commit()
        cursor.close()
        conn.close()
        flash('Cliente atualizado com sucesso!', 'success')
        return redirect(url_for('clientes.lista'))
    cursor.execute("SELECT * FROM clientes WHERE id = %s", (id,))
    cliente = cursor.fetchone()
    cursor.close()
    conn.close()
    if not cliente:
        flash('Cliente não encontrado!', 'danger')
        return redirect(url_for('clientes.lista'))
    return render_template('clientes/editar.html', cliente=cliente)

@bp.route('/excluir/<int:id>')
@login_required
@admin_required
def excluir(id):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM clientes WHERE id = %s", (id,))
        conn.commit()
        flash('Cliente excluído com sucesso!', 'success')
    except Exception as e:
        flash(f'Erro ao excluir: {str(e)}', 'danger')
    finally:
        cursor.close()
        conn.close()
    return redirect(url_for('clientes.lista'))
```

---
