// ============================================================================
// FRETES_CALCULOS.JS - VERSÃO CORRIGIDA
// Sistema de cálculos automáticos para fretes
// ============================================================================

// Objeto global que armazena as rotas (preenchido pelo template)
// Formato: ROTAS["origem_id|destino_id"] = valor_por_litro
let ROTAS = window.ROTAS || {};

// ============================================================================
// FUNÇÕES DE FORMATAÇÃO
// ============================================================================

function formatarMoeda(valor) {
    if (valor === null || valor === undefined || valor === '') return '0,00';
    valor = parseFloat(valor);
    if (isNaN(valor)) return '0,00';
    return valor.toFixed(2).replace('.', ',');
}

function desformatarMoeda(valor) {
    if (typeof valor === 'number') return valor;
    if (!valor) return 0;
    valor = valor.toString().replace(/\./g, '').replace(',', '.');
    return parseFloat(valor) || 0;
}

// ============================================================================
// OBTER DADOS DO CLIENTE SELECIONADO
// ============================================================================

function obterDadosCliente() {
    const clienteSelect = document.getElementById('clientes_id');
    if (!clienteSelect || !clienteSelect.value) {
        return {
            pagaComissao: true,
            cteIntegral: false,
            destinoId: null
        };
    }
    
    const selectedOption = clienteSelect.options[clienteSelect.selectedIndex];
    
    // Ler os atributos data-* do option selecionado
    const pagaComissao = selectedOption.getAttribute('data-paga-comissao') === '1';
    const cteIntegral = selectedOption.getAttribute('data-cte-integral') === '1';
    const destinoId = selectedOption.getAttribute('data-destino-id');
    
    console.log('📊 Dados do cliente:', {
        clienteId: clienteSelect.value,
        pagaComissao: pagaComissao,
        cteIntegral: cteIntegral,
        destinoId: destinoId
    });
    
    return {
        pagaComissao: pagaComissao,
        cteIntegral: cteIntegral,
        destinoId: destinoId ? parseInt(destinoId) : null
    };
}

// ============================================================================
// OBTER VALOR POR LITRO DA ROTA
// ============================================================================

function obterValorPorLitroRota() {
    const origemSelect = document.getElementById('origem_id');
    const clienteSelect = document.getElementById('clientes_id');
    
    if (!origemSelect || !origemSelect.value || !clienteSelect || !clienteSelect.value) {
        console.log('⚠️ Origem ou Cliente não selecionado');
        return 0;
    }
    
    const origemId = parseInt(origemSelect.value);
    const dadosCliente = obterDadosCliente();
    const destinoId = dadosCliente.destinoId;
    
    if (!destinoId) {
        console.log('⚠️ Cliente não tem destino_id definido');
        return 0;
    }
    
    // Montar a chave para buscar na tabela de rotas
    const chaveRota = `${origemId}|${destinoId}`;
    const valorPorLitro = ROTAS[chaveRota] || 0;
    
    console.log('🛣️ Busca de rota:', {
        origem: origemId,
        destino: destinoId,
        chave: chaveRota,
        valorEncontrado: valorPorLitro
    });
    
    return parseFloat(valorPorLitro) || 0;
}

// ============================================================================
// CALCULAR QUANTIDADE TOTAL
// ============================================================================

function calcularQuantidade() {
    const quantidadeId = document.getElementById('quantidade_id');
    const quantidadeManual = document.getElementById('quantidade_manual');
    const quantidadeTipo = document.getElementById('quantidade_tipo');
    
    let quantidade = 0;
    
    // Verificar se tem quantidade cadastrada selecionada
    if (quantidadeId && quantidadeId.value) {
        const selectedOption = quantidadeId.options[quantidadeId.selectedIndex];
        const qtdCadastrada = parseFloat(selectedOption.getAttribute('data-quantidade') || 0);
        quantidade = qtdCadastrada;
    }
    
    // Se tem quantidade manual, usar ela
    if (quantidadeManual && quantidadeManual.value) {
        const qtdManual = desformatarMoeda(quantidadeManual.value);
        if (qtdManual > 0) {
            quantidade = qtdManual;
        }
    }
    
    // Converter para litros se for em KG
    if (quantidadeTipo && quantidadeTipo.value === 'KG' && quantidade > 0) {
        quantidade = quantidade * 1.2; // 1 KG = 1.2 L
    }
    
    console.log('📦 Quantidade calculada:', quantidade, 'litros');
    return quantidade;
}

// ============================================================================
// CALCULAR VALOR TOTAL DO FRETE
// ============================================================================

