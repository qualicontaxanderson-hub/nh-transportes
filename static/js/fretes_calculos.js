// ==========================================
// FUNÇÕES AUXILIARES
// ==========================================

function formatarMoeda(valor) {
    return parseFloat(valor).toFixed(2).replace('.', ',');
}

function desformatarMoeda(valor) {
    if (!valor) return 0;
    return parseFloat(valor.toString().replace(/\./g, '').replace(',', '.')) || 0;
}

function obterQuantidade() {
    const tipoQuantidade = document.getElementById('quantidade_tipo');
    
    if (tipoQuantidade && tipoQuantidade.value === 'personalizada') {
        const quantidadeManual = document.getElementById('quantidade_manual').value;
        if (!quantidadeManual) return 0;
        return parseFloat(quantidadeManual.replace(/\./g, '').replace(',', '.')) || 0;
    } else {
        const quantidadeSelect = document.getElementById('quantidade_id');
        const selectedOption = quantidadeSelect.options[quantidadeSelect.selectedIndex];
        const dataLitros = selectedOption ? selectedOption.getAttribute('data-litros') : null;
        
        if (!dataLitros) return 0;
        
        return parseFloat(dataLitros.replace(/\./g, '').replace(',', '.')) || 0;
    }
}

function obterDadosCliente() {
    const clienteSelect = document.getElementById('clientes_id');
    const selectedOption = clienteSelect.options[clienteSelect.selectedIndex];
    
    if (!selectedOption || !selectedOption.value) {
        return { pagaComissao: false, cteIntegral: false };
    }
    
    const pagaComissaoRaw = selectedOption.getAttribute('data-paga-comissao');
    const cteIntegralRaw = selectedOption.getAttribute('data-cte-integral');
    
    const pagaComissao = (pagaComissaoRaw === '1' || pagaComissaoRaw === 'True' || pagaComissaoRaw === 'true' || pagaComissaoRaw === true);
    const cteIntegral = (cteIntegralRaw === '1' || cteIntegralRaw === 'True' || cteIntegralRaw === 'true' || cteIntegralRaw === true);
    
    return { pagaComissao, cteIntegral };
}

function obterDadosMotorista() {
    const motoristaSelect = document.getElementById('motoristas_id');
    const selectedOption = motoristaSelect.options[motoristaSelect.selectedIndex];
    
    if (!selectedOption || !selectedOption.value) {
        return { pagaComissao: false };
    }
    
    const pagaComissaoRaw = selectedOption.getAttribute('data-paga-comissao');
    const pagaComissao = (pagaComissaoRaw === '1' || pagaComissaoRaw === 'True' || pagaComissaoRaw === 'true' || pagaComissaoRaw === true);
    
    return { pagaComissao };
}

function obterValorPorLitroRota() {
    const origemId = document.getElementById('origem_id').value;
    const destinoId = document.getElementById('destino_id').value;
    
    if (!origemId || !destinoId) return 0;
    
    const chave = `${origemId}_${destinoId}`;
    
    if (typeof ROTAS !== 'undefined' && ROTAS[chave]) {
        return parseFloat(ROTAS[chave]);
    }
    
    return 0;
}

// ==========================================
// CÁLCULOS PRINCIPAIS
// ==========================================

function calcularTotalNFCompra() {
    const quantidade = obterQuantidade();
    const precoUnitario = desformatarMoeda(document.getElementById('preco_produto_unitario').value);
    const total = quantidade * precoUnitario;
    document.getElementById('total_nf_compra').value = formatarMoeda(total);
}

function calcularValorTotalFrete() {
    const quantidade = obterQuantidade();
    const precoPorLitro = desformatarMoeda(document.getElementById('preco_por_litro').value);
    const valorTotal = quantidade * precoPorLitro;
    document.getElementById('valor_total_frete').value = formatarMoeda(valorTotal);
}

function calcularComissaoMotorista() {
    const dadosCliente = obterDadosCliente();
    const dadosMotorista = obterDadosMotorista();
    
    const clientePagaComissao = dadosCliente.pagaComissao;
    const motoristaPagaComissao = dadosMotorista.pagaComissao;
    
    if (!clientePagaComissao || !motoristaPagaComissao) {
        document.getElementById('comissao_motorista').value = formatarMoeda(0);
        return;
    }
    
    const quantidade = obterQuantidade();
    const comissao = quantidade * 0.01;
    
    document.getElementById('comissao_motorista').value = formatarMoeda(comissao);
}

function calcularValorCte() {
    const dadosCliente = obterDadosCliente();
    const cteIntegral = dadosCliente.cteIntegral;
    
    let valorCte = 0;
    
    if (cteIntegral) {
        const valorTotalFrete = desformatarMoeda(document.getElementById('valor_total_frete').value);
        valorCte = valorTotalFrete;
    } else {
        const quantidade = obterQuantidade();
        const valorPorLitroRota = obterValorPorLitroRota();
        valorCte = quantidade * valorPorLitroRota;
    }
    
    document.getElementById('valor_cte').value = formatarMoeda(valorCte);
}

function calcularComissaoCte() {
    const valorCte = desformatarMoeda(document.getElementById('valor_cte').value);
    const comissao = valorCte * 0.08;
    document.getElementById('comissao_cte').value = formatarMoeda(comissao);
}

function calcularLucro() {
    const dadosCliente = obterDadosCliente();
    const clientePagaComissao = dadosCliente.pagaComissao;
    
    // ✅ NOVO: Se cliente NÃO paga comissão, lucro = 0
    if (!clientePagaComissao) {
        document.getElementById('lucro').value = formatarMoeda(0);
        return;
    }
    
    const valorTotalFrete = desformatarMoeda(document.getElementById('valor_total_frete').value);
    const comissaoMotorista = desformatarMoeda(document.getElementById('comissao_motorista').value);
    const comissaoCte = desformatarMoeda(document.getElementById('comissao_cte').value);
    
    const lucro = valorTotalFrete - comissaoMotorista - comissaoCte;
    
    document.getElementById('lucro').value = formatarMoeda(lucro);
}

function calcularTudo() {
    // ✅ NOVO: Verificar se cliente paga comissão
    const dadosCliente = obterDadosCliente();
    const clientePagaComissao = dadosCliente.pagaComissao;
    
    const precoPorLitroInput = document.getElementById('preco_por_litro');
    
    // Se cliente NÃO paga comissão, bloquear preço por litro
    if (!clientePagaComissao) {
        precoPorLitroInput.value = formatarMoeda(0);
        precoPorLitroInput.readOnly = true;
        precoPorLitroInput.style.backgroundColor = '#e9ecef';
    } else {
        precoPorLitroInput.readOnly = false;
        precoPorLitroInput.style.backgroundColor = '#ffffff';
    }
    
    calcularTotalNFCompra();
    calcularValorTotalFrete();
    calcularComissaoMotorista();
    calcularValorCte();
    calcularComissaoCte();
    calcularLucro();
}

// ==========================================
// EVENT LISTENERS
// ==========================================

document.addEventListener('DOMContentLoaded', function() {
    const campos = [
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
    
    campos.forEach(function(campoId) {
        const campo = document.getElementById(campoId);
        if (campo) {
            campo.addEventListener('change', calcularTudo);
            campo.addEventListener('input', calcularTudo);
        }
    });
    
    // ✅ NOVO: Calcular ao carregar a página (para formulário de edição)
    calcularTudo();
});
