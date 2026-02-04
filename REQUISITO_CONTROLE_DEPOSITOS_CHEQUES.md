# Requisito: Controle de Depósitos de Cheques

## 📋 Status

- **Data:** 2026-02-04
- **Status:** ⏳ Pendente (não implementado)
- **Complexidade:** Alta
- **Estimativa:** 6-8 horas

## ✅ O Que Foi Feito (Commit 7ac25f0)

**Fix imediato:** TypeError no botão WhatsApp
- Corrigido erro `TypeError: Cannot read properties of undefined (reading 'target')`
- Botão "Copiar para WhatsApp" funciona sem erros
- Pronto para deploy

## 📝 Requisito Completo

### Contexto do Problema

**Fluxo Atual:**
1. Frentistas lançam cheques no sistema (ex: R$ 6.556,03)
2. Supervisor/tesoureiro vai ao banco depositar
3. Depósito pode ser dividido em múltiplas transações:
   - Exemplo: R$ 3.000,00 + R$ 3.556,03
4. Sistema atual não registra o que foi realmente depositado
5. **Problema:** Não há controle se houve falta ou diferença

**Caso Especial - Cheques a Prazo:**
- Cheque recebido em: 04/02/2026
- Data do cheque: 10/02/2026 (prazo)
- Depósito só pode ser feito em: 10/02/2026
- Supervisor precisa voltar no lançamento do dia 04/02 para registrar
- Sistema deve permitir edição retroativa

### Requisitos Funcionais

#### RF-01: Registrar Depósitos de Cheques À Vista
- Botão VERMELHO ao lado do campo "Depósitos em Cheques À Vista"
- Texto do botão: "📍 Registrar Depósito"
- Modal para entrada de dados:
  - Valor depositado (pode ser diferente do lançado)
  - Data do depósito
  - Responsável pelo depósito
  - Observação (opcional)

#### RF-02: Registrar Depósitos de Cheques A Prazo
- Botão VERMELHO ao lado do campo "Depósitos em Cheques A Prazo"
- Mesmas funcionalidades do RF-01
- Permite registro retroativo (voltar em lançamento antigo)

#### RF-03: Cálculo de Diferenças
- Sistema calcula automaticamente: Valor Lançado - Valor Depositado
- Mostra diferença em destaque:
  - Verde: sem diferença
  - Amarelo: diferença pequena (< 1%)
  - Vermelho: diferença significativa (>= 1%)

#### RF-04: Visualização no Lançamento
- Mostrar status do depósito abaixo do campo
- Exemplo:
  ```
  📍 Depositado: R$ 6.556,03 em 04/02/2026 por João Silva
  ✅ Sem diferença
  ```
  ou
  ```
  📍 Depositado: R$ 6.500,00 em 04/02/2026 por João Silva
  ⚠️ Diferença: -R$ 56,03 (Falta)
  ```

#### RF-05: Integração com WhatsApp
Incluir no texto do WhatsApp:
```
• Depósitos em Cheques À Vista (3): R$ 6.556,03
  📍 Depositado: R$ 6.556,03 em 04/02/2026
  ✅ Conferido

• Depósitos em Cheques A Prazo (2): R$ 5.000,00
  ⏳ Aguardando depósito (Data do cheque: 10/02/2026)
```

#### RF-06: Histórico e Auditoria
- Registrar quem fez o depósito
- Data e hora do registro no sistema
- Permitir consulta de histórico
- Log de alterações

## 🏗️ Arquitetura da Solução

### 1. Banco de Dados

```sql
CREATE TABLE lancamentos_caixa_depositos_cheques (
    id INT PRIMARY KEY AUTO_INCREMENT,
    lancamento_caixa_id INT NOT NULL,
    tipo ENUM('VISTA', 'PRAZO') NOT NULL,
    
    -- Valores
    valor_lancado DECIMAL(10,2) NOT NULL,
    valor_depositado DECIMAL(10,2),
    diferenca DECIMAL(10,2) GENERATED ALWAYS AS (valor_lancado - valor_depositado) STORED,
    
    -- Depósito
    data_deposito DATE,
    depositado_por VARCHAR(100),
    observacao TEXT,
    
    -- Auditoria
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    criado_por INT,
    atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    atualizado_por INT,
    
    FOREIGN KEY (lancamento_caixa_id) REFERENCES lancamentos_caixa(id) ON DELETE CASCADE,
    FOREIGN KEY (criado_por) REFERENCES usuarios(id),
    FOREIGN KEY (atualizado_por) REFERENCES usuarios(id),
    
    INDEX idx_lancamento (lancamento_caixa_id),
    INDEX idx_tipo (tipo),
    INDEX idx_data_deposito (data_deposito)
);
```