function calcularValorTotalFrete() {
    const dadosCliente = obterDadosCliente();
    
    // Se cliente não paga comissão, valor total frete = 0
    if (!dadosCliente.pagaComissao) {
        console.log('💰 Cliente não paga comissão → Valor Total Frete = 0,00');
        return 0;
    }
    
    const precoPorLitroInput = document.getElementById('preco_por_litro');
    if (!precoPorLitroInput) return 0;
    
    const precoPorLitro = desformatarMoeda(precoPorLitroInput.value);
    const quantidade = calcularQuantidade();
    
    const valorTotal = precoPorLitro * quantidade;
    
    console.log('💰 Valor Total Frete:', {
        precoPorLitro: precoPorLitro,
        quantidade: quantidade,
        total: valorTotal
    });
    
    return valorTotal;
}

// ============================================================================
// CALCULAR COMISSÃO DO MOTORISTA
// ============================================================================

function calcularComissaoMotorista() {
    const dadosCliente = obterDadosCliente();
    
    // Se cliente não paga comissão, comissão motorista = 0
    if (!dadosCliente.pagaComissao) {
        console.log('🚚 Cliente não paga → Comissão Motorista = 0,00');
        return 0;
    }
    
    const motoristaSelect = document.getElementById('motoristas_id');
    if (!motoristaSelect || !motoristaSelect.value) return 0;
    
    const selectedOption = motoristaSelect.options[motoristaSelect.selectedIndex];
    const percentual = parseFloat(selectedOption.getAttribute('data-percentual') || 0) / 100;
    
    const valorTotalFrete = calcularValorTotalFrete();
    const comissao = valorTotalFrete * percentual;
    
    console.log('🚚 Comissão Motorista:', {
        percentual: percentual * 100 + '%',
        valorTotalFrete: valorTotalFrete,
        comissao: comissao
    });
    
    return comissao;
}

// ============================================================================
// CALCULAR VALOR CTE
// ============================================================================

function calcularValorCte() {
    const dadosCliente = obterDadosCliente();
    let valorCte = 0;
    
    // Se CTE INTEGRAL está ativo, usar Valor Total Frete
    if (dadosCliente.cteIntegral) {
        valorCte = calcularValorTotalFrete();
        console.log('📋 CTE Integral = SIM → Valor CTE = Valor Total Frete:', valorCte);
    } else {
        // Caso contrário, calcular pela rota
        const valorPorLitroRota = obterValorPorLitroRota();
        const quantidade = calcularQuantidade();
        valorCte = valorPorLitroRota * quantidade;
        console.log('📋 CTE Integral = NÃO → Calcular pela rota:', {
            valorPorLitro: valorPorLitroRota,
            quantidade: quantidade,
            valorCte: valorCte
        });
    }
    
    return valorCte;
}

// ============================================================================
// CALCULAR COMISSÃO CTE (8%)
// ============================================================================

function calcularComissaoCte() {
    const valorCte = calcularValorCte();
    const comissaoCte = valorCte * 0.08; // Sempre 8% do Valor CTE
    
    console.log('📋 Comissão CTE (8%):', comissaoCte);
    return comissaoCte;
}

// ============================================================================
// CALCULAR LUCRO
// ============================================================================

function calcularLucro() {
    const dadosCliente = obterDadosCliente();
    
    // REGRA CRÍTICA: Se cliente não paga comissão, lucro = 0,00
    if (!dadosCliente.pagaComissao) {
        console.log('💵 Cliente não paga → Lucro = 0,00');
        return 0;
    }
    
    const valorTotalFrete = calcularValorTotalFrete();
    const comissaoMotorista = calcularComissaoMotorista();
    const comissaoCte = calcularComissaoCte();
    
    const lucro = valorTotalFrete - comissaoMotorista - comissaoCte;
    
    console.log('💵 Lucro:', {
        valorTotalFrete: valorTotalFrete,
        comissaoMotorista: comissaoMotorista,
        comissaoCte: comissaoCte,
        lucro: lucro
    });
    
    return lucro;
}

// ============================================================================
// ATUALIZAR CAMPO DE PREÇO POR LITRO (BLOQUEAR SE CLIENTE NÃO PAGA)
// ============================================================================

function atualizarCampoPrecoPorLitro() {
    const precoPorLitroInput = document.getElementById('preco_por_litro');
    if (!precoPorLitroInput) return;
    
    const dadosCliente = obterDadosCliente();
    
    if (!dadosCliente.pagaComissao) {
        // Cliente NÃO paga → bloquear campo e zerar valor
        precoPorLitroInput.value = '0,00';
        precoPorLitroInput.readOnly = true;
        precoPorLitroInput.style.backgroundColor = '#e9ecef';
        precoPorLitroInput.style.cursor = 'not-allowed';
        console.log('🔒 Campo Preço por Litro BLOQUEADO (cliente não paga)');
    } else {
        // Cliente PAGA → desbloquear campo
        precoPorLitroInput.readOnly = false;
        precoPorLitroInput.style.backgroundColor = '#ffffff';
        precoPorLitroInput.style.cursor = 'text';
        console.log('🔓 Campo Preço por Litro DESBLOQUEADO (cliente paga)');
    }
}

