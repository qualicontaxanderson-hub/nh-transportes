// ========================================
// FUNÇÕES DE FORMATAÇÃO DE MOEDA
// ========================================

/**
 * Formata número para exibição com R$ e separadores
 * Exemplo: 10830.50 → "R$ 10.830,50"
 * decimals: número de casas decimais a formatar (2 ou 3)
 */
function formatarMoedaDisplay(valor, decimals = 2) {
    if (valor === null || valor === undefined || valor === '') {
        return decimals === 3 ? 'R$ 0,000' : 'R$ 0,00';
    }

    const numero = typeof valor === 'string' ? parseFloat(valor.replace(',', '.')) : valor;

    if (isNaN(numero)) {
        return decimals === 3 ? 'R$ 0,000' : 'R$ 0,00';
    }

    return 'R$ ' + numero.toLocaleString('pt-BR', {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals
    });
}

/**
 * Remove formatação de moeda para obter valor numérico
 * Funciona para 2 ou 3 casas (ex.: "R$ 10.830,500" -> 10830.5)
 */
function limparMoeda(valor) {
    if (!valor) return 0;
    return parseFloat(valor.toString().replace(/[R$\s.]/g, '').replace(',', '.')) || 0;
}

/**
 * Formata input de moeda enquanto usuário digita
 * input: elemento input
 * decimals: 2 (centavos) ou 3 (milésimos)
 */
function aplicarMascaraMoeda(input, decimals = 2) {
    // remove tudo que não é dígito
    let valor = input.value.replace(/\D/g, '');

    if (valor === '') {
        input.value = decimals === 3 ? 'R$ 0,000' : 'R$ 0,00';
        return;
    }

    valor = parseInt(valor, 10);
    const fator = Math.pow(10, decimals);
    const reais = Math.floor(valor / fator);
    const casas = valor % fator;
    input.value = 'R$ ' + reais.toLocaleString('pt-BR') + ',' + casas.toString().padStart(decimals, '0');
}

// ===========================
// FUNÇÕES AUXILIARES
// ===========================
function formatarMoeda(valor) {
    return formatarMoedaDisplay(valor, 2);
}
function desformatarMoeda(valorStr) {
    return limparMoeda(valorStr);
}

// ===========================
// FUNÇÕES DE LEITURA DE DADOS
// ===========================
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
 */
function obterValorPorLitroRota() {
    const selectOrigem = document.getElementById('origem_id');
    if (!selectOrigem || !selectOrigem.value) return 0;

    const origemId = selectOrigem.value;
    const dadosCliente = obterDadosCliente();

    // Destino preferencial: o hidden destino (enviável) ou o select (se existir), senão data-destino-id do cliente
    const destinoHidden = document.getElementById('destino_id_hidden');
    const destinoSelect = document.getElementById('destino_id');
    const destinoId = (destinoHidden && destinoHidden.value) ? destinoHidden.value
                      : (destinoSelect && destinoSelect.value) ? destinoSelect.value
                      : dadosCliente.destinoId;

    if (!destinoId) return 0;

    const chaveRota = `${origemId}|${destinoId}`;
    if (typeof ROTAS === 'undefined') {
        console.warn('ROTAS não definido no template — obterValorPorLitroRota retornará 0');
        return 0;
    }
    return Number(ROTAS[chaveRota] || 0);
}

// ===========================
// FUNÇÕES DE CÁLCULO
// ===========================
function calcularQuantidade() {
    const selectQuantidade = document.getElementById('quantidade_id');
    const inputQuantidadeManual = document.getElementById('quantidade_manual');

    let quantidade = 0;

    if (selectQuantidade && selectQuantidade.value) {
        const optionSelecionada = selectQuantidade.options[selectQuantidade.selectedIndex];
        const raw = optionSelecionada.getAttribute('data-quantidade') || '0';
        // normaliza ponto de milhar e vírgula decimal
        quantidade = parseFloat(String(raw).toString().replace(/\./g, '').replace(',', '.')) || 0;
    }

    if (inputQuantidadeManual && inputQuantidadeManual.value) {
        const raw = inputQuantidadeManual.value.toString().trim();
        const normalized = raw.replace(/\./g, '').replace(',', '.').replace(/[^\d.]/g, '');
        quantidade = parseFloat(normalized) || quantidade;
    }

    // trabalhamos diretamente em litros — sem conversão KG -> L
    return quantidade;
}

function calcularTotalNFCompra() {
    const inputPrecoUnitario = document.getElementById('preco_produto_unitario');
    if (!inputPrecoUnitario) return 0;

    const precoUnitario = limparMoeda(inputPrecoUnitario.value);
    const quantidade = calcularQuantidade();

    return precoUnitario * quantidade;
}