### 2. Backend (routes/lancamentos_caixa.py)

#### Nova Rota: Registrar Depósito
```python
@lancamentos_caixa_bp.route('/<int:id>/deposito_cheque', methods=['POST'])
@login_required
def registrar_deposito_cheque(id):
    """
    Registra ou atualiza depósito de cheque
    """
    try:
        # Validar lançamento existe
        lancamento = get_lancamento_by_id(id)
        if not lancamento:
            return jsonify({'error': 'Lançamento não encontrado'}), 404
        
        # Receber dados
        tipo = request.json.get('tipo')  # VISTA ou PRAZO
        valor_lancado = request.json.get('valor_lancado')
        valor_depositado = request.json.get('valor_depositado')
        data_deposito = request.json.get('data_deposito')
        depositado_por = request.json.get('depositado_por')
        observacao = request.json.get('observacao', '')
        
        # Validações
        if tipo not in ['VISTA', 'PRAZO']:
            return jsonify({'error': 'Tipo inválido'}), 400
        
        if not valor_depositado or float(valor_depositado) <= 0:
            return jsonify({'error': 'Valor depositado inválido'}), 400
        
        # Inserir ou atualizar
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        
        # Verificar se já existe
        cursor.execute("""
            SELECT id FROM lancamentos_caixa_depositos_cheques
            WHERE lancamento_caixa_id = %s AND tipo = %s
        """, (id, tipo))
        
        existing = cursor.fetchone()
        
        if existing:
            # Atualizar
            cursor.execute("""
                UPDATE lancamentos_caixa_depositos_cheques
                SET valor_depositado = %s, data_deposito = %s,
                    depositado_por = %s, observacao = %s,
                    atualizado_por = %s
                WHERE id = %s
            """, (valor_depositado, data_deposito, depositado_por,
                  observacao, current_user.id, existing['id']))
        else:
            # Inserir
            cursor.execute("""
                INSERT INTO lancamentos_caixa_depositos_cheques
                (lancamento_caixa_id, tipo, valor_lancado, valor_depositado,
                 data_deposito, depositado_por, observacao, criado_por)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (id, tipo, valor_lancado, valor_depositado, data_deposito,
                  depositado_por, observacao, current_user.id))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': 'Depósito registrado com sucesso'
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
```

#### Atualizar Visualização
```python
# Adicionar em visualizar()
cursor.execute("""
    SELECT * FROM lancamentos_caixa_depositos_cheques
    WHERE lancamento_caixa_id = %s
""", (id,))
depositos_cheques = cursor.fetchall()

return render_template(
    'lancamentos_caixa/visualizar.html',
    # ... outros dados ...
    depositos_cheques=depositos_cheques
)
```

### 3. Frontend (templates/lancamentos_caixa/novo.html)

#### HTML - Botões
```html
<!-- Depósitos em Cheques À Vista -->
<div class="form-group">
    <label for="cheques_vista_total">Depósitos em Cheques À Vista</label>
    <div class="input-group">
        <input type="text" 
               id="cheques_vista_total" 
               class="form-control money-input" 
               readonly
               value="R$ 0,00">
        <button type="button" 
                class="btn btn-danger btn-sm"
                onclick="abrirModalDepositoCheque('VISTA')"
                id="btn_deposito_vista">
            📍 Registrar Depósito
        </button>
    </div>
    <div id="status_deposito_vista" class="mt-2"></div>
</div>

<!-- Depósitos em Cheques A Prazo -->
<div class="form-group">
    <label for="cheques_prazo_total">Depósitos em Cheques A Prazo</label>
    <div class="input-group">
        <input type="text" 
               id="cheques_prazo_total" 
               class="form-control money-input" 
               readonly
               value="R$ 0,00">
        <button type="button" 
                class="btn btn-danger btn-sm"
                onclick="abrirModalDepositoCheque('PRAZO')"
                id="btn_deposito_prazo">
            📍 Registrar Depósito
        </button>
    </div>
    <div id="status_deposito_prazo" class="mt-2"></div>
</div>
```

