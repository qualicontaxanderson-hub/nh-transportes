/**
 * Funções de cálculo para formulário de fretes
 * Corrige os problemas com parsing de quantidade e valores em formato brasileiro
 */

// Função para converter formato brasileiro (1.234,56) para número (1234.56)
function converterBrasileiro(valor) {
    if (!valor || valor === '') return 0;
    // Remove pontos de milhar e substitui vírgula por ponto
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
    // Extrai apenas os números do texto "3.000 litros" para "3000"
    const quantidade = parseInt(dataLitros.replace(/[^0-9]/g, '')) || 0;
    return quantidade; // ✅ CORRIGIDO: Agora retorna o valor!
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
        
        // CÁLCULOS CORRETOS
        const total_nf_compra = quantidade * preco_unitario;
        const valor_total_frete = quantidade * preco_por_litro;
        const comissao_motorista = valor_total_frete * 0.01; // 1% do valor do frete
        
        // Atualizar campos readonly com valores formatados
        document.querySelector('#total_nf_compra').value = formatarBrasileiro(total_nf_compra);
        document.querySelector('#valor_total_frete').value = formatarBrasileiro(valor_total_frete);
        document.querySelector('#comissao_motorista').value = formatarBrasileiro(comissao_motorista);
        
        // Recalcular Valor CTe (igual ao frete)
        const valor_cte = valor_total_frete;
        document.querySelector('#valor_cte').value = formatarBrasileiro(valor_cte);
        
        // Recalcular Comissão CTe e Lucro
        const comissao_cte = valor_total_frete * 0.20; // 20% do valor do frete
        document.querySelector('#comissao_cte').value = formatarBrasileiro(comissao_cte);
        
        const lucro = valor_total_frete - comissao_motorista - comissao_cte;
        document.querySelector('#lucro').value = formatarBrasileiro(lucro);
        
    } catch (err) {
        console.error('Erro ao calcular frete:', err);
    }
}

// Inicializar quando o DOM estiver pronto
document.addEventListener('DOMContentLoaded', function() {
    // Campos que disparam o cálculo
    const camposCalculo = ['quantidade_id', 'preco_produto_unitario', 'preco_por_litro'];
    
    camposCalculo.forEach(campo => {
        const elemento = document.querySelector('#' + campo);
        if (elemento) {
            // Executar cálculo quando mudar
            elemento.addEventListener('change', calcularFrete);
            // Executar também enquanto digita (para feedback em tempo real)
            elemento.addEventListener('input', calcularFrete);
        }
    });
    
    // Executar cálculo ao carregar a página (importante para o formulário de edição)
    calcularFrete();
});