// ============================================================================
// FUNÇÃO PRINCIPAL: CALCULAR TUDO
// ============================================================================

function calcularTudo() {
    console.log('🔄 ========== INICIANDO CÁLCULOS ==========');
    
    try {
        // 1. Atualizar estado do campo preço por litro
        atualizarCampoPrecoPorLitro();
        
        // 2. Calcular Valor Total Frete
        const valorTotalFrete = calcularValorTotalFrete();
        const valorTotalFreteInput = document.getElementById('valor_total_frete');
        if (valorTotalFreteInput) {
            valorTotalFreteInput.value = formatarMoeda(valorTotalFrete);
        }
        
        // 3. Calcular Comissão Motorista
        const comissaoMotorista = calcularComissaoMotorista();
        const comissaoMotoristaInput = document.getElementById('comissao_motorista');
        if (comissaoMotoristaInput) {
            comissaoMotoristaInput.value = formatarMoeda(comissaoMotorista);
        }
        
        // 4. Calcular Valor CTE
        const valorCte = calcularValorCte();
        const valorCteInput = document.getElementById('valor_cte');
        if (valorCteInput) {
            valorCteInput.value = formatarMoeda(valorCte);
        }
        
        // 5. Calcular Comissão CTE
        const comissaoCte = calcularComissaoCte();
        const comissaoCteInput = document.getElementById('comissao_cte');
        if (comissaoCteInput) {
            comissaoCteInput.value = formatarMoeda(comissaoCte);
        }
        
        // 6. Calcular Lucro
        const lucro = calcularLucro();
        const lucroInput = document.getElementById('lucro');
        if (lucroInput) {
            lucroInput.value = formatarMoeda(lucro);
        }
        
        console.log('✅ ========== CÁLCULOS FINALIZADOS ==========');
        console.log('📊 RESUMO:', {
            valorTotalFrete: formatarMoeda(valorTotalFrete),
            comissaoMotorista: formatarMoeda(comissaoMotorista),
            valorCte: formatarMoeda(valorCte),
            comissaoCte: formatarMoeda(comissaoCte),
            lucro: formatarMoeda(lucro)
        });
        
    } catch (error) {
        console.error('❌ Erro durante os cálculos:', error);
    }
}

// ============================================================================
// INICIALIZAÇÃO: ADICIONAR EVENT LISTENERS
// ============================================================================

document.addEventListener('DOMContentLoaded', function() {
    console.log('🚀 Inicializando sistema de cálculos de fretes...');
    
    // Lista de campos que devem triggerar recálculo
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
    
    // Adicionar event listeners
    camposParaMonitorar.forEach(campoId => {
        const campo = document.getElementById(campoId);
        if (campo) {
            // Usar 'change' para selects e 'input' para text inputs
            const evento = campo.tagName === 'SELECT' ? 'change' : 'input';
            campo.addEventListener(evento, function() {
                console.log(`🔄 Campo alterado: ${campoId}`);
                calcularTudo();
            });
            console.log(`✅ Listener adicionado: ${campoId} (${evento})`);
        } else {
            console.log(`⚠️ Campo não encontrado: ${campoId}`);
        }
    });
    
    // Executar cálculo inicial
    console.log('🔄 Executando cálculo inicial...');
    calcularTudo();
    
    console.log('✅ Sistema de cálculos inicializado com sucesso!');
});

// ============================================================================
// FUNÇÕES AUXILIARES PARA DEPURAÇÃO
// ============================================================================

// Função para debugar rotas carregadas
function debugRotas() {
    console.log('🛣️ ROTAS CARREGADAS:', ROTAS);
    console.log('📊 Total de rotas:', Object.keys(ROTAS).length);
}

// Função para debugar dados do cliente atual
function debugCliente() {
    const dados = obterDadosCliente();
    console.log('👤 DADOS DO CLIENTE SELECIONADO:', dados);
}

// Tornar funções de debug disponíveis globalmente
window.debugRotas = debugRotas;
window.debugCliente = debugCliente;
window.calcularTudo = calcularTudo;

console.log('✅ fretes_calculos.js carregado com sucesso!');
console.log('💡 Dica: Use debugRotas() ou debugCliente() no console para depurar');