#### Modal
```html
<div class="modal fade" id="modalDepositoCheque">
    <div class="modal-dialog">
        <div class="modal-content">
            <div class="modal-header">
                <h5 class="modal-title">Registrar Depósito de Cheque</h5>
                <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
            </div>
            <div class="modal-body">
                <input type="hidden" id="deposito_tipo">
                
                <div class="form-group">
                    <label>Valor Lançado</label>
                    <input type="text" id="deposito_valor_lancado" class="form-control" readonly>
                </div>
                
                <div class="form-group">
                    <label>Valor Depositado *</label>
                    <input type="text" id="deposito_valor_depositado" class="form-control money-input" required>
                </div>
                
                <div class="form-group">
                    <label>Diferença</label>
                    <input type="text" id="deposito_diferenca" class="form-control" readonly>
                </div>
                
                <div class="form-group">
                    <label>Data do Depósito *</label>
                    <input type="date" id="deposito_data" class="form-control" required>
                </div>
                
                <div class="form-group">
                    <label>Depositado Por *</label>
                    <input type="text" id="deposito_responsavel" class="form-control" required>
                </div>
                
                <div class="form-group">
                    <label>Observação</label>
                    <textarea id="deposito_observacao" class="form-control" rows="3"></textarea>
                </div>
            </div>
            <div class="modal-footer">
                <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancelar</button>
                <button type="button" class="btn btn-danger" onclick="salvarDepositoCheque()">
                    Salvar Depósito
                </button>
            </div>
        </div>
    </div>
</div>
```

