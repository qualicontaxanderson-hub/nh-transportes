-- Ponto com foto: o registro de quem chegou, a que horas e onde.
--
-- O problema que esta tabela resolve nao e "anotar horario" -- isso o papel
-- ja fazia. E o Joao pegar o cartao do Marcelo e bater por ele. Por isso a
-- FOTO nao e opcional nem enfeite: e a coluna que faz o registro valer. Sem
-- ela a linha nao deveria existir, e a rota recusa grava-la.
--
-- A empresa nao tem obrigacao legal de ponto (poucos funcionarios), entao
-- aqui nao ha nada de Portaria 671: e controle interno. Mas o registro ja
-- nasce imutavel -- so INSERT, nunca UPDATE do horario -- porque um ponto que
-- se edita depois nao serve nem para controle interno.
--
-- momento e UTC, gravado pelo SERVIDOR. Nunca a hora do aparelho: relogio de
-- celular se muda no ajuste de data e hora, e ai o ponto vira ficcao.
--
-- A foto mora aqui em MEDIUMBLOB e nao em arquivo porque o container do
-- Railway perde o disco a cada deploy. Ja ha precedente no proprio app: o
-- certificado da DFe e um LONGBLOB. Guardada pequena (o navegador reduz para
-- 480px antes de enviar, ~30 KB), da uns 40 MB por ano com 11 funcionarios
-- batendo quatro vezes ao dia.
--
-- lat/lng aceitam NULL de proposito: se o funcionario negar a localizacao, a
-- batida TEM de acontecer mesmo assim -- senao o trabalho para na porta por
-- causa de uma permissao. A tela do gestor mostra "sem localizacao" bem
-- visivel, que resolve melhor do que impedir.
--
-- CUIDADO ao editar: o runner divide este arquivo por PONTO-E-VIRGULA, sem
-- entender que um deles pode estar dentro de comentario.

CREATE TABLE IF NOT EXISTS `ponto_batidas` (
    `id`             INT AUTO_INCREMENT PRIMARY KEY,
    `funcionario_id` INT          NOT NULL,
    `cliente_id`     INT          NULL,
    `tipo`           VARCHAR(8)   NOT NULL,
    `momento`        DATETIME     NOT NULL,
    `foto`           MEDIUMBLOB   NOT NULL,
    `foto_mime`      VARCHAR(32)  NOT NULL DEFAULT 'image/jpeg',
    `foto_bytes`     INT          NOT NULL DEFAULT 0,
    `lat`            DECIMAL(10,7) NULL,
    `lng`            DECIMAL(10,7) NULL,
    `precisao_m`     INT          NULL,
    `geo_negada`     TINYINT(1)   NOT NULL DEFAULT 0,
    `dispositivo`    VARCHAR(255) NULL,
    `usuario_id`     INT          NULL,
    `ip`             VARCHAR(45)  NULL,
    `observacao`     VARCHAR(255) NULL,
    `criado_em`      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY `ix_ponto_func_momento` (`funcionario_id`, `momento`),
    KEY `ix_ponto_momento` (`momento`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
