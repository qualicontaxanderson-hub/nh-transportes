-- Tabela chave/valor do aplicativo.
--
-- Criada porque este banco NAO tem nenhuma tabela de configuracao generica:
-- nao existe `parametros` nem `app_config`, e `config_pagamentos_efi` e
-- especifica da EFI. O primeiro morador e o status do backup na nuvem
-- (chave 'backup_bd_status'), lido pelo card do dashboard.
--
-- `updated_at` e a fonte da IDADE do backup, e por isso o card usa o relogio
-- do BANCO (TIMESTAMPDIFF ... NOW()) e nunca o datetime.now() do Python, que
-- diverge entre o worker web e o container do cron.
--
-- O modulo utils/backup_bd.py tambem cria esta tabela sozinho (CREATE TABLE IF
-- NOT EXISTS) porque o servico de cron roda `python cron_backup.py` sem subir
-- o Flask -- ou seja, sem passar pelo runner de migrations.
CREATE TABLE IF NOT EXISTS `app_config` (
    `chave`      VARCHAR(100) NOT NULL,
    `valor`      TEXT         NULL,
    `updated_at` TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`chave`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
