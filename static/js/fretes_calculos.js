// ========================================
// fretes_calculos.js - versão completa (para usar com os templates novo/editar acima)
// - parsing robusto de moeda
// - toggle quantidade personalizada
// - sincroniza preco_produto_unitario_raw
// - dispatch + call para Importar Pedido
// - bloqueio destino + hidden
// ========================================

/* ---------- Helpers de formatação / parsing ---------- */
function formatarMoedaDisplay(valor, decimals = 2) {
    if (valor === null || valor === undefined || valor === '') {
        return decimals === 3 ? 'R$ 0,000' : 'R$ 0,00';
    }
    const numero = typeof valor === 'string' ? parseFloat(valor.replace(',', '.')) : valor;
    if (isNaN(numero)) return decimals === 3 ? 'R$ 0,000' : 'R$ 0,00';
    return 'R$ ' + numero.toLocaleString('pt-BR', {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals
    });
}

function parseNumberFromString(s, decimalsHint) {
    if (s === null || s === undefined) return 0;
    s = String(s).trim();
    s = s.replace(/[R$\u00A0\s]/g, '');
    if (s === '') return 0;
    const hasDot = s.indexOf('.') !== -1;
    const hasComma = s.indexOf(',') !== -1;
    if (hasDot && hasComma) {
        return parseFloat(s.replace(/\./g, '').replace(',', '.')) || 0;
    }
    if (!hasDot && hasComma) {
        return parseFloat(s.replace(',', '.')) || 0;
    }
    if (hasDot && !hasComma) {
        const parts = s.split('.');
        const last = parts[parts.length - 1];
        if (decimalsHint && last.length === decimalsHint) return parseFloat(s) || 0;
        if (last.length <= 2) return parseFloat(s) || 0;
        return parseFloat(s.replace(/\./g, '')) || 0;
    }
    return parseFloat(s) || 0;
}

function limparMoeda(valor, decimalsHint) {
    return parseNumberFromString(valor, decimalsHint);
}
function desformatarMoeda(valorStr) {
    return limparMoeda(valorStr);
}

function aplicarMascaraMoeda(input, decimals = 2) {
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

/* ---------- Leitura e regras do formulário ---------- */
function obterDadosCliente() {
    const selectCliente = document.getElementById('clientes_id');
    if (!selectCliente || !selectCliente.value) {
        return { pagaComissao: true, cteIntegral: false, destinoId: null };
    }
    const option = selectCliente.options[selectCliente.selectedIndex];
    return {
        pagaComissao: option.getAttribute('data-paga-comissao') !== '0',
        cteIntegral: option.getAttribute('data-cte-integral') === '1',
        destinoId: option.getAttribute('data-destino-id')
    };
}

function obterValorPorLitroRota() {
    const selectOrigem = document.getElementById('origem_id');
    if (!selectOrigem || !selectOrigem.value) return 0;
    const origemId = selectOrigem.value;
    const dadosCliente = obterDadosCliente();
    const destinoHidden = document.getElementById('destino_id_hidden');
    const destinoSelect = document.getElementById('destino_id');
    const destinoId = (destinoHidden && destinoHidden.value) ? destinoHidden.value
                      : (destinoSelect && destinoSelect.value) ? destinoSelect.value
                      : dadosCliente.destinoId;
    if (!destinoId) return 0;
    const chaveRota = `${origemId}|${destinoId}`;
    if (typeof ROTAS === 'undefined') {
        console.warn('ROTAS não definido — obterValorPorLitroRota retorna 0');
        return 0;
    }
    return Number(ROTAS[chaveRota] || 0);
}

/* ---------- Cálculos ---------- */
function calcularQuantidade() {
    const selectQuantidade = document.getElementById('quantidade_id');
    const inputQuantidadeManual = document.getElementById('quantidade_manual');
    let quantidade = 0;
    if (selectQuantidade && selectQuantidade.value) {
        const option = selectQuantidade.options[selectQuantidade.selectedIndex];
        const raw = option.getAttribute('data-quantidade') || '0';
        quantidade = parseNumberFromString(raw, 0) || 0;
    }
    if (inputQuantidadeManual && inputQuantidadeManual.value) {
        quantidade = parseNumberFromString(inputQuantidadeManual.value, 0) || quantidade;
    }
    return quantidade;
}

function calcularTotalNFCompra() {
    const inputPrecoUnitario = document.getElementById('preco_produto_unitario');
    if (!inputPrecoUnitario) return 0;
    const precoUnitario = limparMoeda(inputPrecoUnitario.value, 3);
    const quantidade = calcularQuantidade();
    return precoUnitario * quantidade;
}

function calcularValorTotalFrete() {
    const dadosCliente = obterDadosCliente();
    if (!dadosCliente.pagaComissao) return 0;
    const inputPrecoPorLitro = document.getElementById('preco_por_litro');
    if (!inputPrecoPorLitro) return 0;
    const precoPorLitro = limparMoeda(inputPrecoPorLitro.value, 2);
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

/* ---------- UI Helpers ---------- */
function alternarQuantidadeExibicao() {
    const tipo = (document.getElementById('quantidade_tipo') || {}).value;
    const divManual = document.getElementById('div_quantidade_personalizada');
    const selectPadrao = document.getElementById('div_quantidade_padrao');
    if (!divManual || !selectPadrao) return;
    if (tipo === 'personalizada') {
        selectPadrao.style.display = 'none';
        divManual.style.display = 'block';
    } else {
        selectPadrao.style.display = 'block';
        divManual.style.display = 'none';
    }
}

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
        inputPrecoPorLitro.style.backgroundColor = '';
        inputPrecoPorLitro.style.cursor = '';
    }
}

