# Sistema de Gerenciamento de Despesas - Instruções de Deploy

## Visão Geral

Este documento descreve como fazer o deploy do novo sistema de gerenciamento de despesas para a aplicação NH Transportes.

## Arquivos Criados

### Modelos (models/)
- `titulo_despesa.py` - Modelo para títulos principais de despesas
- Atualizações em `categoria_despesa.py` - Adicionado relacionamento com títulos
- Atualizações em `subcategoria_despesa.py` - Adicionado campo ordem

### Rotas (routes/)
- `despesas.py` - Rotas completas para gerenciamento de despesas (CRUD)

### Templates (templates/despesas/)
- `index.html` - Lista de títulos de despesas
- `titulo_detalhes.html` - Detalhes e categorias de um título
- `categoria_detalhes.html` - Detalhes e subcategorias de uma categoria
- `titulo_form.html` - Formulário para criar/editar títulos
- `categoria_form.html` - Formulário para criar/editar categorias
- `subcategoria_form.html` - Formulário para criar/editar subcategorias

### Migrações (migrations/)
- `20260212_add_titulos_despesas.sql` - Cria tabela titulos_despesas e adiciona campos necessários
- `20260212_seed_despesas.sql` - Popula banco com estrutura inicial de despesas

### Outros
- Atualização em `templates/includes/navbar.html` - Adiciona menu "Despesas" acima de "Funcionários"

## Estrutura de Dados

O sistema usa uma hierarquia de 3 níveis:

1. **Título** (ex: DESPESAS OPERACIONAIS, IMPOSTOS, etc.)
2. **Categoria** (ex: ADVOGADO, CONTADOR, ALUGUEL, etc.)
3. **Subcategoria** (ex: Para veículos: DOCUMENTOS, ABASTECIMENTOS, MANUTENÇÃO)

## Instruções de Deploy

### 1. Executar Migrações no Banco de Dados

Execute os seguintes scripts SQL **nesta ordem**:

```bash
# 1. Criar estrutura de títulos
mysql -h <host> -u <user> -p <database> < migrations/20260212_add_titulos_despesas.sql

# 2. Popular com dados iniciais
mysql -h <host> -u <user> -p <database> < migrations/20260212_seed_despesas.sql
```

Ou use o script Python fornecido (se tiver acesso ao banco):
```bash
python3 run_migrations.py
```

### 2. Verificar Deploy

Após o deploy, verifique:

1. **Acesso ao Menu**: No menu "Cadastros", deve aparecer "Despesas" acima de "Funcionários"

2. **Títulos Criados**: Devem existir 9 títulos:
   - DESPESAS OPERACIONAIS
   - IMPOSTOS
   - FINANCEIRO
   - DESPESAS POSTO
   - FUNCIONÁRIOS
   - VEICULOS EMPRESA
   - CAMINHÕES
   - INVESTIMENTOS
   - DESPESAS PESSOAIS (MONICA)

3. **Categorias Populadas**: Cada título deve ter suas categorias correspondentes

### 3. Estrutura Completa de Dados Populados

#### DESPESAS OPERACIONAIS (24 categorias)
- ADVOGADO, CONTADOR, ALUGUEL, CARTÃO DE CREDITO - SANTANDER, CARTÃO DE CRÉDITO - CORA, INTERNET, ENGENHEIRO, ENERGIA, AGUA, GRAFICA - BOIÃO, GRAFICA - IDEIAS, FRETES TERCEIROS, MATERIAIS DE LIMPEZA, MATERIAIS ELÉTRICOS, MATERIAIS DE CONSTRUÇÃO, SISTEMA - SOFTWARE, MECANICO, SERVIÇOS DE ELETRICISTAS, SERVIÇOS DE PINTURAS, SERVIÇOS DE REFORMAS, SERVIÇOS DE SERRALHERIA, SEGUROS EMPRESARIAIS, TELEFONE MÓVEL, PROPAGANDAS

#### IMPOSTOS (12 categorias)
- IBAMA, FUNAPE, IMPOSTO DE RENDA - IRPJ, CONTRIBUIÇÃO SOCIAL - CSLL, DARE ICMS, TAXAS TESOURO, TAXA TRIBUNAL DE JUSTIÇA, INMETRO, AMBIENTAL, TX MUNICIPAL, IPTU, DAS PREST

#### FINANCEIRO (8 categorias)
- CESTA DE RELACIONAMENTO - SICREDI, BOLETOS, TARIFA BANCÁRIA - SANTANDER, TARIFA PIX - SANTANDER, CARTÃO DE DEBITO - SICREDI, CARTÃO DE CREDITO - SICREDI, CARTÃO DE CREDITO - SICREDI ANTECIPAÇÃO, IOF SANTANDER

