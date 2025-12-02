// ========================================
// FUNÇÕES DE FORMATAÇÃO DE MOEDA
// ========================================

/**
 * Formata número para exibição com R$ e separadores
 * Exemplo: 10830.50 → "R$ 10.830,50"
 */
function formatarMoedaDisplay(valor) {
    if (valor === null || valor === undefined || valor === '') {
        return 'R$ 0,00';
    }
    
    const numero = typeof valor === 'string' ? parseFloat(valor.replace(',', '.')) : valor;
    
    if (isNaN(numero)) {
        return 'R$ 0,00';
    }
    
    return 'R$ ' + numero.toLocaleString('pt-BR', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    });
}

/**
 * Remove formatação de moeda para obter valor numérico
 * Exemplo: "R$ 10.830,50" → 10830.50
 */
function limparMoeda(valor) {
    if (!valor) return 0;
    return parseFloat(valor.toString().replace(/[R$\s.]/g, '').replace(',', '.')) || 0;
}

/**
 * Formata input de moeda enquanto usuário digita
 */
function aplicarMascaraMoeda(input) {
    let valor = input.value.replace(/\D/g, ''); // Remove tudo que não é dígito
    
    if (valor === '') {
        input.value = 'R$ 0,00';
        return;
    }
    
    // Converte para centavos
    valor = parseInt(valor);
    
    // Formata
    const reais = Math.floor(valor / 100);
    const centavos = valor % 100;
    
    input.value = 'R$ ' + reais.toLocaleString('pt-BR') + ',' + centavos.toString().padStart(2, '0');
}

// ===========================
// FUNÇÕES AUXILIARES
// ===========================

/**
 * Formata número para moeda brasileira
 */
function formatarMoeda(valor) {
    return formatarMoedaDisplay(valor);
}

/**
 * Desformata string de moeda para número
 */
function desformatarMoeda(valorStr) {
    return limparMoeda(valorStr);
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

    // Preferir o valor atual do select destino (quando houver).
    // Se não existir/estiver vazio, usar o destino associado ao cliente (dadosCliente.destinoId).
    const destinoSelect = document.getElementById('destino_id');
    const destinoId = (destinoSelect && destinoSelect.value) ? destinoSelect.value : dadosCliente.destinoId;

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
        // aceitar formatos como "R$ 1.234,56" ou "1234.56" ou "9.975"
        const raw = inputQuantidadeManual.value.toString().trim();
        // remover pontos de milhar e trocar vírgula por ponto
        const normalized = raw.replace(/\./g, '').replace(',', '.').replace(/[^\d.]/g, '');
        quantidade = parseFloat(normalized) || quantidade;
    }

    // Converter KG para litros (1 KG = 1.2 L)
    if (selectTipo && selectTipo.value === 'KG') {
        quantidade = quantidade * 1.2;
    }

    return quantidade;
}

/**
 * Calcula o total da NF de compra
 * Regra: Quantidade × Preço Produto Unitário
 */
