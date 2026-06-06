-- Migration: add barcode (linha digitável) and pix_qrcode columns to cobrancas
ALTER TABLE cobrancas
  ADD COLUMN IF NOT EXISTS barcode VARCHAR(120) NULL COMMENT 'Linha digitável / barcode retornado pela EFI',
  ADD COLUMN IF NOT EXISTS pix_qrcode TEXT NULL COMMENT 'QR Code Pix (copia e cola) retornado pela EFI';
