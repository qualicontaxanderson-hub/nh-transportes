import os
import mysql.connector
from datetime import datetime, timedelta
from efipay import EfiPay

def get_db_connection():
    """Retorna conexão com o banco de dados MySQL"""
    return mysql.connector.connect(
        host=os.getenv('DB_HOST'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_DATABASE'),
        port=int(os.getenv('DB_PORT', 3306))
    )

def emitir_boleto_frete(frete_id):
    """
    Emite um boleto via Efí (antiga Gerencianet) para um frete específico.
    
    Args:
        frete_id (int): ID do frete para emissão de boleto
    
    Returns:
        dict: {"success": True/False, "error": str, "charge_id": str, "boleto_url": str, "barcode": str}
    """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)  # IMPORTANTE: dictionary=True
    
    try:
        # Buscar dados do frete e cliente
        cursor.execute("""
            SELECT 
                f.*, 
                c.razaosocial as cliente_nome,
                c.nomefantasia as cliente_fantasia,
                c.cnpj as cliente_cnpj,
                c.endereco as cliente_endereco,
                c.numero as cliente_numero,
                c.complemento as cliente_complemento,
                c.bairro as cliente_bairro,
                c.municipio as cliente_cidade,
                c.uf as cliente_estado,
                c.cep as cliente_cep,
                c.telefone as cliente_telefone,
                c.email as cliente_email,
                o.nome as origem_nome,
                d.nome as destino_nome
            FROM fretes f
            INNER JOIN clientes c ON f.clientes_id = c.id
            LEFT JOIN origens o ON f.origem_id = o.id
            LEFT JOIN destinos d ON f.destino_id = d.id
            WHERE f.id = %s
        """, (frete_id,))
        
        frete = cursor.fetchone()
        
        if not frete:
            return {"success": False, "error": "Frete não encontrado"}
        
        # Validar dados obrigatórios
        if not frete.get('cliente_email'):
            return {"success": False, "error": "Cliente sem e-mail cadastrado"}
        
        if not frete.get('cliente_telefone'):
            return {"success": False, "error": "Cliente sem telefone cadastrado"}
        
        if not frete.get('cliente_cnpj'):
            return {"success": False, "error": "Cliente sem CNPJ cadastrado"}
        
        # Configurar credenciais Efí
        credentials = {
            'client_id': os.getenv('EFI_CLIENT_ID'),
            'client_secret': os.getenv('EFI_CLIENT_SECRET'),
            'certificate': os.getenv('EFI_CERT_PATH'),
            'sandbox': os.getenv('EFI_SANDBOX', 'true').lower() == 'true'
        }
        
        efi = EfiPay(credentials)
        
        # Data de vencimento: 7 dias a partir de hoje
        data_vencimento = datetime.now() + timedelta(days=7)
        
        # Limpar CNPJ/CPF
        cpf_cnpj = frete['cliente_cnpj'].replace('.', '').replace('-', '').replace('/', '').strip()
        
        # Limpar telefone
        telefone = frete['cliente_telefone'].replace('(', '').replace(')', '').replace('-', '').replace(' ', '').strip()
        
        # Limpar CEP
        cep = (frete.get('cliente_cep') or '').replace('-', '').strip()
        if not cep or len(cep) != 8:
            cep = '74000000'  # CEP padrão Goiânia
        
        # Nome do cliente
        nome_cliente = frete.get('cliente_fantasia') or frete.get('cliente_nome') or 'Cliente'
        
        # Descrição do item
        descricao_frete = f"Frete #{frete['id']}"
        if frete.get('origem_nome') and frete.get('destino_nome'):
            descricao_frete += f" - {frete['origem_nome']} para {frete['destino_nome']}"
        
        # Valor total (converter para centavos)
        valor_total_centavos = int(float(frete['valor_total_frete'] or 0) * 100)
        
        if valor_total_centavos <= 0:
            return {"success": False, "error": "Valor do frete inválido ou zerado"}
        
        # Montar payload para API Efí
        body = {
            'payment': {
                'banking_billet': {
                    'expire_at': data_vencimento.strftime('%Y-%m-%d'),
                    'customer': {
                        'name': nome_cliente[:80],
                        'cpf': cpf_cnpj if len(cpf_cnpj) == 11 else None,
                        'cnpj': cpf_cnpj if len(cpf_cnpj) == 14 else None,
                        'phone_number': telefone[:11],
                        'email': frete['cliente_email'][:50],
                        'address': {
                            'street': (frete.get('cliente_endereco') or 'Rua Exemplo')[:80],
                            'number': (frete.get('cliente_numero') or 'SN')[:10],
                            'neighborhood': (frete.get('cliente_bairro') or 'Centro')[:50],
                            'zipcode': cep,
                            'city': (frete.get('cliente_cidade') or 'Goiania')[:50],
                            'state': (frete.get('cliente_estado') or 'GO')[:2].upper()
                        }
                    }
                }
            },
            'items': [{
                'name': descricao_frete[:80],
                'amount': 1,
                'value': valor_total_centavos
            }],
            'metadata': {
                'custom_id': str(frete_id),
                'notification_url': os.getenv('EFI_NOTIFICATION_URL', 'https://nh-transportes.onrender.com/webhooks/efi')
            }
        }
        
        # Criar cobrança na Efí
        response = efi.create_charge(body=body)
        
        # Extrair dados da resposta
        charge_id = response['data']['charge_id']
        boleto_url = response['data']['payment']['banking_billet']['link']
        barcode = response['data']['payment']['banking_billet']['barcode']
        
        # Salvar na tabela recebimentos
        cursor.execute("""
            INSERT INTO recebimentos 
            (frete_id, cliente_id, valor, data_vencimento, status, charge_id, boleto_url, codigo_barras, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
        """, (
            frete_id,
            frete['clientes_id'],
            frete['valor_total_frete'],
            data_vencimento.strftime('%Y-%m-%d'),
            'pendente',
            charge_id,
            boleto_url,
            barcode
        ))
        
        recebimento_id = cursor.lastrowid
        
        conn.commit()
        
        return {
            "success": True,
            "recebimento_id": recebimento_id,
            "charge_id": charge_id,
            "boleto_url": boleto_url,
            "barcode": barcode
        }
        
    except Exception as e:
        conn.rollback()
        return {"success": False, "error": str(e)}
    finally:
        cursor.close()
        conn.close()
