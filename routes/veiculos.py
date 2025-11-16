from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
import mysql.connector
import os

veiculos_bp = Blueprint('veiculos', __name__)

def get_db_connection():
    """Cria e retorna uma conexão com o banco de dados"""
    conn = mysql.connector.connect(
        host=os.getenv('DB_HOST'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_NAME'),
        port=int(os.getenv('DB_PORT', 3306))
    )
    return conn

@veiculos_bp.route('/listar')
@login_required
def lista():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        cursor.execute("SELECT * FROM veiculos ORDER BY id DESC")
        veiculos = cursor.fetchall()
        return render_template('veiculos/lista.html', veiculos=veiculos)
    except Exception as e:
        flash(f'Erro ao listar veículos: {str(e)}', 'error')
        return redirect(url_for('index'))
    finally:
        cursor.close()
        conn.close()

@veiculos_bp.route('/adicionar', methods=['GET', 'POST'])
@login_required
def adicionar():
    if request.method == 'POST':
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            placa = request.form.get('placa')
            modelo = request.form.get('modelo')
            ano = request.form.get('ano')
            
            cursor.execute(
                "INSERT INTO veiculos (placa, modelo, ano) VALUES (%s, %s, %s)",
                (placa, modelo, ano)
            )
            conn.commit()
            flash('Veículo adicionado com sucesso!', 'success')
            return redirect(url_for('veiculos.lista'))
        except Exception as e:
            conn.rollback()
            flash(f'Erro ao adicionar veículo: {str(e)}', 'error')
            return redirect(url_for('veiculos.adicionar'))
        finally:
            cursor.close()
            conn.close()
    
    return render_template('veiculos/adicionar.html')

@veiculos_bp.route('/editar/<int:id>', methods=['GET', 'POST'])
@login_required
def editar(id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    if request.method == 'POST':
        try:
            placa = request.form.get('placa')
            modelo = request.form.get('modelo')
            ano = request.form.get('ano')
            
            cursor.execute(
                "UPDATE veiculos SET placa=%s, modelo=%s, ano=%s WHERE id=%s",
                (placa, modelo, ano, id)
            )
            conn.commit()
            flash('Veículo atualizado com sucesso!', 'success')
            return redirect(url_for('veiculos.lista'))
        except Exception as e:
            conn.rollback()
            flash(f'Erro ao atualizar veículo: {str(e)}', 'error')
        finally:
            cursor.close()
            conn.close()
    
    try:
        cursor.execute("SELECT * FROM veiculos WHERE id = %s", (id,))
        veiculo = cursor.fetchone()
        
        if not veiculo:
            flash('Veículo não encontrado!', 'error')
            return redirect(url_for('veiculos.lista'))
        
        return render_template('veiculos/editar.html', veiculo=veiculo)
    except Exception as e:
        flash(f'Erro ao buscar veículo: {str(e)}', 'error')
        return redirect(url_for('veiculos.lista'))
    finally:
        cursor.close()
        conn.close()

@veiculos_bp.route('/deletar/<int:id>')
@login_required
def deletar(id):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("DELETE FROM veiculos WHERE id = %s", (id,))
        conn.commit()
        flash('Veículo deletado com sucesso!', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Erro ao deletar veículo: {str(e)}', 'error')
    finally:
        cursor.close()
        conn.close()
    
    return redirect(url_for('veiculos.lista'))