function calcularValorTotalFrete() {
    const dadosCliente = obterDadosCliente();
    if (!dadosCliente.pagaComissao) return 0;

    const inputPrecoPorLitro = document.getElementById('preco_por_litro');
    if (!inputPrecoPorLitro) return 0;

    const precoPorLitro = desformatarMoeda(inputPrecoPorLitro.value);
    const quantidade = calcularQuantidade();

    return precoPorLitro * quantidade;
}

function calcularComissaoMotorista() {
    const dadosCliente = obterDadosCliente();
    if (!dadosCliente.pagaComissao) return 0;

    const quantidade = calcularQuantidade();
    return quantidade * 0.01;
}

function calcularValorCte() {
    const dadosCliente = obterDadosCliente();
    const quantidade = calcularQuantidade();

    if (dadosCliente.cteIntegral) {
        return calcularValorTotalFrete();
    } else {
        const valorPorLitroRota = obterValorPorLitroRota();
        return valorPorLitroRota * quantidade;
    }
}

function calcularComissaoCte() {
    const valorCte = calcularValorCte();
    return valorCte * 0.08;
}

function calcularLucro() {
    const dadosCliente = obterDadosCliente();
    if (!dadosCliente.pagaComissao) return 0;

    const valorTotalFrete = calcularValorTotalFrete();
    const comissaoMotorista = calcularComissaoMotorista();
    const comissaoCte = calcularComissaoCte();

    return valorTotalFrete - comissaoMotorista - comissaoCte;
}

// ===========================
// CONTROLE DE CAMPOS
// ===========================
function atualizarCampoPrecoPorLitro() {
    const inputPrecoPorLitro = document.getElementById('preco_por_litro');
    if (!inputPrecoPorLitro) return;

    const dadosCliente = obterDadosCliente();

    if (!dadosCliente.pagaComissao) {
        inputPrecoPorLitro.value = 'R$ 0,00';
        inputPrecoPorLitro.readOnly = true;
        inputPrecoPorLitro.style.backgroundColor = '#e9ecef';
        inputPrecoPorLitro.style.cursor = 'not-allowed';
    } else {
        inputPrecoPorLitro.readOnly = false;
        inputPrecoPorLitro.style.backgroundColor = '#ffffff';
        inputPrecoPorLitro.style.cursor = 'text';
    }
}

// ===========================
// FUNÇÃO PRINCIPAL
// ===========================
function calcularTudo() {
    atualizarCampoPrecoPorLitro();

    const totalNFCompra = calcularTotalNFCompra();
    const valorTotalFrete = calcularValorTotalFrete();
    const comissaoMotorista = calcularComissaoMotorista();
    const valorCte = calcularValorCte();
    const comissaoCte = calcularComissaoCte();
    const lucro = calcularLucro();

    // atualizar campo hidden preco raw (numérico) para backend
    const hiddenPrecoUnitario = document.getElementById('preco_produto_unitario_raw');
    const inputPrecoUnitario = document.getElementById('preco_produto_unitario');
    if (hiddenPrecoUnitario && inputPrecoUnitario) {
        hiddenPrecoUnitario.value = limparMoeda(inputPrecoUnitario.value); // ex.: 1234.567
    }

    const campoTotalNFCompra = document.getElementById('total_nf_compra');
    const campoValorTotalFrete = document.getElementById('valor_total_frete');
    const campoComissaoMotorista = document.getElementById('comissao_motorista');
    const campoValorCte = document.getElementById('valor_cte');
    const campoComissaoCte = document.getElementById('comissao_cte');
    const campoLucro = document.getElementById('lucro');

    if (campoTotalNFCompra) campoTotalNFCompra.value = formatarMoedaDisplay(totalNFCompra, 2);
    if (campoValorTotalFrete) campoValorTotalFrete.value = formatarMoedaDisplay(valorTotalFrete, 2);
    if (campoComissaoMotorista) campoComissaoMotorista.value = formatarMoedaDisplay(comissaoMotorista, 2);
    if (campoValorCte) campoValorCte.value = formatarMoedaDisplay(valorCte, 2);
    if (campoComissaoCte) campoComissaoCte.value = formatarMoedaDisplay(comissaoCte, 2);
    if (campoLucro) campoLucro.value = formatarMoedaDisplay(lucro, 2);
}

// ========================================
// INICIALIZAÇÃO E EVENTOS
// ========================================
/**
 * Aplica bloqueio/auto-preenchimento do campo destino:
 * - marca o select como disabled (bloqueio real)
 * - garante a existência/atualização de um input hidden com name="destino_id" para envio do form
 */
