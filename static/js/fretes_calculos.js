/**
 * Funções de cálculo para formulário de fretes
 * Versão corrigida com regras de negócio do sistema
 */

// Função para converter formato brasileiro (1.234,56) para número (1234.56)
function converterBrasileiro(valor) {
    if (!valor || valor === '') return 0;
    return parseFloat(valor.replace(/\./g, '').replace(',', '.')) || 0;
}

// Função para formatar número para formato brasileiro
function formatarBrasileiro(numero) {
    if (isNaN(numero)) return '0,00';
    return numero.toLocaleString('pt-BR', { 
        minimumFractionDigits: 2, 
        maximumFractionDigits: 2 
    });
}

// Função para extrair quantidade corretamente
function obterQuantidade() {
    const selectQtd = document.querySelector('#quantidade_id');
    if (!selectQtd || !selectQtd.selectedOptions[0]) return 0;
    
    let dataLitros = selectQtd.selectedOptions[0].getAttribute('data-litros');
    const quantidade = parseInt(dataLitros.replace(/[^0-9]/g, '')) || 0;
    return quantidade;
}

// Função para obter dados do cliente selecionado
function obterDadosCliente() {
    const selectCliente = document.querySelector('#clientes_id');
    if (!selectCliente || !selectCliente.selectedOptions[0]) {
        return { pagaComissao: false, percentualCte: 0, cteIntegral: false };
    }
    
    const option = selectCliente.selectedOptions[0];
    return {
        pagaComissao: option.getAttribute('data-paga-comissao') === 'True',
        percentualCte: parseFloat(option.getAttribute('data-percentual-cte')) || 0,
        cteIntegral: option.getAttribute('data-cte-integral') === 'True'
    };
}

// Função para obter dados do motorista selecionado
function obterDadosMotorista() {
    const selectMotorista = document.querySelector('#motoristas_id');
    if (!selectMotorista || !selectMotorista.selectedOptions[0]) {
        return { pagaComissao: false };
    }
    
    const option = selectMotorista.selectedOptions[0];
    return {
        pagaComissao: option.getAttribute('data-paga-comissao') === 'True'
    };
}

// Função principal de cálculo
function calcularFrete() {
    try {
        // Obter valores dos campos
        const quantidade = obterQuantidade();
        const preco_unitario = converterBrasileiro(
            document.querySelector('#preco_produto_unitario').value
        );
        const preco_por_litro = converterBrasileiro(
            document.querySelector('#preco_por_litro').value
        );
        
        // Obter dados do cliente e motorista
        const dadosCliente = obterDadosCliente();
        const dadosMotorista = obterDadosMotorista();
        
        // ===== CÁLCULOS BÁSICOS =====
        const total_nf_compra = quantidade * preco_unitario;
        const valor_total_frete = quantidade * preco_por_litro;
        
        // ===== COMISSÃO MOTORISTA =====
        // Verifica se Cliente paga comissão E se Motorista recebe comissão
        let comissao_motorista = 0;
        if (dadosCliente.pagaComissao && dadosMotorista.pagaComissao) {
            comissao_motorista = valor_total_frete * 0.01; // 1% do valor do frete
        }
        
        // ===== VALOR CTe =====
        // Regra: depende de Cliente + Origem + Destino
        // Se cteIntegral = True, valor CTe = valor do frete
        // Se cteIntegral = False, valor CTe = valor do frete * percentualCte
        let valor_cte = 0;
        if (dadosCliente.cteIntegral) {
            valor_cte = valor_total_frete;
        } else {
            valor_cte = valor_total_frete * (dadosCliente.percentualCte / 100);
        }
        
        // ===== COMISSÃO CTe =====
        // 8% do Valor CTe
        const comissao_cte = valor_cte * 0.08;
        
        // ===== LUCRO =====
        const lucro = valor_total_frete - comissao_motorista - comissao_cte;
        
        // ===== ATUALIZAR CAMPOS =====
        document.querySelector('#total_nf_compra').value = formatarBrasileiro(total_nf_compra);
        document.querySelector('#valor_total_frete').value = formatarBrasileiro(valor_total_frete);
        document.querySelector('#comissao_motorista').value = formatarBrasileiro(comissao_motorista);
        document.querySelector('#valor_cte').value = formatarBrasileiro(valor_cte);
        document.querySelector('#comissao_cte').value = formatarBrasileiro(comissao_cte);
        document.querySelector('#lucro').value = formatarBrasileiro(lucro);
        
    } catch (err) {
        console.error('Erro ao calcular frete:', err);
    }
}

// Inicializar quando o DOM estiver pronto
document.addEventListener('DOMContentLoaded', function() {
    // Campos que disparam o cálculo
    const camposCalculo = [
        'quantidade_id', 
        'preco_produto_unitario', 
        'preco_por_litro',
        'clientes_id',      // Cliente afeta comissões
        'motoristas_id'     // Motorista afeta comissão
    ];
    
    camposCalculo.forEach(campo => {
        const elemento = document.querySelector('#' + campo);
        if (elemento) {
            elemento.addEventListener('change', calcularFrete);
            elemento.addEventListener('input', calcularFrete);
        }
    });
    
    // Executar cálculo ao carregar a página
    calcularFrete();
});
