(() => {
  const seletor = document.getElementById('id_endereco_catalogo');
  const dados = document.getElementById('pares-de-endereco');
  if (!seletor || !dados) return;
  const pares = JSON.parse(dados.textContent);
  const rua = document.getElementById('id_endereco');
  const bairro = document.getElementById('id_bairro');
  const cidade = document.getElementById('id_cidade');
  function aplicar() {
    const par = pares[seletor.value];
    if (par) {
      rua.value = par.logradouro;
      bairro.value = par.bairro;
      cidade.value = 'Santa Cruz de Minas';
    }
  }
  seletor.addEventListener('change', aplicar);
  for (const campo of [rua, bairro, cidade]) {
    campo.addEventListener('input', () => { seletor.value = ''; });
  }
  aplicar();
})();
