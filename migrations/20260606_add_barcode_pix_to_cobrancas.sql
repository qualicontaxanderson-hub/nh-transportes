-- Guarda a linha digitavel e o Pix copia-e-cola que a EFI devolve na emissao.
-- Sem estas colunas os dois vinham na resposta e eram jogados fora: o app ja
-- gravava (utils/boletos.py) e ja lia de volta (routes/financeiro.py), so nao
-- tinha onde por.
--
-- A versao anterior deste arquivo usava ADD COLUMN IF NOT EXISTS, que e
-- sintaxe de MariaDB/Postgres — o MySQL recusa com erro 1064. Cada coluna vai
-- num ALTER separado para que uma que ja exista (erro 1060, tratado como "ja
-- aplicado") nao impeca a outra de ser criada.
ALTER TABLE cobrancas
  ADD COLUMN barcode VARCHAR(120) NULL COMMENT 'Linha digitavel devolvida pela EFI';

ALTER TABLE cobrancas
  ADD COLUMN pix_qrcode TEXT NULL COMMENT 'Pix copia e cola devolvido pela EFI';
