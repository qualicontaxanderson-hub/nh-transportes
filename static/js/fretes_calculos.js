// ===========================
// FUNÇÕES AUXILIARES
// ===========================

/**
 * Formata número para moeda brasileira
 */
function formatarMoeda(valor) {
    return parseFloat(valor).toFixed(2).replace('.', ',');
}

/**
 * Desformata string de moeda para número
 */
function desformatarMoeda(valorStr) {
    if (!valorStr) return 0;
    return parseFloat(valorStr.toString().replace(',', '.')) || 0;
}

// ===========================
// FUNÇÕES DE LEITURA DE DADOS
// ===========================

/**
 * Obtém dados do cliente selecionado
 * @returns {Object} { pagaComissao, cteIntegral, destinoId }
 */
function obterDadosCliente() {
    const selectCliente = document.getElementById('clientes_id');
    if (!selectCliente || !selectCliente.value) {
        return {
            pagaComissao: true,
            cteIntegral: false,
            destinoId: null
        };
    }

    const optionSelecionada = selectCliente.options[selectCliente.selectedIndex];
    
    return {
        pagaComissao: optionSelecionada.getAttribute('data-paga-comissao') !== '0',
        cteIntegral: optionSelecionada.getAttribute('data-cte-integral') === '1',
        destinoId: optionSelecionada.getAttribute('data-destino-id')
    };
}

/**
 * Obtém o valor por litro da rota (origem → destino do cliente)
 * @returns {number} Valor por litro da rota
 */
function obterValorPorLitroRota() {
    const selectOrigem = document.getElementById('origem_id');
    if (!selectOrigem || !selectOrigem.value) return 0;

    const origemId = selectOrigem.value;
    const dadosCliente = obterDadosCliente();
    const destinoId = dadosCliente.destinoId;

    if (!destinoId) return 0;

    const chaveRota = `${origemId}|${destinoId}`;
    return ROTAS[chaveRota] || 0;
}

// ===========================
// FUNÇÕES DE CÁLCULO
// ===========================

/**
 * Calcula a quantidade em litros
 * Regra: se tipo = KG, multiplica por 1.2 para converter em litros
 */
function calcularQuantidade() {
    const selectQuantidade = document.getElementById('quantidade_id');
    const inputQuantidadeManual = document.getElementById('quantidade_manual');
    const selectTipo = document.getElementById('quantidade_tipo');

    let quantidade = 0;

    // Prioridade: quantidade cadastrada > manual
    if (selectQuantidade && selectQuantidade.value) {
        const optionSelecionada = selectQuantidade.options[selectQuantidade.selectedIndex];
        quantidade = parseFloat(optionSelecionada.getAttribute('data-quantidade')) || 0;
    }

    // Se existe quantidade manual preenchida, substitui
    if (inputQuantidadeManual && inputQuantidadeManual.value) {
        quantidade = desformatarMoeda(inputQuantidadeManual.value);
    }

    // Converter KG para litros (1 KG = 1.2 L)
    if (selectTipo && selectTipo.value === 'KG') {
        quantidade = quantidade * 1.2;
    }

    return quantidade;
}

/**
 * Calcula o valor total do frete
 * Regra: se cliente não paga comissão, retorna 0
 */
function calcularValorTotalFrete() {
    const dadosCliente = obterDadosCliente();
    
    // Se cliente não paga comissão, valor do frete é zero
    if (!dadosCliente.pagaComissao) {
        return 0;
    }

    const inputPrecoPorLitro = document.getElementById('preco_por_litro');
    if (!inputPrecoPorLitro) return 0;

    const precoPorLitro = desformatarMoeda(inputPrecoPorLitro.value);
    const quantidade = calcularQuantidade();

    return precoPorLitro * quantidade;
}

/**
 * Calcula a comissão do motorista
 * Regra: percentual do motorista × valor total do frete
 */
function calcularComissaoMotorista() {
    const dadosCliente = obterDadosCliente();
    
    // Se cliente não paga comissão, comissão do motorista é zero
    if (!dadosCliente.pagaComissao) {
        return 0;
    }

    const selectMotorista = document.getElementById('motoristas_id');
    if (!selectMotorista || !selectMotorista.value) return 0;

    const optionSelecionada = selectMotorista.options[selectMotorista.selectedIndex];
    const percentual = parseFloat(optionSelecionada.getAttribute('data-percentual')) || 0;
    const valorTotalFrete = calcularValorTotalFrete();

    return valorTotalFrete * (percentual / 100);
}
/**
 * Calcula o valor do CTE
 * Regra: 
 * - Se CTE integral: usa valor total do frete
 * - Se CTE não integral: usa valor por litro da rota × quantidade
 */