function aplicarBloqueioDestino(destinoId) {
    const destinoSelect = document.getElementById('destino_id');
    if (!destinoSelect) return;

    // sempre manter disabled (o usuário não pode alterar)
    destinoSelect.value = destinoId || '';
    destinoSelect.disabled = true;
    destinoSelect.style.backgroundColor = '#e9ecef';
    destinoSelect.style.cursor = 'not-allowed';

    // cria/atualiza input hidden para garantir envio do value
    let hidden = document.getElementById('destino_id_hidden');
    if (!hidden) {
        hidden = document.createElement('input');
        hidden.type = 'hidden';
        hidden.id = 'destino_id_hidden';
        hidden.name = 'destino_id';
        destinoSelect.parentElement.appendChild(hidden);
    }
    hidden.value = destinoId || '';

    // adicionar/atualizar badge informativo
    let badge = destinoSelect.parentElement.querySelector('.destino-auto-badge');
    if (!badge) {
        badge = document.createElement('small');
        badge.className = 'destino-auto-badge text-muted d-block mt-1';
        destinoSelect.parentElement.appendChild(badge);
    }
    badge.innerHTML = '<i class="bi bi-info-circle"></i> Destino preenchido a partir do cadastro do cliente';
    badge.classList.remove('text-warning');
    badge.classList.add('text-muted');

    console.log('✅ Destino bloqueado (auto-preenchido do cliente):', destinoId);
}

document.addEventListener('DOMContentLoaded', function() {
    console.log('✅ fretes_calculos.js carregado');

    // Aplicar máscara de moeda nos campos editáveis
    const camposMoeda = ['preco_produto_unitario', 'preco_por_litro'];

    camposMoeda.forEach(function(campoId) {
        const campo = document.getElementById(campoId);
        if (campo) {
            const decimals = campoId === 'preco_produto_unitario' ? 3 : 2;

            // Formatar valor inicial (se houver)
            if (campo.value && campo.value !== '0,00' && campo.value !== 'R$ 0,00' && campo.value !== (decimals === 3 ? 'R$ 0,000' : 'R$ 0,00')) {
                const valorLimpo = limparMoeda(campo.value);
                campo.value = formatarMoedaDisplay(valorLimpo, decimals);
            } else {
                campo.value = decimals === 3 ? 'R$ 0,000' : 'R$ 0,00';
            }

            // Aplicar máscara ao digitar
            campo.addEventListener('input', function() {
                aplicarMascaraMoeda(this, decimals);
            });

            // Recalcular ao sair do campo
            campo.addEventListener('blur', function() {
                calcularTudo();
            });
        }
    });

    // AUTO-BLOQUEIO DO DESTINO quando cliente selecionado
    const clienteSelect = document.getElementById('clientes_id');
    const destinoSelect = document.getElementById('destino_id');

    if (clienteSelect && destinoSelect) {
        clienteSelect.addEventListener('change', function() {
            const selectedOption = this.options[this.selectedIndex];
            const destinoId = selectedOption ? selectedOption.getAttribute('data-destino-id') : null;
            // sempre aplicar o bloqueio (mesmo que vazio)
            aplicarBloqueioDestino(destinoId);
            calcularTudo();
        });

        // Inicializar bloqueio no load (Editar) caso cliente já tenha destination
        const optionInicial = clienteSelect.options[clienteSelect.selectedIndex];
        const destinoInicial = optionInicial ? optionInicial.getAttribute('data-destino-id') : null;
        aplicarBloqueioDestino(destinoInicial);
    }

    // Configurar eventos nos campos que disparam recálculo
    const camposRecalculo = [
        'clientes_id',
        'motoristas_id',
        'quantidade_id',
        'quantidade_manual',
        'quantidade_tipo',
        'origem_id',
        'preco_produto_unitario',
        'preco_por_litro'
    ];

    camposRecalculo.forEach(function(campoId) {
        const campo = document.getElementById(campoId);
        if (campo) {
            const evento = campo.tagName === 'SELECT' ? 'change' : 'input';
            campo.addEventListener(evento, calcularTudo);
        }
    });

    // Garantir que o hidden preco_raw seja atualizado antes do submit
    const form = document.querySelector('form');
    if (form) {
        form.addEventListener('submit', function() {
            const hidden = document.getElementById('preco_produto_unitario_raw');
            const input = document.getElementById('preco_produto_unitario');
            if (hidden && input) {
                hidden.value = limparMoeda(input.value);
            }
        });
    }

    // Executar cálculo inicial
    calcularTudo();

    // DEBUG helpers
    window.debugRotas = function() {
        console.log('Rotas carregadas:', typeof ROTAS !== 'undefined' ? ROTAS : null);
    };

    window.debugCliente = function() {
        console.log('Dados do cliente:', obterDadosCliente());
    };

    window.calcularTudo = calcularTudo;
});
