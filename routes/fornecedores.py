**Caminho:** `routes/fornecedores.py`

```python
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from utils.db import get_db_connection
from utils.formatadores import formatar_cnpj, formatar_ie_goias, formatar_telefone
from utils.decorators import admin_required

bp = Blueprint('fornecedores', __name__, url_prefix='/fornecedores')

@bp.route('/')
@login_required
def lista():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM fornecedores ORDER BY razao_social")
    fornecedores = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('fornecedores/lista.html', fornecedores=fornecedores)

@bp.route('/novo', methods=['GET', 'POST'])
@login_required
def novo():
    if request.method == 'POST':
        razao_social = request.form.get('razao_social', '').upper()
        nome_fantasia = request.form.get('nome_fantasia', '').upper() or None
        cnpj = formatar_cnpj(request.form.get('cnpj')) or None
        ie = formatar_ie_goias(request.form.get('ie')) or None
        endereco = request.form.get('endereco', '').upper() or None
        numero = request.form.get('numero') or None
        complemento = request.form.get('complemento', '').upper() or None
        bairro = request.form.get('bairro', '').upper() or None
        municipio = request.form.get('municipio', '').upper() or None
        uf = request.form.get('uf', '').upper() or None
        nome_vendedor = request.form.get('nome_vendedor', '').upper() or None
        telefone = formatar_telefone(request.form.get('telefone')) or None
        email = request.form.get('email') or None
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO fornecedores (
                razao_social, nome_fantasia, cnpj, ie, endereco, numero,
                complemento, bairro, municipio, uf, nome_vendedor, telefone, email
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (razao_social, nome_fantasia, cnpj, ie, endereco, numero,
              complemento, bairro, municipio, uf, nome_vendedor, telefone, email))
        conn.commit()
        cursor.close()
        conn.close()
        flash('Fornecedor cadastrado com sucesso!', 'success')
        return redirect(url_for('fornecedores.lista'))
    return render_template('fornecedores/novo.html')

@bp.route('/excluir/<int:id>')
@login_required
@admin_required
def excluir(id):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM fornecedores WHERE id = %s", (id,))
        conn.commit()
        flash('Fornecedor excluído com sucesso!', 'success')
    except Exception as e:
        flash(f'Erro: {str(e)}', 'danger')
    finally:
        cursor.close()
        conn.close()
    return redirect(url_for('fornecedores.lista'))
```

---
