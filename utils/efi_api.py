"""
Utilitário para integração com API EFI Bank (PIX/Boleto)
NH Transportes - Sistema de Gestão de Fretes

Documentação EFI: https://dev.efipay.com.br/docs/api-pix/
"""

import os
import json
import base64
import tempfile
import requests
from datetime import datetime, timedelta
from typing import Optional
from flask import current_app


class EfiAPI:
    """
    Classe para integração com a API EFI Bank.
    Suporta criação de cobranças PIX e Boleto.
    """

    # URLs base da API EFI
    SANDBOX_URL = "https://pix-h.api.efipay.com.br"
    PRODUCAO_URL = "https://pix.api.efipay.com.br"

    # URLs para boleto
    SANDBOX_BOLETO_URL = "https://cobrancas-h.api.efipay.com.br/v1"
    PRODUCAO_BOLETO_URL = "https://cobrancas.api.efipay.com.br/v1"

    def __init__(self, client_id: str, client_secret: str,
                 certificado_pem: str = None, ambiente: str = 'sandbox',
                 chave_pix: str = None):
        """
        Inicializa a API EFI.

        Args:
            client_id: Client ID da aplicação EFI
            client_secret: Client Secret da aplicação EFI
            certificado_pem: Conteúdo do certificado .pem (obrigatório para PIX)
            ambiente: 'sandbox' ou 'producao'
            chave_pix: Chave PIX cadastrada na conta EFI
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self.certificado_pem = certificado_pem
        self.ambiente = ambiente
        self.chave_pix = chave_pix
        self._access_token = None
        self._token_expira = None
        self._cert_file = None

        # Define URLs baseado no ambiente
        if ambiente == 'producao':
            self.base_url = self.PRODUCAO_URL
            self.boleto_url = self.PRODUCAO_BOLETO_URL
        else:
            self.base_url = self.SANDBOX_URL
            self.boleto_url = self.SANDBOX_BOLETO_URL

    def _get_cert_file(self) -> Optional[str]:
        """Cria arquivo temporário com o certificado."""
        if not self.certificado_pem:
            return None

        if self._cert_file and os.path.exists(self._cert_file):
            return self._cert_file

        # Decodifica se estiver em base64
        try:
            cert_content = base64.b64decode(self.certificado_pem).decode('utf-8')
        except Exception:
            cert_content = self.certificado_pem

        # Cria arquivo temporário
        fd, path = tempfile.mkstemp(suffix='.pem')
        with os.fdopen(fd, 'w') as f:
            f.write(cert_content)

        self._cert_file = path
        return path

    def _cleanup_cert(self):
        """Remove arquivo temporário do certificado."""
        if self._cert_file and os.path.exists(self._cert_file):
            try:
                os.remove(self._cert_file)
            except Exception:
                pass
            self._cert_file = None

    def obter_token(self) -> str:
        """
        Obtém token de acesso OAuth2 da API EFI.

        Returns:
            Token de acesso
        """
        # Verifica se token ainda é válido
        if self._access_token and self._token_expira:
            if datetime.now() < self._token_expira:
                return self._access_token

        auth_url = f"{self.base_url}/oauth/token"

        # Credenciais em base64
        credentials = f"{self.client_id}:{self.client_secret}"
        auth_header = base64.b64encode(credentials.encode()).decode()

        headers = {
            "Authorization": f"Basic {auth_header}",
            "Content-Type": "application/json"
        }

        payload = {
            "grant_type": "client_credentials"
        }

        cert_file = self._get_cert_file()

        try:
            response = requests.post(
                auth_url,
                headers=headers,
                json=payload,
                cert=cert_file,
                timeout=30
            )
            response.raise_for_status()

            data = response.json()
            self._access_token = data['access_token']
            # Token expira em 'expires_in' segundos (geralmente 3600)
            expires_in = data.get('expires_in', 3600)
            self._token_expira = datetime.now() + timedelta(seconds=expires_in - 60)

            return self._access_token

        except requests.exceptions.RequestException as e:
            current_app.logger.error(f"Erro ao obter token EFI: {e}")
            raise Exception(f"Erro ao autenticar na API EFI: {str(e)}")

    def criar_cobranca_pix(self, valor: float, descricao: str,
                           pagador_cpf: str = None, pagador_nome: str = None,
                           expiracao: int = 3600) -> dict:
        """
        Cria uma cobrança PIX imediata.

        Args:
            valor: Valor da cobrança em reais
            descricao: Descrição da cobrança
            pagador_cpf: CPF do pagador (opcional)
            pagador_nome: Nome do pagador (opcional)
            expiracao: Tempo de expiração em segundos (padrão: 1 hora)

        Returns:
            Dados da cobrança criada
        """
        token = self.obter_token()
        url = f"{self.base_url}/v2/cob"

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        payload = {
            "calendario": {
                "expiracao": expiracao
            },
            "valor": {
                "original": f"{valor:.2f}"
            },
            "chave": self.chave_pix,
            "solicitacaoPagador": descricao[:140]  # Limite de 140 caracteres
        }

        # Adiciona dados do devedor se fornecidos
        if pagador_cpf and pagador_nome:
            cpf_limpo = ''.join(filter(str.isdigit, pagador_cpf))
            if len(cpf_limpo) == 11:
                payload["devedor"] = {
                    "cpf": cpf_limpo,
                    "nome": pagador_nome[:200]
                }
            elif len(cpf_limpo) == 14:
                payload["devedor"] = {
                    "cnpj": cpf_limpo,
                    "nome": pagador_nome[:200]
                }

        cert_file = self._get_cert_file()

        try:
            response = requests.post(
                url,
                headers=headers,
                json=payload,
                cert=cert_file,
                timeout=30
            )
            response.raise_for_status()

            cob_data = response.json()

            # Busca o QR Code
            qrcode_data = self._gerar_qrcode(cob_data.get('loc', {}).get('id'))

            return {
                'sucesso': True,
                'txid': cob_data.get('txid'),
                'location': cob_data.get('loc', {}).get('location'),
                'status': cob_data.get('status'),
                'valor': valor,
                'qrcode_base64': qrcode_data.get('imagemQrcode'),
                'pix_copia_cola': qrcode_data.get('qrcode'),
                'expiracao': expiracao,
                'resposta_completa': cob_data
            }

        except requests.exceptions.RequestException as e:
            current_app.logger.error(f"Erro ao criar cobrança PIX: {e}")
            return {
                'sucesso': False,
                'erro': str(e),
                'resposta_completa': getattr(e.response, 'text', None) if hasattr(e, 'response') else None
            }

    def _gerar_qrcode(self, loc_id: int) -> dict:
        """Gera QR Code para uma cobrança PIX."""
        if not loc_id:
            return {}

        token = self.obter_token()
        url = f"{self.base_url}/v2/loc/{loc_id}/qrcode"

        headers = {
            "Authorization": f"Bearer {token}",
        }

        cert_file = self._get_cert_file()

        try:
            response = requests.get(
                url,
                headers=headers,
                cert=cert_file,
                timeout=30
            )
            response.raise_for_status()
            return response.json()

        except Exception as e:
            current_app.logger.error(f"Erro ao gerar QR Code: {e}")
            return {}

    def consultar_pix(self, txid: str) -> dict:
        """
        Consulta o status de uma cobrança PIX.

        Args:
            txid: ID da transação

        Returns:
            Dados atualizados da cobrança
        """
        token = self.obter_token()
        url = f"{self.base_url}/v2/cob/{txid}"

        headers = {
            "Authorization": f"Bearer {token}",
        }

        cert_file = self._get_cert_file()

        try:
            response = requests.get(
                url,
                headers=headers,
                cert=cert_file,
                timeout=30
            )
            response.raise_for_status()
            return {
                'sucesso': True,
                'dados': response.json()
            }

        except requests.exceptions.RequestException as e:
            current_app.logger.error(f"Erro ao consultar PIX: {e}")
            return {
                'sucesso': False,
                'erro': str(e)
            }

    def criar_boleto(self, valor: float, descricao: str,
                     pagador_nome: str, pagador_cpf_cnpj: str,
                     pagador_endereco: str = None, pagador_cidade: str = None,
                     pagador_uf: str = None, pagador_cep: str = None,
                     vencimento: str = None) -> dict:
        """
        Cria um boleto bancário.

        Args:
            valor: Valor do boleto
            descricao: Descrição/mensagem do boleto
            pagador_nome: Nome do pagador
            pagador_cpf_cnpj: CPF ou CNPJ do pagador
            pagador_endereco: Endereço do pagador
            pagador_cidade: Cidade do pagador
            pagador_uf: UF do pagador
            pagador_cep: CEP do pagador
            vencimento: Data de vencimento (YYYY-MM-DD)

        Returns:
            Dados do boleto criado
        """
        token = self.obter_token()
        url = f"{self.boleto_url}/charge/one-step"

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        # Define vencimento padrão (3 dias)
        if not vencimento:
            vencimento = (datetime.now() + timedelta(days=3)).strftime('%Y-%m-%d')

        cpf_cnpj_limpo = ''.join(filter(str.isdigit, pagador_cpf_cnpj))

        payload = {
            "items": [
                {
                    "name": descricao[:255],
                    "value": int(valor * 100),  # Valor em centavos
                    "amount": 1
                }
            ],
            "payment": {
                "banking_billet": {
                    "expire_at": vencimento,
                    "customer": {
                        "name": pagador_nome[:255],
                        "cpf": cpf_cnpj_limpo if len(cpf_cnpj_limpo) == 11 else None,
                        "cnpj": cpf_cnpj_limpo if len(cpf_cnpj_limpo) == 14 else None,
                        "email": None,
                        "phone_number": None
                    }
                }
            }
        }

        # Remove campos None do customer
        payload["payment"]["banking_billet"]["customer"] = {
            k: v for k, v in payload["payment"]["banking_billet"]["customer"].items()
            if v is not None
        }

        # Adiciona endereço se disponível
        if all([pagador_endereco, pagador_cidade, pagador_uf, pagador_cep]):
            payload["payment"]["banking_billet"]["customer"]["address"] = {
                "street": pagador_endereco[:200],
                "city": pagador_cidade[:100],
                "state": pagador_uf[:2],
                "zipcode": ''.join(filter(str.isdigit, pagador_cep))
            }

        try:
            response = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=30
            )
            response.raise_for_status()

            boleto_data = response.json()

            return {
                'sucesso': True,
                'charge_id': boleto_data.get('data', {}).get('charge_id'),
                'nosso_numero': boleto_data.get('data', {}).get('barcode'),
                'codigo_barras': boleto_data.get('data', {}).get('barcode'),
                'linha_digitavel': boleto_data.get('data', {}).get('line'),
                'link_boleto': boleto_data.get('data', {}).get('link'),
                'pdf': boleto_data.get('data', {}).get('pdf', {}).get('charge'),
                'status': boleto_data.get('data', {}).get('status'),
                'vencimento': vencimento,
                'resposta_completa': boleto_data
            }

        except requests.exceptions.RequestException as e:
            current_app.logger.error(f"Erro ao criar boleto: {e}")
            error_msg = str(e)
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_detail = e.response.json()
                    error_msg = error_detail.get('error_description', str(e))
                except Exception:
                    error_msg = e.response.text or str(e)

            return {
                'sucesso': False,
                'erro': error_msg
            }

    def __del__(self):
        """Limpa recursos ao destruir objeto."""
        self._cleanup_cert()


def get_efi_config():
    """
    Obtém a configuração ativa da API EFI do banco de dados.

    Returns:
        Dicionário com as configurações ou None se não configurado
    """
    from utils.db import get_db_connection

    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT * FROM efi_config 
            WHERE ativo = TRUE 
            ORDER BY id DESC 
            LIMIT 1
        """)
        config = cursor.fetchone()
        return config
    except Exception as e:
        current_app.logger.error(f"Erro ao buscar configuração EFI: {e}")
        return None
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def get_efi_api():
    """
    Retorna uma instância configurada da API EFI.

    Returns:
        Instância de EfiAPI ou None se não configurado
    """
    config = get_efi_config()
    if not config:
        return None

    return EfiAPI(
        client_id=config['client_id'],
        client_secret=config['client_secret'],
        certificado_pem=config.get('certificado_pem'),
        ambiente=config.get('ambiente', 'sandbox'),
        chave_pix=config.get('chave_pix')
    )
