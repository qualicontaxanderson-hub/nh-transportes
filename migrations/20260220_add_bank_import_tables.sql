-- SQL Migration for Bank Account Import System

CREATE TABLE bank_accounts (
    id SERIAL PRIMARY KEY,
    account_number VARCHAR(30) NOT NULL,
    account_name VARCHAR(100) NOT NULL,
    bank_name VARCHAR(100) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE bank_transactions (
    id SERIAL PRIMARY KEY,
    bank_account_id INT NOT NULL,
    transaction_date DATE NOT NULL,
    amount DECIMAL(10, 2) NOT NULL,
    transaction_type VARCHAR(10) NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (bank_account_id) REFERENCES bank_accounts(id)
);

CREATE TABLE bank_supplier_mapping (
    id SERIAL PRIMARY KEY,
    bank_account_id INT NOT NULL,
    supplier_name VARCHAR(100) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (bank_account_id) REFERENCES bank_accounts(id)
);