document.addEventListener('DOMContentLoaded', function () {
  // Utility
  function qs(sel, el=document) { return el.querySelector(sel); }
  function qsa(sel, el=document) { return Array.from(el.querySelectorAll(sel)); }

  // Modal elements
  const modal = qs('#emit-boleto-modal');
  const emitForm = qs('#emit-boleto-form');
  const modalFreteId = qs('#modal_frete_id');
  const modalVenc = qs('#modal_vencimento');
  const feedback = qs('#emit-boleto-feedback');
  const emitBtn = qs('#modal_emit_btn');

  // Open modal when clicking Emitir Boleto button
  qsa('.btn-emit-boleto').forEach(btn => {
    btn.addEventListener('click', (e) => {
      const freteId = btn.getAttribute('data-frete-id');
      if (btn.disabled) return;
      modalFreteId.value = freteId;
      // default vencimento: +7 dias
      const d = new Date();
      d.setDate(d.getDate() + 7);
      modalVenc.value = d.toISOString().slice(0,10);
      feedback.style.display = 'none';
      showModal();
    });
  });

  function showModal() {
    modal.style.display = 'block';
    modal.classList.add('show');
    modal.focus && modal.focus();
  }
  function closeModal() {
    modal.style.display = 'none';
    modal.classList.remove('show');
  }
  qsa('[data-action="close-modal"]').forEach(btn => btn.addEventListener('click', closeModal));

  // Emitir form submit
  emitForm.addEventListener('submit', async function (ev) {
    ev.preventDefault();
    emitBtn.disabled = true;
    feedback.style.display = 'none';
    const freteId = modalFreteId.value;
    const venc = modalVenc.value;
    try {
      const resp = await fetch(`/financeiro/emitir-boleto/${freteId}/`, {
        method: 'POST',
        headers: {'Content-Type':'application/json', 'X-Requested-With':'XMLHttpRequest'},
        body: JSON.stringify({vencimento: venc})
      });
      const j = await resp.json();
      if (resp.ok && j.success) {
        feedback.className = 'alert alert-success';
        feedback.textContent = 'Boleto emitido com sucesso.';
        feedback.style.display = 'block';
        // desabilitar botão de emitir na linha do frete
        const btn = document.querySelector(`.btn-emit-boleto[data-frete-id="${freteId}"]`);
        if (btn) { btn.disabled = true; btn.title = 'Boleto emitido'; }
        // opcional: atualizar tabela de recebimentos via reload parcial
        setTimeout(() => { closeModal(); location.reload(); }, 900);
      } else {
        feedback.className = 'alert alert-danger';
        feedback.textContent = j.error || 'Falha ao emitir boleto';
        feedback.style.display = 'block';
      }
    } catch (err) {
      feedback.className = 'alert alert-danger';
      feedback.textContent = 'Erro na requisição: ' + err;
      feedback.style.display = 'block';
    } finally {
      emitBtn.disabled = false;
    }
  });

  // Prorrogar: abrir modal para data e chamar endpoint /financeiro/prorrogar-boleto/{charge_id}/
  qsa('.btn-prorrogar').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      const chargeId = btn.getAttribute('data-charge-id');
      const newDate = prompt("Nova data de vencimento (YYYY-MM-DD):");
      if (!newDate) return;
      try {
        const r = await fetch(`/financeiro/prorrogar-boleto/${chargeId}/`, {
          method: 'POST',
          headers: {'Content-Type':'application/json', 'X-Requested-With':'XMLHttpRequest'},
          body: JSON.stringify({new_date: newDate})
        });
        const j = await r.json();
        if (r.ok && j.success) {
          alert('Vencimento atualizado com sucesso');
          location.reload();
        } else {
          alert('Falha ao atualizar vencimento: ' + (j.error || JSON.stringify(j)));
        }
      } catch (err) {
        alert('Erro ao atualizar vencimento: ' + err);
      }
    });
  });

  // Reemitir: POST /financeiro/reemitir-boleto/{charge_id}/
  qsa('.btn-reemitir').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      const chargeId = btn.getAttribute('data-charge-id');
      const freteId = btn.getAttribute('data-frete-id') || '';
      if (!confirm('Confirma reemissão do boleto? (só possível se cancelado)')) return;
      try {
        const r = await fetch(`/financeiro/reemitir-boleto/${chargeId}/`, {
          method: 'POST',
          headers: {'Content-Type':'application/json', 'X-Requested-With':'XMLHttpRequest'},
          body: JSON.stringify({frete_id: freteId})
        });
        const j = await r.json();
        if (r.ok && j.success) {
          alert('Boleto reemitido com sucesso');
          location.reload();
        } else {
          alert('Falha ao reemitir boleto: ' + (j.error || JSON.stringify(j)));
        }
      } catch (err) {
        alert('Erro ao reemitir boleto: ' + err);
      }
    });
  });

});
