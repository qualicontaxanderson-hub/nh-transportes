try:
    conn = get_db()  # use sua função para abrir conexão
    cursor = conn.cursor(dictionary=True)

    # Busca clientes
    cursor.execute("SELECT id, razao_social, paga_comissao FROM clientes ORDER BY razao_social")
    clientes = cursor.fetchall()

    # Busca fornecedores (TRECHO CORRIGIDO)
    cursor.execute("SELECT id, razao_social FROM fornecedores ORDER BY razao_social")
    fornecedores = cursor.fetchall()

    # Busca motoristas
    cursor.execute("SELECT id, nome FROM motoristas ORDER BY nome")
    motoristas = cursor.fetchall()

    # Busca veículos
    cursor.execute("SELECT id, placa, modelo FROM veiculos ORDER BY placa")
    veiculos = cursor.fetchall()

    # Busca quantidades
    cursor.execute("SELECT id, valor, descricao FROM quantidades ORDER BY valor")
    quantidades = cursor.fetchall()

    # Busca origens
    cursor.execute("SELECT id, nome FROM origens ORDER BY nome")
    origens = cursor.fetchall()

    # Busca destinos
    cursor.execute("SELECT id, nome FROM destinos ORDER BY nome")
    destinos = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template('fretes/novo.html',
                          clientes=clientes,
                          fornecedores=fornecedores,
                          motoristas=motoristas,
                          veiculos=veiculos,
                          quantidades=quantidades,
                          origens=origens,
                          destinos=destinos)

except Exception as e:
    print(f"Erro ao carregar formulário: {e}")
    flash(f'Erro ao carregar formulário: {str(e)}', 'danger')
    return redirect(url_for('index'))
