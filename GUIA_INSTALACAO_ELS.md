# Integração ELS por e-mail — Guia de instalação (nh-transportes)

Esta integração lê os e-mails do sistema de medição **ELS (EXCELbr)** e grava no
banco do app, seguindo os padrões que o projeto já usa (`utils.db`,
criação idempotente de tabelas, agendador APScheduler com `GET_LOCK`).

## Arquivos adicionados (novos, não alteram nada existente)

- `integrations/els_email.py` — leitura IMAP, parsing e gravação.
- `integrations/els_scheduler.py` — agendador (a cada 10 min, fuso de Brasília).

## O que faz

| E-mail do ELS (remetente `notificacao@sistemaels.com.br`) | Ação no app |
|---|---|
| `Fechamento de turno - ABERTURA` | Grava **leitura diária** por tanque em `leitura_tanque_diaria` (Volume atual = estoque inicial do dia). |
| `Alarme descarga` | Registra em `descargas_pendentes` e, se casar com **um** frete, cria a linha em `descargas` (status `vinculada`). |

As tabelas `leitura_tanque_diaria` e `descargas_pendentes` são criadas
automaticamente na primeira execução (padrão `CREATE TABLE IF NOT EXISTS`).

> **Estado em 13/08/2026: em produção e estável.** Os passos 1 a 5 já foram
> executados; este guia vale como referência de manutenção, não como roteiro de
> instalação. Medido na base: 15 dias seguidos (30/07 a 13/08) com as 4 leituras
> de abertura por dia, sem falha. O e-mail chega ~05:00 e a gravação sai entre
> 05:08 e 05:10 — a espera normal é de 8 a 10 minutos, não é travamento.
> Atenção ao fuso: `criado_em` no banco está em **UTC** (3h à frente).

## Passo 1 — Ligar o agendador no `app.py` (JÁ FEITO)

Em `create_app()`, logo **depois** do bloco do `dfe_scheduler` (hoje por volta da
linha 487, antes de `return app`), existe o bloco análogo:

```python
    # Agendador da importação automática do ELS por e-mail (a cada 10 min;
    # lock global no MySQL garante execução única mesmo com vários workers).
    try:
        from integrations.els_scheduler import iniciar_scheduler as iniciar_els
        iniciar_els(app)
    except Exception:
        app.logger.warning("[els_sched] não foi possível iniciar o scheduler.", exc_info=True)
```

## Passo 2 — Variáveis de ambiente (no Railway)

```
ELS_MAIL_IMAP_HOST=imap.titan.email        # Titan; se a caixa for Gmail: imap.gmail.com
ELS_MAIL_IMAP_PORT=993
ELS_MAIL_USER=goiatuba@postonovohorizonte.com.br   # a caixa que RECEBE os e-mails do ELS
ELS_MAIL_PASSWORD=****                      # senha de APP do provedor (não a senha principal)
ELS_REMETENTE=notificacao@sistemaels.com.br
ELS_CLIENTE_ID=<id do Posto Novo Horizonte na tabela clientes>   # OBRIGATÓRIO
# Opcionais:
ELS_SCHED_MINUTE=*/10
ELS_MATCH_TOLERANCIA=500     # litros de tolerância no casamento com o volume NF do frete
ELS_MATCH_JANELA_DIAS=5      # janela de dias para procurar o frete
```

> **ELS_CLIENTE_ID**: rode `SELECT id, razao_social FROM clientes WHERE razao_social LIKE '%NOVO HORIZONTE%';`
> e use o id do posto.

### Senha de app no Titan
Painel do Titan → conta `goiatuba@postonovohorizonte.com.br` → Segurança →
**Senhas de app** → gerar uma para "Integração ELS" e usar em `ELS_MAIL_PASSWORD`.
(Se a caixa estiver no Gmail/Workspace, gere uma senha de app do Google com 2FA
ligado e use `imap.gmail.com`.)

## Passo 3 — Casamento descarga ↔ frete

Como o e-mail do ELS **não traz o número do frete**, o casamento é por:
mesmo `cliente_id` + `produto_id`, `data_frete` dentro da janela, e volume NF
(`quantidade_manual`) próximo do "Total da descarga" (tolerância configurável),
descartando fretes que já têm descarga `finalizado`.

- **Casou com exatamente 1 frete** → cria a descarga (status `vinculada`).
- **Nenhum ou vários candidatos** → fica em `descargas_pendentes` com status
  `pendente`, sem criar descarga (nunca vincula errado).

A tela de confirmação **já existe**: `/estoque` (`routes/estoque.py`), com as
abas **Leituras** e **Descargas**, o modal de vínculo descarga → frete
(`/estoque/descarga/<id>/vinculo`) e o botão "Reler e-mails de descarga" para
recuperar e-mail que foi aberto na mão antes do agendador passar.

## Passo 4 — Mapeamento de produto

`resolver_produto_id()` casa o nome do e-mail ("GASOLINA COMUM", "ETANOL COMUM",
"DIESEL S500 COMUM", "DIESEL S10 COMUM") com `produto.nome` (match exato, depois
por conteúdo, depois por palavra-chave). Confira se os nomes na tabela `produto`
batem; se algum produto novo não casar, é só ajustar o nome no cadastro.

## Passo 5 — Testar

1. Deploy com as variáveis configuradas.
2. Forçar uma execução imediata (sem esperar o agendador), por exemplo num shell
   do app:
   ```python
   from integrations.els_email import processar
   print(processar(dias=2))   # lê e-mails não lidos dos últimos 2 dias
   ```
   Retorna um resumo: `{'aberturas':.., 'leituras':.., 'descargas_vinculadas':..,
   'descargas_pendentes':.., 'ignorados':..}`.
3. Conferir as tabelas:
   ```sql
   SELECT * FROM leitura_tanque_diaria ORDER BY data_leitura DESC LIMIT 10;
   SELECT * FROM descargas_pendentes ORDER BY criado_em DESC LIMIT 10;
   ```

O parser foi validado contra e-mails reais: ABERTURA (Gasolina 3.100, Etanol
5.813, Diesel 12.924 L) e Alarme descarga (Diesel S500, 4.959 L).

## Observações de segurança / operação

- Só processa e-mails **não lidos** e os marca como lidos → não duplica.
- Idempotência extra: descargas usam a chave `tanque + data_final`; leitura
  diária usa `UNIQUE(cliente_id, data_leitura, tanque)`.
- Nenhum arquivo existente é alterado além do bloco no `app.py` (passo 1).
- Falha na importação **não derruba** o app (o bloco é protegido por try/except).

## Futuro — integração direta com o ELS (sem e-mail)

O ELS (EXCELbr) também exporta por **arquivo XML** e por **MODBUS TCP/IP**, e
integra com ERPs, mas não há API pública documentada — é preciso habilitar/
configurar com a EXCELbr (vendas@excelbr.com.br, (11) 3858-7724) e normalmente
ler da máquina local do ELS no posto. Quando/se quiserem migrar do e-mail para o
XML, só a camada de leitura muda; a parte de gravação (tabelas, casamento de
frete) continua igual.