#### JavaScript
```javascript
function abrirModalDepositoCheque(tipo) {
    const lancamentoId = getUrlParameter('id') || {{ lancamento.id if lancamento else 'null' }};
    
    if (!lancamentoId) {
        alert('Salve o lançamento antes de registrar depósitos');
        return;
    }
    
    // Pegar valor lançado
    let valorLancado = 0;
    if (tipo === 'VISTA') {
        valorLancado = parseMoneyToFloat($('#cheques_vista_total').val());
    } else {
        valorLancado = parseMoneyToFloat($('#cheques_prazo_total').val());
    }
    
    if (valorLancado <= 0) {
        alert('Não há valor lançado para este tipo de cheque');
        return;
    }
    
    // Preencher modal
    $('#deposito_tipo').val(tipo);
    $('#deposito_valor_lancado').val(formatMoney(valorLancado));
    $('#deposito_valor_depositado').val('');
    $('#deposito_diferenca').val('R$ 0,00');
    $('#deposito_data').val(new Date().toISOString().split('T')[0]);
    $('#deposito_responsavel').val('');
    $('#deposito_observacao').val('');
    
    // Mostrar modal
    new bootstrap.Modal(document.getElementById('modalDepositoCheque')).show();
}

// Calcular diferença em tempo real
$('#deposito_valor_depositado').on('input', function() {
    const valorLancado = parseMoneyToFloat($('#deposito_valor_lancado').val());
    const valorDepositado = parseMoneyToFloat($(this).val());
    const diferenca = valorLancado - valorDepositado;
    
    $('#deposito_diferenca').val(formatMoney(Math.abs(diferenca)));
    
    // Colorir de acordo com diferença
    if (Math.abs(diferenca) < 0.01) {
        $('#deposito_diferenca').css('color', 'green');
    } else if (Math.abs(diferenca) < valorLancado * 0.01) {
        $('#deposito_diferenca').css('color', 'orange');
    } else {
        $('#deposito_diferenca').css('color', 'red');
    }
});

function salvarDepositoCheque() {
    const lancamentoId = getUrlParameter('id') || {{ lancamento.id if lancamento else 'null' }};
    
    const dados = {
        tipo: $('#deposito_tipo').val(),
        valor_lancado: parseMoneyToFloat($('#deposito_valor_lancado').val()),
        valor_depositado: parseMoneyToFloat($('#deposito_valor_depositado').val()),
        data_deposito: $('#deposito_data').val(),
        depositado_por: $('#deposito_responsavel').val(),
        observacao: $('#deposito_observacao').val()
    };
    
    // Validações
    if (!dados.valor_depositado || dados.valor_depositado <= 0) {
        alert('Informe o valor depositado');
        return;
    }
    
    if (!dados.data_deposito) {
        alert('Informe a data do depósito');
        return;
    }
    
    if (!dados.depositado_por) {
        alert('Informe quem fez o depósito');
        return;
    }
    
    // Enviar via AJAX
    $.ajax({
        url: `/lancamentos_caixa/${lancamentoId}/deposito_cheque`,
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify(dados),
        success: function(response) {
            alert('Depósito registrado com sucesso!');
            bootstrap.Modal.getInstance(document.getElementById('modalDepositoCheque')).hide();
            
            // Atualizar status
            mostrarStatusDeposito(dados.tipo, dados);
        },
        error: function(xhr) {
            alert('Erro ao registrar depósito: ' + (xhr.responseJSON?.error || 'Erro desconhecido'));
        }
    });
}

function mostrarStatusDeposito(tipo, dados) {
    const diferenca = dados.valor_lancado - dados.valor_depositado;
    let html = '<div class="alert alert-info">';
    html += `📍 Depositado: ${formatMoney(dados.valor_depositado)} em ${formatDate(dados.data_deposito)}`;
    html += ` por ${dados.depositado_por}<br>`;
    
    if (Math.abs(diferenca) < 0.01) {
        html += '<span class="text-success">✅ Sem diferença</span>';
    } else if (diferenca > 0) {
        html += `<span class="text-danger">⚠️ Falta: ${formatMoney(Math.abs(diferenca))}</span>`;
    } else {
        html += `<span class="text-warning">⚠️ Sobra: ${formatMoney(Math.abs(diferenca))}</span>`;
    }
    
    html += '</div>';
    
    if (tipo === 'VISTA') {
        $('#status_deposito_vista').html(html);
    } else {
        $('#status_deposito_prazo').html(html);
    }
}
```

### 4. WhatsApp (visualizar.html)

```javascript
// Adicionar após os depósitos de cheques no texto WhatsApp

{% set deposito_vista = depositos_cheques|selectattr('tipo', 'equalto', 'VISTA')|list|first %}
{% if deposito_vista %}
texto += `  📍 Depositado: R$ {{ "{:,.2f}".format(deposito_vista.valor_depositado|float).replace(',', 'X').replace('.', ',').replace('X', '.') }}`;
texto += ` em {{ deposito_vista.data_deposito.strftime("%d/%m/%Y") if deposito_vista.data_deposito else "" }}\n`;
{% set dif_vista = deposito_vista.valor_lancado - deposito_vista.valor_depositado %}
{% if dif_vista|abs < 0.01 %}
texto += `  ✅ Conferido\n`;
{% elif dif_vista > 0 %}
texto += `  ⚠️ Falta: R$ {{ "{:,.2f}".format(dif_vista|abs).replace(',', 'X').replace('.', ',').replace('X', '.') }}\n`;
{% else %}
texto += `  ⚠️ Sobra: R$ {{ "{:,.2f}".format(dif_vista|abs).replace(',', 'X').replace('.', ',').replace('X', '.') }}\n`;
{% endif %}
{% else %}
texto += `  ⏳ Aguardando depósito\n`;
{% endif %}

{% set deposito_prazo = depositos_cheques|selectattr('tipo', 'equalto', 'PRAZO')|list|first %}
{% if deposito_prazo %}
texto += `  📍 Depositado: R$ {{ "{:,.2f}".format(deposito_prazo.valor_depositado|float).replace(',', 'X').replace('.', ',').replace('X', '.') }}`;
texto += ` em {{ deposito_prazo.data_deposito.strftime("%d/%m/%Y") if deposito_prazo.data_deposito else "" }}\n`;
{% set dif_prazo = deposito_prazo.valor_lancado - deposito_prazo.valor_depositado %}
{% if dif_prazo|abs < 0.01 %}
texto += `  ✅ Conferido\n`;
{% elif dif_prazo > 0 %}
texto += `  ⚠️ Falta: R$ {{ "{:,.2f}".format(dif_prazo|abs).replace(',', 'X').replace('.', ',').replace('X', '.') }}\n`;
{% else %}
texto += `  ⚠️ Sobra: R$ {{ "{:,.2f}".format(dif_prazo|abs).replace(',', 'X').replace('.', ',').replace('X', '.') }}\n`;
{% endif %}
{% else %}
texto += `  ⏳ Aguardando depósito\n`;
{% endif %}
```