function calcularValorCte() {
    const dadosCliente = obterDadosCliente();
    const quantidade = calcularQuantidade();

    if (dadosCliente.cteIntegral) {
        // CTE Integral: usa o valor total do frete
        return calcularValorTotalFrete();
    } else {
        // CTE Normal: valor por litro da rota × quantidade
        const valorPorLitroRota = obterValorPorLitroRota();
        return valorPorLitroRota * quantidade;
    }
}

/**
 * Calcula a comissão do CTE (8% do valor do CTE)
 */
function calcularComissaoCte() {
    const valorCte = calcularValorCte();
    return valorCte * 0.08;
}

/**
 * Calcula o lucro
 * Regra: Valor Total Frete - Comissão Motorista - Comissão CTE
 */
function calcularLucro() {
    const dadosCliente = obterDadosCliente();
    
    // Se cliente não paga comissão, lucro é zero
    if (!dadosCliente.pagaComissao) {
        return 0;
    }

    const valorTotalFrete = calcularValorTotalFrete();
    const comissaoMotorista = calcularComissaoMotorista();
    const comissaoCte = calcularComissaoCte();

    return valorTotalFrete - comissaoMotorista - comissaoCte;
}

// ===========================
// CONTROLE DE CAMPOS
// ===========================

/**
 * Atualiza o estado do campo "preço por litro"
 * Bloqueia se cliente não paga comissão
 */
function atualizarCampoPrecoPorLitro() {
    const inputPrecoPorLitro = document.getElementById('preco_por_litro');
    if (!inputPrecoPorLitro) return;

    const dadosCliente = obterDadosCliente();

    if (!dadosCliente.pagaComissao) {
        // Cliente não paga comissão: bloqueia campo e zera
        inputPrecoPorLitro.value = '0,00';
        inputPrecoPorLitro.readOnly = true;
        inputPrecoPorLitro.style.backgroundColor = '#e9ecef';
        inputPrecoPorLitro.style.cursor = 'not-allowed';
    } else {
        // Cliente paga comissão: libera campo
        inputPrecoPorLitro.readOnly = false;
        inputPrecoPorLitro.style.backgroundColor = '#ffffff';
        inputPrecoPorLitro.style.cursor = 'text';
    }
}

// ===========================
// FUNÇÃO PRINCIPAL
// ===========================

/**
 * Executa todos os cálculos e atualiza os campos
 */
function calcularTudo() {
    // Atualiza estado do campo preço por litro
    atualizarCampoPrecoPorLitro();

    // Calcula e preenche todos os campos
    const valorTotalFrete = calcularValorTotalFrete();
    const comissaoMotorista = calcularComissaoMotorista();
    const valorCte = calcularValorCte();
    const comissaoCte = calcularComissaoCte();
    const lucro = calcularLucro();

    // Atualiza os campos no formulário
    const campoValorTotalFrete = document.getElementById('valor_total_frete');
    const campoComissaoMotorista = document.getElementById('comissao_motorista');
    const campoValorCte = document.getElementById('valor_cte');
    const campoComissaoCte = document.getElementById('comissao_cte');
    const campoLucro = document.getElementById('lucro');

    if (campoValorTotalFrete) campoValorTotalFrete.value = formatarMoeda(valorTotalFrete);
    if (campoComissaoMotorista) campoComissaoMotorista.value = formatarMoeda(comissaoMotorista);
    if (campoValorCte) campoValorCte.value = formatarMoeda(valorCte);
    if (campoComissaoCte) campoComissaoCte.value = formatarMoeda(comissaoCte);
    if (campoLucro) campoLucro.value = formatarMoeda(lucro);
}

// ===========================
// INICIALIZAÇÃO
// ===========================

document.addEventListener('DOMContentLoaded', function() {
    // Lista de campos que disparam o recálculo
    const camposParaMonitorar = [
        'clientes_id',
        'motoristas_id',
        'quantidade_id',
        'quantidade_manual',
        'quantidade_tipo',
        'origem_id',
        'preco_produto_unitario',
        'preco_por_litro'
    ];

    // Adiciona listeners em todos os campos
    camposParaMonitorar.forEach(function(campoId) {
        const campo = document.getElementById(campoId);
        if (campo) {
            const evento = campo.tagName === 'SELECT' ? 'change' : 'input';
            campo.addEventListener(evento, calcularTudo);
        }
    });

    // Executa cálculo inicial
    calcularTudo();

    // ===========================
    // FUNÇÕES DE DEBUG (console)
    // ===========================
    window.debugRotas = function() {
        console.log('Rotas carregadas:', ROTAS);
    };

    window.debugCliente = function() {
        console.log('Dados do cliente:', obterDadosCliente());
    };

    window.calcularTudo = calcularTudo;
});
