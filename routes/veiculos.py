**Caminho:** `routes/veiculos.py`

```python
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from utils.db import get_db_connection
from utils.decorators import admin_required

bp = Blueprint('veiculos', __name__, url_prefix='/veiculos')

@bp.route('/')
@login_required
def lista():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM veiculos ORDER BY caminhao")
    veiculos = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('veiculos/lista.html', veiculos=veiculos)

@bp.route('/novo', methods=['GET', 'POST'])
@login_required
def novo():
    if request.method == 'POST':
        caminhao = request.form.get('caminhao', '').upper()
        placa = request.form.get('placa', '').upper()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO veiculos (caminhao, placa) VALUES (%s, %s)", (caminhao, placa))
        conn.commit()
        cursor.close()
        conn.close()
        flash('Veículo cadastrado!', 'success')
        return redirect(url_for('veiculos.lista'))
    return render_template('veiculos/novo.html')

@bp.route('/excluir/<int:id>')
@login_required
@admin_required
def excluir(id):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM veiculos WHERE id = %s", (id,))
        conn.commit()
        flash('Veículo excluído!', 'success')
    except Exception as e:
        flash(f'Erro: {str(e)}', 'danger')
    finally:
        cursor.close()
        conn.close()
    return redirect(url_for('veiculos.lista'))
```

---
