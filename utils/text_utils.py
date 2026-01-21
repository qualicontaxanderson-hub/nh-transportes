# -*- coding: utf-8 -*-
"""
Utilitários para normalização de texto
Garante que dados sejam salvos consistentemente no banco de dados
"""

def normalize_text_field(value):
    """
    Normaliza um campo de texto para maiúsculas
    Remove espaços extras e converte para uppercase
    
    Args:
        value: String a ser normalizada
        
    Returns:
        String normalizada em maiúsculas ou None se entrada for None/vazia
    """
    if value is None:
        return None
    
    # Converte para string se não for
    value = str(value)
    
    # Remove espaços extras e converte para maiúsculas
    normalized = value.strip().upper()
    
    # Retorna None se string vazia
    return normalized if normalized else None


def normalize_form_data(form_data, exclude_fields=None):
    """
    Normaliza todos os campos de texto de um dicionário de dados de formulário
    
    Args:
        form_data: Dicionário com dados do formulário
        exclude_fields: Lista de campos que não devem ser normalizados
                       (ex: ['email', 'password', 'observacao'])
    
    Returns:
        Dicionário com dados normalizados
    """
    if exclude_fields is None:
        exclude_fields = ['email', 'senha', 'password', 'observacao', 'observacoes']
    
    normalized_data = {}
    
    for key, value in form_data.items():
        # Se é um campo excluído ou não é string, mantém valor original
        if key.lower() in [f.lower() for f in exclude_fields] or not isinstance(value, str):
            normalized_data[key] = value
        else:
            # Normaliza o campo
            normalized_data[key] = normalize_text_field(value)
    
    return normalized_data


def normalize_nome(nome):
    """
    Normaliza especificamente um campo de nome
    Alias para normalize_text_field para clareza no código
    """
    return normalize_text_field(nome)
