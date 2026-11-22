(() => {
  const normalizar = valor => valor.toLocaleLowerCase('pt-BR').normalize('NFD').replace(/[\u0300-\u036f]/g, '');
  const busca = document.querySelector('[data-ca-busca]');
  const situacao = document.querySelector('[data-ca-status]');
  const linhas = [...document.querySelectorAll('[data-ca-profissional]')];
  if (busca && situacao) {
    const filtrar = () => {
      const termo = normalizar(busca.value.trim());
      let total = 0;
      linhas.forEach(linha => {
        const corresponde = normalizar(linha.dataset.caTexto).includes(termo) && (!situacao.value || linha.dataset.caAtivo === situacao.value);
        linha.hidden = !corresponde;
        if (corresponde) total += 1;
      });
      document.querySelector('[data-ca-contagem]').textContent = total + (total === 1 ? ' profissional' : ' profissionais');
      document.querySelector('[data-ca-vazio]').hidden = total > 0 || linhas.length === 0;
    };
    busca.addEventListener('input', filtrar);
    situacao.addEventListener('change', filtrar);
    document.querySelector('[data-ca-limpar]').addEventListener('click', () => { busca.value = ''; situacao.value = ''; filtrar(); busca.focus(); });
  }
  const matrizElement = document.getElementById('ca-matriz-perfis');
  const perfil = document.querySelector('[data-ca-perfil]');
  if (matrizElement && perfil) {
    const matriz = JSON.parse(matrizElement.textContent);
    const atualizar = () => {
      const codigos = matriz[perfil.value] || [];
      document.querySelectorAll('[data-ca-permissao]').forEach(linha => {
        const herdado = linha.querySelector('[data-ca-herdada]');
        const incluido = codigos.includes(linha.dataset.caPermissao);
        herdado.textContent = incluido ? 'Incluído' : 'Sem acesso';
        herdado.classList.toggle('ca-included', incluido);
      });
    };
    perfil.addEventListener('change', atualizar);
    atualizar();
  }
  document.querySelectorAll('[data-ca-permissao]').forEach(linha => {
    const permitir = linha.querySelector('input[name=permitir][type=checkbox]');
    const negar = linha.querySelector('input[name=negar][type=checkbox]');
    if (!permitir || !negar) return;
    permitir.addEventListener('change', () => { if (permitir.checked) negar.checked = false; });
    negar.addEventListener('change', () => { if (negar.checked) permitir.checked = false; });
  });
  const copiar = document.querySelector('[data-ca-copiar]');
  if (copiar) copiar.addEventListener('click', async () => {
    const campo = document.getElementById('link-pessoal');
    const retorno = document.querySelector('[data-ca-copiado]');
    try {
      await navigator.clipboard.writeText(campo.value);
      retorno.textContent = 'Link copiado.';
    } catch (erro) {
      campo.focus();
      campo.select();
      retorno.textContent = 'Selecione e copie o link no campo acima.';
    }
  });
})();
