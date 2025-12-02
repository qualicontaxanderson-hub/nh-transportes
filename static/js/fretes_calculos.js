// (apenas o trecho final do handler do botão Importar mudou — mas aqui envio o arquivo completo mínimo
// necessário para o comportamento do botão: dispatch do evento 'abrirImportacaoPedido' + chamada da função)

document.addEventListener('DOMContentLoaded', function() {
    // ... (presumo que todo o conteúdo do fretes_calculos.js já está no arquivo)
    // Fallback/compatibilidade do botão "Importar Pedido":
    const btnImport = document.getElementById('btn_importar_pedido');
    if (btnImport) {
        btnImport.addEventListener('click', function() {
            // 1) Disparar evento para compatibilidade com módulos que escutam esse evento
            try {
                const ev = new CustomEvent('abrirImportacaoPedido', { bubbles: true, cancelable: true });
                window.dispatchEvent(ev);
            } catch (e) {
                // older browsers fallback
                const ev2 = document.createEvent('Event');
                ev2.initEvent('abrirImportacaoPedido', true, true);
                window.dispatchEvent(ev2);
            }

            // 2) Se existir a função global (código antigo), chama também
            if (typeof window.abrirImportacaoPedido === 'function') {
                try {
                    window.abrirImportacaoPedido();
                } catch (err) {
                    console.error('Erro ao chamar abrirImportacaoPedido():', err);
                }
            }
        });
    }

    // resto da inicialização...
});
