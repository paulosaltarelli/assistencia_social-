(() => {
  "use strict";
  const raiz = document.querySelector("[data-territorial]");
  if (!raiz) return;
  const canvas = raiz.querySelector("canvas");
  const malhaElemento = document.getElementById("territorial-geometria");
  if (!canvas || !malhaElemento) return;
  const ler = id => JSON.parse(document.getElementById(id).textContent);
  let malha, totais, linhas, referencias, mapeados, semPonto;
  try {
    malha = JSON.parse(malhaElemento.textContent);
    totais = ler("territorial-totais");
    linhas = ler("territorial-linhas");
    referencias = ler("territorial-pontos");
    mapeados = ler("territorial-mapeados");
    semPonto = ler("territorial-sem-ponto");
  } catch (_) { return; }
  const contexto = canvas.getContext("2d");
  if (!contexto) return;
  const formato = new Intl.NumberFormat("pt-BR");
  const legenda = raiz.querySelector("[data-territorial-legenda]");
  const cobertura = raiz.querySelector("[data-territorial-cobertura]");
  const selecao = raiz.querySelector("[data-territorial-selecao]");
  const escalaElemento = raiz.querySelector("[data-territorial-escala]");
  let metrica = totais.atendimentos === null ? "demandas" : "atendimentos";
  let referenciaSelecionada = null;
  let alvos = [];
  const normalizar = texto => String(texto).normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase("pt-BR").trim().replace(/\s+/g, " ");
  const poligonos = feature => feature.geometry.type === "Polygon" ? [feature.geometry.coordinates] : feature.geometry.coordinates;
  const pontos = malha.features.flatMap(feature => poligonos(feature).flatMap(poligono => poligono.flat()));
  if (!pontos.length) return;
  const latitudeMedia = pontos.reduce((total, ponto) => total + ponto[1], 0) / pontos.length;
  const correcao = Math.cos(latitudeMedia * Math.PI / 180);
  const limites = pontos.reduce((caixa, [lon, lat]) => ({
    minX: Math.min(caixa.minX, lon * correcao),
    maxX: Math.max(caixa.maxX, lon * correcao),
    minY: Math.min(caixa.minY, -lat),
    maxY: Math.max(caixa.maxY, -lat),
  }), {minX: Infinity, maxX: -Infinity, minY: Infinity, maxY: -Infinity});
  const {minX, maxX, minY, maxY} = limites;
  const regioes = malha.features.filter(feature => feature.properties.tipo !== "municipio");
  const rotulo = () => metrica === "atendimentos" ? "atendimentos no período" : "demandas pendentes agora";
  const cor = () => metrica === "atendimentos" ? "#287ab4" : "#c97518";
  const raio = (valor, maximo) => valor > 0 ? 21 * Math.sqrt(valor / maximo) : 3;

  function valorRegional(feature) {
    const nome = normalizar(feature.properties.nome);
    const campo = feature.properties.tipo === "bairro" ? "bairro" : "territorio";
    const encontrados = linhas.filter(linha => normalizar(linha[campo]) === nome);
    return encontrados.length ? encontrados.reduce((total, linha) => total + (linha[metrica] || 0), 0) : null;
  }

  function atualizarSelecao() {
    raiz.querySelectorAll("[data-referencia]").forEach(botao => {
      const indice = Number(botao.dataset.referencia);
      const item = referencias[indice];
      botao.setAttribute("aria-pressed", String(indice === referenciaSelecionada));
      botao.querySelector("[data-referencia-valor]").textContent = formato.format(item[metrica] || 0);
      botao.setAttribute("aria-label", `${item.nome}, ${formato.format(item[metrica] || 0)} ${rotulo()}`);
    });
    if (selecao && referenciaSelecionada !== null) {
      const item = referencias[referenciaSelecionada];
      const atendimentos = item.atendimentos === null ? "" : `${formato.format(item.atendimentos)} atendimentos no período; `;
      selecao.textContent = `${item.nome}: ${atendimentos}${formato.format(item.demandas)} demandas pendentes agora. Referência amostral de ${formato.format(item.amostra)} coordenadas públicas distintas.`;
    }
  }

  function atualizarEscala(maximo) {
    if (!escalaElemento) return;
    escalaElemento.replaceChildren();
    const valores = [...new Set([1, Math.max(1, Math.round(maximo / 2)), maximo])];
    for (const valor of valores) {
      const item = document.createElement("span");
      const circulo = document.createElement("i");
      circulo.style.width = `${raio(valor, maximo) * 2}px`;
      circulo.style.height = `${raio(valor, maximo) * 2}px`;
      circulo.style.backgroundColor = cor();
      circulo.setAttribute("aria-hidden", "true");
      item.append(circulo, document.createTextNode(formato.format(valor)));
      escalaElemento.append(item);
    }
  }

  function desenhar() {
    const largura = Math.max(250, canvas.clientWidth);
    const altura = Math.max(200, canvas.clientHeight);
    const pixel = window.devicePixelRatio || 1;
    canvas.width = Math.round(largura * pixel);
    canvas.height = Math.round(altura * pixel);
    contexto.setTransform(pixel, 0, 0, pixel, 0, 0);
    contexto.clearRect(0, 0, largura, altura);
    const escala = Math.min((largura - 70) / Math.max(maxX - minX, 0.000001), (altura - 55) / Math.max(maxY - minY, 0.000001));
    const margemX = (largura - (maxX - minX) * escala) / 2;
    const margemY = (altura - (maxY - minY) * escala) / 2;
    const projetar = (lon, lat) => [margemX + (lon * correcao - minX) * escala, margemY + (-lat - minY) * escala];
    const maximoRegional = Math.max(1, ...regioes.map(feature => valorRegional(feature) || 0));
    for (const feature of malha.features) {
      contexto.beginPath();
      for (const poligono of poligonos(feature)) {
        for (const anel of poligono) {
          anel.forEach(([lon, lat], indice) => {
            const [x, y] = projetar(lon, lat);
            if (indice === 0) contexto.moveTo(x, y); else contexto.lineTo(x, y);
          });
          contexto.closePath();
        }
      }
      const municipal = feature.properties.tipo === "municipio";
      const valor = municipal ? null : valorRegional(feature);
      contexto.fillStyle = municipal ? "#dcebe5" : valor === null ? "#e0e7e9" : `rgba(30, 129, 108, ${0.18 + valor / maximoRegional * 0.65})`;
      contexto.fill("evenodd");
      contexto.strokeStyle = municipal ? "#356a66" : "#f8fcfb";
      contexto.lineWidth = municipal ? 1.8 : 1;
      contexto.stroke();
    }
    const maximo = Math.max(1, ...referencias.map(item => item[metrica] || 0));
    alvos = referencias.map((item, indice) => {
      const [x, y] = projetar(item.longitude, item.latitude);
      return {x, y, indice, valor: item[metrica] || 0, raio: raio(item[metrica] || 0, maximo)};
    });
    // Desenha os maiores primeiro para preservar a visibilidade dos menores.
    for (const alvo of [...alvos].sort((a, b) => b.raio - a.raio)) {
      contexto.beginPath();
      contexto.arc(alvo.x, alvo.y, alvo.raio, 0, 2 * Math.PI);
      contexto.fillStyle = alvo.valor === 0 ? "#fff" : cor();
      contexto.globalAlpha = alvo.indice === referenciaSelecionada ? 1 : 0.82;
      contexto.fill();
      contexto.globalAlpha = 1;
      contexto.lineWidth = alvo.indice === referenciaSelecionada ? 3 : 1.4;
      contexto.strokeStyle = alvo.indice === referenciaSelecionada ? "#193c54" : "#fff";
      contexto.stroke();
      if (alvo.raio >= 8) {
        contexto.fillStyle = "#fff";
        contexto.font = "600 11px system-ui";
        contexto.textAlign = "center";
        contexto.textBaseline = "middle";
        contexto.fillText(formato.format(alvo.valor), alvo.x, alvo.y);
      }
    }
    legenda.textContent = `${formato.format(totais[metrica] || 0)} ${rotulo()}`;
    cobertura.textContent = referencias.length ? `${formato.format(mapeados[metrica] || 0)} registros associados às referências; ${formato.format(semPonto[metrica] || 0)} registros somente na tabela.` : "Distribuição detalhada disponível na tabela.";
    canvas.setAttribute("aria-label", `${raiz.querySelector("figcaption strong").textContent}. ${legenda.textContent}. ${referencias.length} referências amostrais de localidades. Os mesmos indicadores estão nos botões de localidades e na tabela.`);
    atualizarSelecao();
    atualizarEscala(maximo);
  }

  raiz.querySelectorAll("[data-metrica]").forEach(botao => {
    botao.addEventListener("click", () => {
      metrica = botao.dataset.metrica;
      raiz.querySelectorAll("[data-metrica]").forEach(outro => outro.setAttribute("aria-pressed", String(outro === botao)));
      desenhar();
    });
  });
  raiz.querySelectorAll("[data-referencia]").forEach(botao => {
    botao.addEventListener("click", () => {
      referenciaSelecionada = Number(botao.dataset.referencia);
      desenhar();
    });
  });
  canvas.addEventListener("click", event => {
    const caixa = canvas.getBoundingClientRect();
    const x = event.clientX - caixa.left, y = event.clientY - caixa.top;
    const candidato = alvos.map(alvo => ({...alvo, distancia: Math.hypot(x - alvo.x, y - alvo.y)}))
      .filter(alvo => alvo.distancia <= Math.max(8, alvo.raio + 3)).sort((a, b) => a.distancia - b.distancia)[0];
    if (candidato) {
      referenciaSelecionada = candidato.indice;
      desenhar();
    }
  });
  if (window.ResizeObserver) new ResizeObserver(desenhar).observe(canvas); else window.addEventListener("resize", desenhar);
  desenhar();
})();