#### DESPESAS POSTO (8 categorias)
- MATERIAIS DE ESCRITÓRIO, MATERIAIS ELETRICOS, MANUTENÇÃO DIVERSAS, FUNCIONÁRIOS POSTO, MATERIAIS LIMPEZA, DESPESAS POP, SOBRAS DE CAIXA, FALTA DE CAIXA

#### FUNCIONÁRIOS (7 categorias)
- FGTS, VALE ALIMENTAÇÃO, BENEFICIO SOCIAL, ODONTO BENEFICIO SOCIAL, FUNCIONÁRIOS, FÉRIAS, UNIFORMES

#### VEICULOS EMPRESA (2 categorias com subcategorias)
- **FIORINO**: DOCUMENTOS IPVA/MULTA, ABASTECIMENTOS, MANUTENÇÃO
- **POP**: DOCUMENTOS IPVA/MULTA, ABASTECIMENTOS, MANUTENÇÃO

#### CAMINHÕES (2 categorias com 19 subcategorias cada)
- **VEICULO CARRETA MODELO SCANIA R500**
- **VEICULO TRUCK MODELO ACTROS 1620**
  - Subcategorias: FATURAMENTO DO VEICULOS, MOTORISTA, MOTORISTA ADICIONAL, COMISSÃO DO MOTORISTA, FGTS, VALE ALIMENTAÇÃO, BENEFICIO SOCIAL, ODONTO BENEFICIO SOCIAL, COMISSÃO CT-e, COMBUSTIVEL, PEDAGIOS, SASCAR, DOCUMENTOS CAMINHÃO, MULTAS, MANUTENÇÃO CAMINHÃO, PEÇAS CAMINHÃO, PNEUS, LAVAJATO, SEGURO

#### INVESTIMENTOS (4 categorias)
- INTEGRALIZAÇÃO CAPITAL - SICREDI, CONSÓRCIO - SANTANDER, APLICAÇÃO DE FUNDOS - SICREDI, (-) RESGATE DE FUNDOS - SICREDI

#### DESPESAS PESSOAIS (MONICA) (16 categorias com subcategorias)
- CARTÃO CARREFOUR, CARTÃO NUBANK, MARIA HELENA, RODRIGO, ABASTECIMENTOS, UNIMED, FACULDADE, COLÉGIO - DRUMMOND
- **Propriedades com subcategorias** (PARCELA, IPTU): SÃO SIMÃO, ANAPOLIS, CASA GOIATUBA, MORRINHOS RECANTO DAS ARARAS, BR-153
- **Veículos com subcategorias** (IPVA, SEGURO, DESPACHANTE, ABASTECIMENTO): VEICULO COMMANDER, VEICULO F-250
- **DIVERSOS** com subcategoria: VESTIMENTA

## Funcionalidades Implementadas

### Para Administradores e Gerentes:
- ✅ Criar, editar e desativar (soft delete) títulos
- ✅ Criar, editar e desativar categorias
- ✅ Criar, editar e desativar subcategorias
- ✅ Organizar por ordem de exibição

### Para Todos os Usuários:
- ✅ Visualizar hierarquia completa de despesas
- ✅ Navegar entre títulos → categorias → subcategorias
- ✅ Interface responsiva e intuitiva

## Próximos Passos (Futuras Implementações)

As seguintes funcionalidades foram mencionadas nos requisitos mas não foram implementadas nesta fase:

1. **Integração com Sistema de Funcionários**: Links para puxar dados de:
   - `/lancamentos-funcionarios/` (FGTS, VALE ALIMENTAÇÃO, BENEFICIO SOCIAL, etc.)
   - `/relatorios/fretes_comissao_motorista`
   - `/relatorios/fretes_comissao_cte`

2. **Integração com Sistema de Veículos**:
   - Vincular motoristas aos veículos
   - Puxar faturamento de `/relatorios/fretes_lucro`

3. **Lançamentos de Despesas**: Sistema para registrar lançamentos reais contra estas categorias

4. **Relatórios**: Análise de despesas por título/categoria/período

## Observações Importantes

- ⚠️ As migrações devem ser executadas **ANTES** de reiniciar a aplicação
- ⚠️ O sistema usa soft delete (campo `ativo = 0`) ao invés de deletar registros
- ⚠️ O campo `ordem` permite organizar a exibição de títulos, categorias e subcategorias
- ⚠️ Apenas usuários com nível ADMIN ou GERENTE podem criar/editar/excluir

## Suporte

Em caso de problemas durante o deploy:
1. Verifique se as migrações foram executadas corretamente
2. Verifique os logs da aplicação
3. Confirme que as tabelas foram criadas: `titulos_despesas`, alterações em `categorias_despesas` e `subcategorias_despesas`