## 📅 Plano de Implementação

### Fase 1: Preparação (30 min)
- [ ] Criar migration do banco de dados
- [ ] Testar migration em ambiente de dev
- [ ] Backup do banco de produção

### Fase 2: Backend (2h)
- [ ] Criar rota POST para registrar depósito
- [ ] Atualizar GET visualizar para carregar depósitos
- [ ] Atualizar GET editar para carregar depósitos
- [ ] Adicionar validações
- [ ] Testar com Postman/curl

### Fase 3: Frontend - Botões (2h)
- [ ] Adicionar botões vermelhos nos campos
- [ ] Criar modal de registro
- [ ] Implementar cálculo de diferença em tempo real
- [ ] Adicionar indicadores visuais de status
- [ ] Testar interação usuário

### Fase 4: WhatsApp (1h)
- [ ] Adicionar informações de depósito no texto
- [ ] Testar formatação
- [ ] Validar cópia para clipboard

### Fase 5: Testes (1-2h)
- [ ] Teste completo do fluxo
- [ ] Teste de validações
- [ ] Teste de casos extremos
- [ ] Teste de retroatividade (cheques a prazo)

### Fase 6: Documentação (30 min)
- [ ] Atualizar README
- [ ] Criar guia do usuário
- [ ] Documentar API

## 🚨 Riscos e Mitigações

### Risco 1: Mudança no Banco de Dados
**Impacto:** Alto  
**Probabilidade:** Baixa  
**Mitigação:**
- Testar migration extensivamente
- Fazer backup antes do deploy
- Ter plano de rollback pronto

### Risco 2: Complexidade da Retroatividade
**Impacto:** Médio  
**Probabilidade:** Média  
**Mitigação:**
- Permitir edição de lançamentos antigos
- Log de auditoria completo
- Alertas visuais para edições retroativas

### Risco 3: Confusão de Usuário
**Impacto:** Médio  
**Probabilidade:** Alta  
**Mitigação:**
- Interface intuitiva com botões destacados
- Mensagens claras de feedback
- Treinamento da equipe
- Documentação com prints

## 📊 Critérios de Aceitação

- [ ] Botões vermelhos aparecem nos campos de cheques
- [ ] Modal abre ao clicar no botão
- [ ] Valores são salvos corretamente no banco
- [ ] Diferenças são calculadas automaticamente
- [ ] Status aparece abaixo do campo
- [ ] Informações aparecem no WhatsApp
- [ ] Edição retroativa funciona para cheques a prazo
- [ ] Log de auditoria está completo
- [ ] Sem bugs ou erros no console

## 📚 Referências

- Código atual: `/lancamentos_caixa/novo`
- Visualização: `/lancamentos_caixa/visualizar/<id>`
- Fix WhatsApp: commit 7ac25f0
- Documentação: Todos os arquivos `.md` criados

## 💡 Notas Finais

Este é um requisito complexo que adiciona controle financeiro importante ao sistema. Recomenda-se:

1. **Implementar em branch separada** após merge do fix do WhatsApp
2. **Testar extensivamente** antes de deploy
3. **Treinar usuários** antes de usar em produção
4. **Monitorar** primeiros dias de uso
5. **Coletar feedback** e ajustar conforme necessário

---

**Documento criado em:** 2026-02-04  
**Versão:** 1.0  
**Status:** Pendente de implementação
