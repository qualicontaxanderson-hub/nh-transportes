-- NH-ROBO: as horas gravadas ate aqui estao em UTC. Passam para Brasilia.
--
-- O container da Railway roda em UTC, e recebido_em vinha do DEFAULT
-- CURRENT_TIMESTAMP. Resultado na tela: um arquivo entregue as 21h18 aparecia
-- como 00:18 do dia seguinte -- hora que ninguem trabalha e, pior, DIA errado.
-- Quem fosse procurar o extrato pela data nao o acharia.
--
-- A partir do commit que acompanha esta migration quem carimba a hora e o
-- Python (utils/fuso.agora_brasilia), nao o NOW() do banco. Isto aqui conserta
-- so o que ja estava gravado.
--
-- -3h fixo e nao CONVERT_TZ com nome de fuso: a tabela de fusos do MySQL
-- costuma vir vazia em container, e o Brasil nao tem mais horario de verao
-- desde 2019 -- o deslocamento e constante.
--
-- RODA UMA VEZ SO. O runner grava o nome em schema_migrations e nunca repete;
-- rodar duas vezes tiraria 6 horas em vez de 3.
--
-- criado_em e atualizado_em ficam como estao de proposito: sao carimbos
-- internos, nao aparecem em tela nenhuma.
--
-- CUIDADO ao editar: o runner divide este arquivo por PONTO-E-VIRGULA e nao
-- entende que um deles esta dentro de comentario.

UPDATE nhrobo_recebidos SET recebido_em = recebido_em - INTERVAL 3 HOUR;

UPDATE nhrobo_config
   SET ultimo_contato = ultimo_contato - INTERVAL 3 HOUR
 WHERE ultimo_contato IS NOT NULL;

UPDATE nhrobo_config
   SET token_gerado_em = token_gerado_em - INTERVAL 3 HOUR
 WHERE token_gerado_em IS NOT NULL;
