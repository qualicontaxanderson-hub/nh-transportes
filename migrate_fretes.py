#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script de Migração: lancamento_frete -> fretes

Execute este script para migrar os dados da tabela antiga para a nova tabela fretes.
Python: python3 migrate_fretes.py
"""

import mysql.connector
from config import Config

# Use database configuration from config.py
DB_HOST = Config.DB_HOST
DB_PORT = Config.DB_PORT
DB_USER = Config.DB_USER
DB_PASSWORD = Config.DB_PASSWORD
DB_NAME = Config.DB_NAME

def migrar_fretes():
    """
    Executa a migração de dados da tabela lancamento_frete para fretes
    """
    try:
        # Conectar ao banco
        print(f"🔗 Conectando ao banco de dados {DB_NAME}...")
        conn = mysql.connector.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME
        )
        cursor = conn.cursor()
        print("✅ Conectado com sucesso!")
        
        # SQL de migração
        sql_migrate = """
        INSERT INTO fretes (
            id, clientes_id, fornecedores_id, motoristas_id, veiculos_id,
            quantidade_id, origem_id, destino_id, preco_produto_unitario,
            total_nf_compra, preco_por_litro, valor_total_frete,
            comissao_motorista, valor_cte, comissao_cte, lucro,
            data_frete, status
        )
        SELECT 
            lf.id, lf.clientes_id, COALESCE(lf.fornecedores_id, 1),
            lf.motoristas_id, COALESCE(lf.veiculos_id, 1),
            COALESCE(lf.quantidade_id, 1),
            COALESCE(lf.origem_produto_id, 1), 1,
            COALESCE(lf.preco_produto_unitario, 0.00),
            COALESCE(lf.total_nf_compra, 0.00),
            COALESCE(lf.preco_litro, 0.00),
            COALESCE(lf.vlr_total_frete, 0.00),
            COALESCE(lf.comissao_motorista, 0.00),
            COALESCE(lf.vlr_cte, 0.00),
            COALESCE(lf.comissao_cte, 0.00),
            COALESCE(lf.lucro, 0.00),
            COALESCE(lf.data_frete, '2025-01-01'),
            'concluido'
        FROM lancamento_frete lf
        WHERE lf.clientes_id IS NOT NULL AND lf.motoristas_id IS NOT NULL
        """
        
        print("\n📊 Executando migração...")
        cursor.execute(sql_migrate)
        conn.commit()
        
        total_migrados = cursor.rowcount
        print(f"\n✅ Migração concluída com sucesso!")
        print(f"📈 Total de registros migrados: {total_migrados}")
        
        # Verificar resultado
        cursor.execute("SELECT COUNT(*) FROM fretes")
        total_fretes = cursor.fetchone()[0]
        print(f"📋 Total de registros na tabela 'fretes': {total_fretes}")
        
        cursor.close()
        conn.close()
        
    except mysql.connector.Error as err:
        if err.errno == 2003:
            print(f"❌ ERRO: Não conseguiu conectar ao banco de dados em {DB_HOST}:{DB_PORT}")
            print("   Verifique se o servidor MySQL está rodando.")
        elif err.errno == 1045:
            print(f"❌ ERRO: Usuário ou senha incorretos para {DB_USER}")
        else:
            print(f"❌ ERRO DE BANCO DE DADOS: {err}")
        return False
    except Exception as e:
        print(f"❌ ERRO: {str(e)}")
        return False
    
    return True

if __name__ == '__main__':
    print("\n" + "="*60)
    print("🚚 MIGRAÇÃO DE FRETES")
    print("lancamento_frete -> fretes")
    print("="*60 + "\n")
    
    success = migrar_fretes()
    
    print("\n" + "="*60)
    if success:
        print("🎉 Processo finalizado com sucesso!")
    else:
        print("⚠️  Processo finalizado com erros.")
    print("="*60 + "\n")
