CREATE TABLE estoque_inicial_global (
    id INT AUTO_INCREMENT PRIMARY KEY,
    cliente_id INT NOT NULL,
    produto_id INT NOT NULL,
    data_inicio DATE NOT NULL,
    quantidade_inicial DECIMAL(12,3) NOT NULL DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_eig_cliente_produto (cliente_id, produto_id),
    INDEX (cliente_id),
    INDEX (produto_id),
    FOREIGN KEY (cliente_id) REFERENCES clientes(id),
    FOREIGN KEY (produto_id) REFERENCES produto(id)
);

CREATE TRIGGER prevent_update BEFORE UPDATE ON estoque_inicial_global
FOR EACH ROW
BEGIN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Updates are not allowed on estoque_inicial_global';
END;

CREATE TRIGGER prevent_delete BEFORE DELETE ON estoque_inicial_global
FOR EACH ROW
BEGIN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Deletes are not allowed on estoque_inicial_global';
END;