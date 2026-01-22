# Guia de Solução de Problemas - Sistema de Funcionários

## Problema: "não apareceu no URL nada"

### Solução Aplicada ✅

Adicionei os itens de menu na barra de navegação. Agora os novos módulos aparecem no menu!

### Como Verificar

**1. Restart da Aplicação**
```bash
# Para o serviço Flask atual (Ctrl+C ou kill)
# Reinicie a aplicação
python app.py
# ou
gunicorn app:app
```

**2. Acesse o Sistema**
- Faça login no sistema
- Veja o menu "Cadastros" - agora tem 3 novos itens:
  - 👥 Funcionários
  - 🏷️ Categorias Funcionários
  - ✓ Rubricas
- Veja o menu "Lançamentos" - agora tem:
  - 📅 Lançamentos Funcionários

**3. Teste Cada Módulo**

**Funcionários:** `/funcionarios`
- Lista todos os funcionários
- Botão "Novo Funcionário" para cadastrar

**Categorias:** `/categorias-funcionarios`
- Lista categorias (MOTORISTA, FRENTISTA, etc)
- Botão "Nova Categoria" para adicionar

**Rubricas:** `/rubricas`
- Lista componentes salariais (SALÁRIO BASE, VALE ALIMENTAÇÃO, etc)
- Botão "Nova Rubrica" para adicionar

**Lançamentos:** `/lancamentos-funcionarios`
- Formulário de lançamento mensal
- Lista de lançamentos por mês/cliente

### Se Ainda Não Aparecer

**Verifique os Logs da Aplicação:**
```bash
# Procure por erros de blueprint registration
grep -i "blueprint" logs/app.log
grep -i "funcionario" logs/app.log
```

**Possíveis Erros:**

1. **Erro de Import:**
   - Verifique se todos os pacotes estão instalados: `pip install -r requirements.txt`

2. **Erro de Banco de Dados:**
   - As tabelas existem? Execute a migração se necessário
   - Verifique conexão com o banco

3. **Erro de Permissão:**
   - Verifique se o usuário tem permissão de admin para acessar

**Teste Direto das URLs:**
```bash
# Com a aplicação rodando, teste:
curl http://localhost:5000/funcionarios/
curl http://localhost:5000/categorias-funcionarios/
curl http://localhost:5000/rubricas/
curl http://localhost:5000/lancamentos-funcionarios/
```

### Estrutura de Arquivos

```
routes/
├── funcionarios.py              ✓ Criado
├── categorias_funcionarios.py   ✓ Criado
├── rubricas.py                  ✓ Criado
└── lancamentos_funcionarios.py  ✓ Criado

templates/
├── funcionarios/
│   ├── lista.html               ✓ Criado
│   ├── novo.html                ✓ Criado
│   ├── editar.html              ✓ Criado
│   └── vincular_veiculo.html    ✓ Criado
├── categorias_funcionarios/
│   ├── lista.html               ✓ Criado
│   ├── novo.html                ✓ Criado
│   └── editar.html              ✓ Criado
├── rubricas/
│   ├── lista.html               ✓ Criado
│   ├── novo.html                ✓ Criado
│   └── editar.html              ✓ Criado
├── lancamentos_funcionarios/
│   ├── lista.html               ✓ Criado
│   ├── novo.html                ✓ Criado
│   └── detalhe.html             ✓ Criado
└── includes/
    └── navbar.html              ✓ Atualizado (commit 4ebc02a)

models/
├── categoria_funcionario.py     ✓ Criado
├── rubrica.py                   ✓ Criado
├── funcionario.py               ✓ Criado
└── lancamento_funcionario.py    ✓ Criado
```

### Debug Step-by-Step

**1. Verifique se o Flask está carregando os blueprints:**
```python
# No console Python (depois de iniciar a app):
from app import app
print(app.blueprints.keys())
# Deve mostrar: 'funcionarios', 'categorias_funcionarios', 'rubricas', 'lancamentos_funcionarios'
```

**2. Verifique as rotas registradas:**
```python
from app import app
for rule in app.url_map.iter_rules():
    if 'funcionario' in rule.rule or 'rubrica' in rule.rule:
        print(rule)
```

**3. Teste um endpoint específico:**
```bash
# Com curl ou no navegador
curl -v http://localhost:5000/funcionarios/
```

### Contato

Se ainda houver problemas, forneça:
1. Mensagem de erro completa (se houver)
2. Logs da aplicação
3. Resultado dos testes acima

Commit com menu: **4ebc02a**