function aplicarBloqueioDestino(destinoId) {
    const destinoSelect = document.getElementById('destino_id');
    if (!destinoSelect) return;
    destinoSelect.value = destinoId || '';
    destinoSelect.disabled = true;
    destinoSelect.style.backgroundColor = '#e9ecef';
    destinoSelect.style.cursor = 'not-allowed';
    let hidden = document.getElementById('destino_id_hidden');
    if (!hidden) {
        hidden = document.createElement('input');
        hidden.type = 'hidden';
        hidden.id = 'destino_id_hidden';
        hidden.name = 'destino_id';
        destinoSelect.parentElement.appendChild(hidden);
    }
    hidden.value = destinoId || '';
    let badge = destinoSelect.parentElement.querySelector('.destino-auto-badge');
    if (!badge) {
        badge = document.createElement('small');
        badge.className = 'destino-auto-badge text-muted d-block mt-1';
        destinoSelect.parentElement.appendChild(badge);
    }
    badge.innerHTML = '<i class="bi bi-info-circle"></i> Destino preenchido a partir do cadastro do cliente';
    badge.classList.remove('text-warning');
    badge.classList.add('text-muted');
}

/* ---------- Inicialização de eventos ---------- */
document.addEventListener('DOMContentLoaded', function() {
    console.debug('✅ fretes_calculos.js carregado');

    const camposMoeda = ['preco_produto_unitario', 'preco_por_litro'];
    camposMoeda.forEach(function(campoId) {
        const campo = document.getElementById(campoId);
        if (!campo) return;
        const decimals = campoId === 'preco_produto_unitario' ? 3 : 2;
        if (campo.value && campo.value !== (decimals === 3 ? 'R$ 0,000' : 'R$ 0,00')) {
            const v = limparMoeda(campo.value, decimals);
            campo.value = formatarMoedaDisplay(v, decimals);
        } else {
            campo.value = decimals === 3 ? 'R$ 0,000' : 'R$ 0,00';
        }
        campo.addEventListener('input', function() { aplicarMascaraMoeda(this, decimals); });
        campo.addEventListener('blur', calcularTudo);
    });

    const tipoSelect = document.getElementById('quantidade_tipo');
    if (tipoSelect) {
        tipoSelect.addEventListener('change', alternarQuantidadeExibicao);
        alternarQuantidadeExibicao();
    }

    const clienteSelect = document.getElementById('clientes_id');
    const destinoSelect = document.getElementById('destino_id');
    if (clienteSelect && destinoSelect) {
        clienteSelect.addEventListener('change', function() {
            const option = this.options[this.selectedIndex];
            const destinoId = option ? option.getAttribute('data-destino-id') : null;
            aplicarBloqueioDestino(destinoId);
            calcularTudo();
        });
        const optInit = clienteSelect.options[clienteSelect.selectedIndex];
        const destinoInit = optInit ? optInit.getAttribute('data-destino-id') : null;
        aplicarBloqueioDestino(destinoInit);
    }

    const camposRecalculo = ['clientes_id','motoristas_id','fornecedores_id','quantidade_id','quantidade_manual','quantidade_tipo','origem_id','preco_produto_unitario','preco_por_litro'];
    camposRecalculo.forEach(function(id) {
        const el = document.getElementById(id);
        if (!el) return;
        const ev = el.tagName === 'SELECT' ? 'change' : 'input';
        el.addEventListener(ev, calcularTudo);
    });

    // Importar Pedido: dispatch event + call global function if exists
    const btnImport = document.getElementById('btn_importar_pedido');
    if (btnImport) {
        btnImport.addEventListener('click', function() {
            try {
                const ev = new CustomEvent('abrirImportacaoPedido', { bubbles: true, cancelable: true });
                window.dispatchEvent(ev);
            } catch (e) {
                const ev2 = document.createEvent('Event');
                ev2.initEvent('abrirImportacaoPedido', true, true);
                window.dispatchEvent(ev2);
            }
            if (typeof window.abrirImportacaoPedido === 'function') {
                try { window.abrirImportacaoPedido(); } catch (err) { console.error('Erro abrirImportacaoPedido():', err); }
            }
        });
    }

    const form = document.querySelector('form');
    if (form) {
        form.addEventListener('submit', function() {
            const hidden = document.getElementById('preco_produto_unitario_raw');
            const input = document.getElementById('preco_produto_unitario');
            if (hidden && input) hidden.value = limparMoeda(input.value, 3);
        });
    }

    calcularTudo();

    window.debugRotas = function(){ console.log('ROTAS:', (typeof ROTAS==='undefined'?null:ROTAS)); };
    window.debugCliente = function(){ console.log('Cliente:', obterDadosCliente()); };
    window.calcularTudo = calcularTudo;
});
