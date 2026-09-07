-- Q-COLABORE: os colaboradores largam o arquivo numa pasta da maquina deles e
-- o agente entrega direto no Dropbox, via este servidor.
--
-- Por que passa pelo servidor e nao vai direto ao Dropbox: as cinco maquinas
-- nao tem Dropbox nem acesso a nada. Mandar a credencial do Dropbox para
-- computador de terceiro seria entregar a nuvem inteira. Assim a credencial
-- nunca sai daqui, cada pessoa tem uma chave que se revoga sozinha, e de
-- quebra fica registrado quem mandou o que -- que e o que hoje se resolve por
-- mensagem no WhatsApp.
--
-- A CHAVE NAO E GUARDADA. So o SHA-256 dela e um prefixo de 8 caracteres, que
-- serve para a tela dizer de qual chave esta falando. Vazar esta tabela nao
-- da acesso a nada. O segredo em claro aparece UMA vez, na hora de gerar.
--
-- CUIDADO ao editar: o runner divide este arquivo por PONTO-E-VIRGULA, e
-- nao entende que um deles esta dentro de comentario. Um deles numa frase
-- em portugues aqui parte a migration ao meio e ela falha com erro 1064.
CREATE TABLE IF NOT EXISTS colabore_config (
    id                  INT AUTO_INCREMENT PRIMARY KEY,
    usuario_id          INT          NOT NULL,
    token_hash          VARCHAR(64)  NULL,
    token_prefixo       VARCHAR(8)   NULL,
    versao              INT          NOT NULL DEFAULT 0,
    data_inicio_captura DATE         NULL,
    ativo               TINYINT(1)   NOT NULL DEFAULT 1,
    ultimo_contato      DATETIME     NULL,
    token_gerado_em     DATETIME     NULL,
    token_gerado_por    INT          NULL,
    criado_em           TIMESTAMP    NULL DEFAULT CURRENT_TIMESTAMP,
    atualizado_em       TIMESTAMP    NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_colabore_usuario (usuario_id),
    UNIQUE KEY uk_colabore_hash (token_hash),
    CONSTRAINT fk_colabore_usuario FOREIGN KEY (usuario_id)
        REFERENCES usuarios(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- O que chegou, de quem e quando. E ESTA tabela que substitui o "me mandaram
-- no WhatsApp": sem ela o trabalho manual vira caixa-preta.
--
-- O nome do arquivo E gravado aqui, ao contrario do Qualicontax, que evita de
-- proposito porque nome de .pfx costuma carregar a senha do certificado. Neste
-- app so entram OFX e planilha, onde o nome nao esconde segredo nenhum -- e e
-- justamente o que se precisa ver na lista.
CREATE TABLE IF NOT EXISTS colabore_recebidos (
    id             INT AUTO_INCREMENT PRIMARY KEY,
    usuario_id     INT          NOT NULL,
    nome_original  VARCHAR(255) NOT NULL,
    nome_final     VARCHAR(255) NOT NULL,
    ext            VARCHAR(12)  NOT NULL,
    tamanho_bytes  INT          NOT NULL,
    destino        VARCHAR(255) NOT NULL,
    ip             VARCHAR(45)  NULL,
    recebido_em    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY ix_colabore_recebidos_quando (recebido_em),
    KEY ix_colabore_recebidos_usuario (usuario_id, recebido_em)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
