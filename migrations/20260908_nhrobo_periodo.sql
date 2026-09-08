-- NH-ROBO: de que documento e de que periodo e cada arquivo que chegou.
--
-- A aba Historico precisa responder "extrato de agosto", nao "arquivo.ofx":
-- quem pergunta no escritorio nunca pergunta pelo nome do arquivo.
--
-- Guardado em COLUNA e nao calculado na hora de mostrar porque o periodo sai
-- de DENTRO do arquivo (DTSTART do OFX, registro 0000 do SPED, dhEmi do XML),
-- e o arquivo mora no Dropbox. Recalcular a tela inteira seria baixar 200
-- arquivos do Dropbox a cada F5.
--
-- Tudo NULL: linha sem periodo e o caso normal, nao defeito. Planilha e PDF
-- costumam nao dizer nada, e a tela mostra um travessao.
--
-- periodo_fonte diz de onde veio -- 'arquivo' (de dentro dele) ou 'nome' (do
-- nome do arquivo). Sem isso a tela nao teria como avisar que aquele periodo
-- e uma leitura do nome, que e a parte que pode errar.
--
-- CUIDADO ao editar: o runner divide este arquivo por PONTO-E-VIRGULA e nao
-- entende que um deles esta dentro de comentario. Um deles numa frase em
-- portugues aqui parte a migration ao meio e ela falha com erro 1064.

ALTER TABLE nhrobo_recebidos ADD COLUMN doc_tipo VARCHAR(16) NULL;

ALTER TABLE nhrobo_recebidos ADD COLUMN periodo_ini DATE NULL;

ALTER TABLE nhrobo_recebidos ADD COLUMN periodo_fim DATE NULL;

ALTER TABLE nhrobo_recebidos ADD COLUMN periodo_fonte VARCHAR(8) NULL;

ALTER TABLE nhrobo_recebidos ADD KEY ix_nhrobo_recebidos_tipo (doc_tipo, recebido_em);