function calcularTotalNFCompra() {
    const inputPrecoUnitario = document.getElementById('preco_produto_unitario');
    if (!inputPrecoUnitario) return 0;

    const precoUnitario = desformatarMoeda(inputPrecoUnitario.value);
    const quantidade = calcularQuantidade();

    return precoUnitario * quantidade;
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
 * Regra: R$ 0,01 por litro (se cliente paga comissão)
 */
function calcularComissaoMotorista() {
    const dadosCliente = obterDadosCliente();
    
    // Se cliente não paga comissão, comissão do motorista é zero
    if (!dadosCliente.pagaComissao) {
        return 0;
    }

    const quantidade = calcularQuantidade();
    return quantidade * 0.01; // R$ 0,01 por litro
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
        inputPrecoPorLitro.value = 'R$ 0,00';
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
    const totalNFCompra = calcularTotalNFCompra();
    const valorTotalFrete = calcularValorTotalFrete();
    const comissaoMotorista = calcularComissaoMotorista();
    const valorCte = calcularValorCte();
    const comissaoCte = calcularComissaoCte();
    const lucro = calcularLucro();

    // Atualiza os campos no formulário
    const campoTotalNFCompra = document.getElementById('total_nf_compra');
    const campoValorTotalFrete = document.getElementById('valor_total_frete');
    const campoComissaoMotorista = document.getElementById('comissao_motorista');
    const campoValorCte = document.getElementById('valor_cte');
    const campoComissaoCte = document.getElementById('comissao_cte');
    const campoLucro = document.getElementById('lucro');

    if (campoTotalNFCompra) campoTotalNFCompra.value = formatarMoeda(totalNFCompra);
    if (campoValorTotalFrete) campoValorTotalFrete.value = formatarMoeda(valorTotalFrete);
    if (campoComissaoMotorista) campoComissaoMotorista.value = formatarMoeda(comissaoMotorista);
    if (campoValorCte) campoValorCte.value = formatarMoeda(valorCte);
    if (campoComissaoCte) campoComissaoCte.value = formatarMoeda(comissaoCte);
    if (campoLucro) campoLucro.value = formatarMoeda(lucro);
}

// ========================================
// INICIALIZAÇÃO E EVENTOS
// ========================================

/**
 * Aplica bloqueio/auto-preenchimento do campo destino (reaproveita UX já existente)
 */
function aplicarBloqueioDestino(destinoId) {
    const destinoSelect = document.getElementById('destino_id');
    if (!destinoSelect || !destinoId) return;

    destinoSelect.value = destinoId;
    destinoSelect.setAttribute('readonly', 'readonly');
    destinoSelect.style.backgroundColor = '#e9ecef';
    destinoSelect.style.cursor = 'not-allowed';

    // Adicionar ou atualizar badge informativo
    let badge = destinoSelect.parentElement.querySelector('.destino-auto-badge');
    if (!badge) {
        badge = document.createElement('small');
        badge.className = 'destino-auto-badge text-muted d-block mt-1';
        destinoSelect.parentElement.appendChild(badge);
    }
    badge.innerHTML = '<i class="bi bi-info-circle"></i> Destino preenchido automaticamente do cadastro do cliente';
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
            // Formatar valor inicial
            if (campo.value && campo.value !== '0,00' && campo.value !== 'R$ 0,00') {
                const valorLimpo = limparMoeda(campo.value);
                campo.value = formatarMoedaDisplay(valorLimpo);
            } else {
                campo.value = 'R$ 0,00';
            }
            
            // Aplicar máscara ao digitar
            campo.addEventListener('input', function() {
                aplicarMascaraMoeda(this);
            });
            
            // Recalcular ao sair do campo
            campo.addEventListener('blur', function() {
                calcularTudo();
            });
        }
    });
    
    // AUTO-BLOQUEIO DO DESTINO quando selecionado via Cliente
    const clienteSelect = document.getElementById('clientes_id');
    const destinoSelect = document.getElementById('destino_id');
    
    if (clienteSelect && destinoSelect) {
        clienteSelect.addEventListener('change', function() {
            const selectedOption = this.options[this.selectedIndex];
            const destinoId = selectedOption.getAttribute('data-destino-id');
            
            if (destinoId) {
                destinoSelect.value = destinoId;
                destinoSelect.setAttribute('readonly', 'readonly');
                destinoSelect.style.backgroundColor = '#e9ecef';
                destinoSelect.style.cursor = 'not-allowed';
                
                // Adicionar badge informativo
                let badge = destinoSelect.parentElement.querySelector('.destino-auto-badge');
                if (!badge) {
                    badge = document.createElement('small');
                    badge.className = 'destino-auto-badge text-muted d-block mt-1';
                    badge.innerHTML = '<i class="bi bi-info-circle"></i> Destino preenchido automaticamente do cadastro do cliente';
                    destinoSelect.parentElement.appendChild(badge);
                }
                
                console.log('✅ Destino bloqueado (auto-preenchido do cliente):', destinoId);
                
                // Recalcular valores
                calcularTudo();
            } else {
                // Cliente sem município: libera campo
                destinoSelect.removeAttribute('readonly');
                destinoSelect.style.backgroundColor = '';
                destinoSelect.style.cursor = '';
                
                // Remover badge
                const badge = destinoSelect.parentElement.querySelector('.destino-auto-badge');
                if (badge) {
                    badge.remove();
                }
                
                console.log('⚠️ Destino liberado (cliente sem município)');
            }
        });
        
        // Permitir desbloquear clicando 2x no campo destino
        destinoSelect.addEventListener('dblclick', function() {
            if (this.hasAttribute('readonly')) {
                this.removeAttribute('readonly');
                this.style.backgroundColor = '';
                this.style.cursor = '';
                
                const badge = this.parentElement.querySelector('.destino-auto-badge');
                if (badge) {
                    badge.innerHTML = '<i class="bi bi-unlock"></i> Destino desbloqueado para edição manual';
                    badge.classList.remove('text-muted');
                    badge.classList.add('text-warning');
                }
                
                console.log('⚠️ Destino desbloqueado manualmente');
            }
        });

        // --- NOVO: aplicar bloqueio inicial caso o cliente já venha selecionado (edição) ---
        const optionInicial = clienteSelect.options[clienteSelect.selectedIndex];
        if (optionInicial) {
            const destinoInicial = optionInicial.getAttribute('data-destino-id');
            if (destinoInicial) {
                aplicarBloqueioDestino(destinoInicial);
            }
        }
    }
    
    // Configurar eventos nos campos que disparam recálculo
    const camposRecalculo = [
        'clientes_id',
        'motoristas_id',
        'quantidade_id',
        'quantidade_manual',
        'quantidade_tipo',
        'origem_id',
        'destino_id',
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
    
    // Executar cálculo inicial
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
