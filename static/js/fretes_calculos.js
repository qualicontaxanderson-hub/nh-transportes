/**
 * Funções de cálculo para formulário de fretes
 * Corrige os problemas com parsing de quantidade e valores em formato brasileiro
 */

// Função para extrair quantidade corretamente
function obterQuantidade() {
    const selectQtd = document.querySelector('#quantidade_id');
    if (!selectQtd) return 0;
    
    let qtdText = selectQtd.value || selectQtd.selectedOptions[0].text;
    // Remove tudo que não é dígito e converte para número inteiro
    const quantidade = parseInt(qtdText.replace(/[^\d]/g, '')) || 0;
    return quantidade;
}

// Função para converter valor brasileiro (1.234,56) para número (1234.56)
function converterBrasileiro(valor) {
    if (!valor) return 0;
    return parseFloat(valor.replace('.', '').replace(',', '.'));
}

// Função para formatar número para formato brasileiro
function formatarBrasileiro(numero) {
    if (isNaN(numero)) return '0,00';
    return numero.toLocaleString('pt-BR', { 
        minimumFractionDigits: 2, 
        maximumFractionDigits: 2 
    });
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
        const comissao_motorista = quantidade * 0.01; // R$ 0,01 por litro
        
        // Atualizar campos readonly com valores formatados
        document.querySelector('#total_nf_compra').value = formatarBrasileiro(total_nf_compra);
        document.querySelector('#valor_total_frete').value = formatarBrasileiro(valor_total_frete);
        document.querySelector('#comissao_motorista').value = formatarBrasileiro(comissao_motorista);
        
        // Recalcular Valor CTe (provavelmente igual ao frete)
        const valor_cte = valor_total_frete;
        document.querySelector('#valor_cte').value = formatarBrasileiro(valor_cte);
        
        // Recalcular Lucro (Frete - Comissão Motorista - Comissão CTe)
        const comissao_cte = valor_total_frete * 0.2; // ou outro percentual conforme sua política
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
    
    // Executar cálculo ao carregar a página
    calcularFrete();
});
