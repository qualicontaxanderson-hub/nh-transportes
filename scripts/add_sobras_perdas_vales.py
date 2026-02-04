#!/usr/bin/env python3
"""
Script para adicionar suporte a sobras, perdas e vales de funcionários
no arquivo routes/lancamentos_caixa.py
"""

def modify_lancamentos_caixa():
    file_path = '/home/runner/work/nh-transportes/nh-transportes/routes/lancamentos_caixa.py'
    
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Adicionar imports de sobras/perdas/vales após linha de comprovacoes
    # Primeira ocorrência (função novo - linha ~389-404)
    old_calc_section_novo = '''            # Get comprovacoes (right side) - JSON encoded
            comprovacoes_json = request.form.get('comprovacoes', '[]')
            comprovacoes = json.loads(comprovacoes_json)
            
            # Validate
            if not data:
                flash('Data é obrigatória!', 'danger')
                raise ValueError('Data não fornecida')
            
            if not cliente_id:
                flash('Cliente é obrigatório!', 'danger')
                raise ValueError('Cliente não fornecido')
            
            # Calculate totals: Diferença = Total Comprovação - Total Receitas
            total_receitas = sum(parse_brazilian_currency(r.get('valor', 0)) for r in receitas)
            total_comprovacao = sum(parse_brazilian_currency(c.get('valor', 0)) for c in comprovacoes)
            diferenca = total_comprovacao - total_receitas
            
            # Insert lancamento_caixa
            cursor.execute("""
                INSERT INTO lancamentos_caixa'''
    
    new_calc_section_novo = '''            # Get comprovacoes (right side) - JSON encoded
            comprovacoes_json = request.form.get('comprovacoes', '[]')
            comprovacoes = json.loads(comprovacoes_json)
            
            # Get sobras de funcionários (receitas) - JSON encoded
            sobras_json = request.form.get('sobras_funcionarios', '[]')
            sobras_funcionarios = json.loads(sobras_json)
            
            # Get perdas de funcionários (comprovações) - JSON encoded
            perdas_json = request.form.get('perdas_funcionarios', '[]')
            perdas_funcionarios = json.loads(perdas_json)
            
            # Get vales de funcionários (comprovações) - JSON encoded
            vales_json = request.form.get('vales_funcionarios', '[]')
            vales_funcionarios = json.loads(vales_json)
            
            # Validate
            if not data:
                flash('Data é obrigatória!', 'danger')
                raise ValueError('Data não fornecida')
            
            if not cliente_id:
                flash('Cliente é obrigatório!', 'danger')
                raise ValueError('Cliente não fornecido')
            
            # Calculate totals: Diferença = Total Comprovação - Total Receitas
            # Include sobras in receitas and perdas+vales in comprovações
            total_receitas = sum(parse_brazilian_currency(r.get('valor', 0)) for r in receitas)
            total_sobras = sum(parse_brazilian_currency(s.get('valor', 0)) for s in sobras_funcionarios)
            total_receitas += total_sobras
            
            total_comprovacao = sum(parse_brazilian_currency(c.get('valor', 0)) for c in comprovacoes)
            total_perdas = sum(parse_brazilian_currency(p.get('valor', 0)) for p in perdas_funcionarios)
            total_vales = sum(parse_brazilian_currency(v.get('valor', 0)) for v in vales_funcionarios)
            total_comprovacao += total_perdas + total_vales
            
            diferenca = total_comprovacao - total_receitas
            
            # Insert lancamento_caixa
            cursor.execute("""
                INSERT INTO lancamentos_caixa'''
    
    # Substituir primeira ocorrência
    if old_calc_section_novo in content:
        content = content.replace(old_calc_section_novo, new_calc_section_novo, 1)
        print("✓ Seção de cálculo da função novo() atualizada")
    else:
        print("✗ Não foi possível encontrar a seção de cálculo da função novo()")
        return False
    
    # Adicionar salvamento dos dados de funcionários antes do commit
    old_commit = '''                          float(parse_brazilian_currency(comprovacao['valor']))))
            
            conn.commit()
            flash('Lançamento de caixa cadastrado com sucesso!', 'success')
            return redirect(url_for('lancamentos_caixa.lista'))'''
    
    new_commit = '''                          float(parse_brazilian_currency(comprovacao['valor']))))
            
            # Insert sobras de funcionários (receitas)
            for sobra in sobras_funcionarios:
                if sobra.get('funcionario_id') and sobra.get('valor'):
                    valor = parse_brazilian_currency(sobra['valor'])
                    if valor > 0:  # Só inserir se tiver valor
                        cursor.execute(\"""
                            INSERT INTO lancamentos_caixa_sobras_funcionarios 
                            (lancamento_caixa_id, funcionario_id, valor, observacao)
                            VALUES (%s, %s, %s, %s)
                        \""", (lancamento_id, int(sobra['funcionario_id']), 
                              float(valor), sobra.get('observacao', '')))
            
            # Insert perdas de funcionários (comprovações)
            for perda in perdas_funcionarios:
                if perda.get('funcionario_id') and perda.get('valor'):
                    valor = parse_brazilian_currency(perda['valor'])
                    if valor > 0:  # Só inserir se tiver valor
                        cursor.execute(\"""
                            INSERT INTO lancamentos_caixa_perdas_funcionarios 
                            (lancamento_caixa_id, funcionario_id, valor, observacao)
                            VALUES (%s, %s, %s, %s)
                        \""", (lancamento_id, int(perda['funcionario_id']), 
                              float(valor), perda.get('observacao', '')))
            
            # Insert vales de funcionários (comprovações)
            for vale in vales_funcionarios:
                if vale.get('funcionario_id') and vale.get('valor'):
                    valor = parse_brazilian_currency(vale['valor'])
                    if valor > 0:  # Só inserir se tiver valor
                        cursor.execute(\"""
                            INSERT INTO lancamentos_caixa_vales_funcionarios 
                            (lancamento_caixa_id, funcionario_id, valor, observacao)
                            VALUES (%s, %s, %s, %s)
                        \""", (lancamento_id, int(vale['funcionario_id']), 
                              float(valor), vale.get('observacao', '')))
            
            conn.commit()
            flash('Lançamento de caixa cadastrado com sucesso!', 'success')
            return redirect(url_for('lancamentos_caixa.lista'))'''
    
    # Substituir primeira ocorrência do commit
    if old_commit in content:
        content = content.replace(old_commit, new_commit, 1)
        print("✓ Código de salvamento de sobras/perdas/vales adicionado na função novo()")
    else:
        print("✗ Não foi possível encontrar o código de commit da função novo()")
        return False
    
    # Salvar arquivo modificado
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print("✓ Arquivo atualizado com sucesso!")
    return True

if __name__ == '__main__':
    success = modify_lancamentos_caixa()
    exit(0 if success else 1)
