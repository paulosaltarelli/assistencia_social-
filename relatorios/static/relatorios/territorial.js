(function () {
  'use strict';
  const root = document.querySelector('[data-territorial]');
  if (!root) return;
  const element = root.querySelector('[data-territorial-map]');
  if (!element) return;
  const read = id => JSON.parse(document.getElementById(id).textContent);
  const status = root.querySelector('[data-territorial-tiles]');
  if (!window.L) {
    status.textContent = 'O mapa interativo não pôde ser carregado. Consulte os valores na tabela territorial.';
    return;
  }
  let geometry, references, totals, mapped, unmapped;
  try {
    geometry = read('territorial-geometria');
    references = read('territorial-pontos');
    totals = read('territorial-totais');
    mapped = read('territorial-mapeados');
    unmapped = read('territorial-sem-ponto');
  } catch (error) {
    status.textContent = 'Os dados do mapa não estão disponíveis. Consulte a tabela territorial.';
    return;
  }
  const L = window.L;
  const format = new Intl.NumberFormat('pt-BR');
  const selection = root.querySelector('[data-territorial-selecao]');
  let metric = totals.atendimentos === null ? 'demandas' : 'atendimentos';
  let selected = null;
  const map = L.map(element, { zoomControl: false, scrollWheelZoom: false, attributionControl: true, maxBoundsViscosity: 1, maxZoom: 19 });
  L.control.zoom({ zoomInTitle: 'Aproximar', zoomOutTitle: 'Afastar' }).addTo(map);
  const streets = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap contributors</a>',
    referrerPolicy: 'strict-origin-when-cross-origin'
  });
  const border = L.geoJSON(geometry, { style: { color: '#f7c956', weight: 2.5, fillColor: '#f7c956', fillOpacity: 0.04 } }).addTo(map);
  const points = L.layerGroup().addTo(map);
  const bounds = border.getBounds();
  if (!bounds.isValid()) {
    map.remove();
    status.textContent = 'Contorno municipal indisponível. Consulte a tabela territorial.';
    return;
  }
  const fit = () => map.fitBounds(bounds, { padding: [28, 28], maxZoom: 16, animate: false });
  fit();
  const bases = { 'Ruas · OpenStreetMap': streets };
  let localSatellite = null;
  let imageBounds = null;
  const localSource = document.getElementById('territorial-satelite');
  const localImage = root.querySelector('[data-territorial-imagem]');
  if (localSource && localImage) {
    try {
      const data = JSON.parse(localSource.textContent);
      const box = data.bounds;
      if (Array.isArray(box) && box.length === 4 && box.every(Number.isFinite)) {
        const credit = document.createElement('span');
        credit.textContent = data.credito || data.fonte || 'Imagem de satélite com fonte identificada';
        imageBounds = L.latLngBounds([[box[1], box[0]], [box[3], box[2]]]);
        localSatellite = L.imageOverlay(localImage.dataset.territorialImagem, imageBounds, { attribution: credit.outerHTML });
        map.setMaxBounds(imageBounds);
        map.setMinZoom(map.getBoundsZoom(imageBounds, true));
        const date = String(data.data_captura || 'não informada').slice(0, 10);
        const readableDate = /^\d{4}-\d{2}-\d{2}$/.test(date) ? date.split('-').reverse().join('/') : date;
        const resolution = data.resolucao_origem_metros ? ' · resolução de origem ' + data.resolucao_origem_metros + ' m' : '';
        root.querySelector('[data-territorial-imagem-fonte]').textContent = 'Imagem de referência · ' + readableDate + resolution + ' · ' + (data.fonte || 'Fonte identificada na atribuição');
        bases['Satélite · imagem de referência'] = localSatellite;
      }
    } catch (error) { /* A imagem opcional não interfere nas camadas principais. */ }
  }
  const localityNames = L.layerGroup().addTo(map);
  const roadsLayer = L.layerGroup();
  const overlays = { 'Contorno municipal': border, 'Referências das localidades': points, 'Nomes das localidades': localityNames };
  const control = L.control.layers(bases, overlays, { position: 'topright', collapsed: true }).addTo(map);
  if (localSatellite) localSatellite.addTo(map); else {
    streets.addTo(map);
    status.textContent = 'Imagem de satélite local ainda não disponível para este município. Exibindo Ruas; os indicadores continuam nas referências e na tabela.';
  }
  function addRoads(data) {
    if (data.type !== 'FeatureCollection' || !Array.isArray(data.features)) return;
    const roadNames = new Map();
    L.geoJSON(data, {
      style: { color: '#ffffff', weight: 2, opacity: 0.8 },
      onEachFeature: (feature, layer) => {
        const name = feature.properties && feature.properties.nome;
        if (!name) return;
        const label = document.createElement('span');
        label.textContent = name;
        layer.bindTooltip(label, { sticky: true });
        const segments = feature.geometry.type === 'LineString' ? [feature.geometry.coordinates] : feature.geometry.type === 'MultiLineString' ? feature.geometry.coordinates : [];
        segments.forEach(segment => {
          let length = 0;
          for (let i = 1; i < segment.length; i += 1) {
            length += L.latLng(segment[i][1], segment[i][0]).distanceTo(L.latLng(segment[i - 1][1], segment[i - 1][0]));
          }
          const previous = roadNames.get(name);
          if (segment.length && (!previous || length > previous.length)) {
            const middle = segment[Math.floor(segment.length / 2)];
            roadNames.set(name, { name, length, position: L.latLng(middle[1], middle[0]) });
          }
        });
      }
    }).addTo(roadsLayer);
    const nameLayer = L.layerGroup().addTo(roadsLayer);
    function updateRoadLabels() {
      nameLayer.clearLayers();
      if (map.getZoom() < 15 || !map.hasLayer(roadsLayer)) return;
      const occupied = [];
      const maximum = Math.min(22, Math.max(4, Math.floor(map.getSize().x * map.getSize().y / 14000)));
      [...roadNames.values()].sort((a, b) => b.length - a.length).forEach(road => {
        if (road.length < 60 || occupied.length >= maximum || !map.getBounds().contains(road.position)) return;
        const point = map.latLngToContainerPoint(road.position);
        if (occupied.some(other => point.distanceTo(other) < 120)) return;
        occupied.push(point);
        const label = document.createElement('span');
        label.className = 'terr-street-name';
        label.textContent = road.name;
        L.marker(road.position, {
          icon: L.divIcon({ className: 'terr-street-marker', html: label.outerHTML, iconSize: [150, 18], iconAnchor: [75, 9] }),
          interactive: false, keyboard: false, zIndexOffset: -200
        }).addTo(nameLayer);
      });
    }
    roadsLayer.addTo(map);
    map.on('zoomend moveend overlayadd', updateRoadLabels);
    updateRoadLabels();
    control.addOverlay(roadsLayer, 'Vias e nomes de ruas');
    map.attributionControl.addAttribution('Vias &copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap contributors</a> · ODbL');
  }
  const roadData = document.getElementById('territorial-vias');
  const roadUrl = root.querySelector('[data-territorial-vias]');
  if (roadData) {
    try { addRoads(JSON.parse(roadData.textContent)); } catch (error) { /* A camada de vias é opcional. */ }
  } else if (roadUrl) {
    try {
      const url = new URL(roadUrl.dataset.territorialVias, window.location.href);
      if (url.origin === window.location.origin) {
        fetch(url.href, { credentials: 'same-origin' }).then(response => {
          if (!response.ok) throw new Error('Vias indisponíveis');
          return response.json();
        }).then(addRoads).catch(() => {
          status.textContent = 'A sobreposição de vias não pôde ser carregada. As referências e o contorno continuam disponíveis.';
        });
      }
    } catch (error) { /* Um endereço de vias inválido não interrompe os indicadores. */ }
  }
  const layerHeading = document.createElement('div');
  layerHeading.className = 'terr-layers-heading';
  layerHeading.textContent = 'Camadas';
  control.getContainer().querySelector('.leaflet-control-layers-list').prepend(layerHeading);
  const layerButton = control.getContainer().querySelector('.leaflet-control-layers-toggle');
  if (layerButton) {
    layerButton.title = 'Escolher mapa e camadas';
    layerButton.append(document.createTextNode('Camadas'));
    layerButton.setAttribute('aria-label', 'Escolher Satélite ou Ruas e ativar camadas');
  }
  let tileFailure = false;
  streets.on('tileerror', () => {
    tileFailure = true;
    status.textContent = 'A camada Ruas está indisponível ou parcialmente carregada. A imagem local, o contorno e os indicadores continuam disponíveis.';
  });
  streets.on('load', () => { if (!tileFailure && map.hasLayer(streets)) status.textContent = ''; });
  if (localSatellite) {
    localSatellite.on('error', () => {
      status.textContent = 'A imagem local não pôde ser carregada. Selecione Ruas ou consulte a tabela territorial.';
    });
  }
  map.on('baselayerchange', () => { tileFailure = false; status.textContent = ''; });
  const markers = [];
  const names = [];
  const label = () => metric === 'atendimentos' ? 'atendimentos no período' : 'demandas pendentes agora';

  function popup(reference) {
    const content = document.createElement('div');
    content.className = 'terr-popup';
    const title = document.createElement('h3');
    title.textContent = reference.nome;
    content.append(title);
    const data = document.createElement('dl');
    const rows = [];
    if (reference.atendimentos !== null) rows.push(['Atendimentos no período', reference.atendimentos]);
    rows.push(['Demandas pendentes agora', reference.demandas]);
    rows.forEach(([name, value]) => {
      const dt = document.createElement('dt');
      dt.textContent = name;
      const dd = document.createElement('dd');
      dd.textContent = format.format(value || 0);
      data.append(dt, dd);
    });
    const note = document.createElement('p');
    note.textContent = 'Referência amostral da localidade, derivada de ' + format.format(reference.amostra) + ' coordenadas públicas distintas. Não representa um domicílio.';
    content.append(data, note);
    return content;
  }

  function updateSelection() {
    root.querySelectorAll('[data-referencia]').forEach(button => {
      const index = Number(button.dataset.referencia);
      const reference = references[index];
      if (!reference) return;
      button.setAttribute('aria-pressed', String(index === selected));
      button.querySelector('[data-referencia-valor]').textContent = format.format(reference[metric] || 0);
      button.setAttribute('aria-label', reference.nome + ', ' + format.format(reference[metric] || 0) + ' ' + label());
    });
    if (selection && selected !== null) {
      const reference = references[selected];
      selection.textContent = reference.nome + ': ' + (reference.atendimentos === null ? '' : format.format(reference.atendimentos) + ' atendimentos no período; ') + format.format(reference.demandas || 0) + ' demandas pendentes agora.';
    }
  }

  function choose(index) {
    if (!markers[index]) return;
    selected = index;
    if (!map.hasLayer(points)) points.addTo(map);
    const position = markers[index].getLatLng();
    map.setView(position, Math.max(map.getZoom(), 15), { animate: false });
    markers[index].openPopup();
    updateSelection();
  }

  function draw() {
    points.clearLayers();
    markers.length = 0;
    names.forEach(name => localityNames.removeLayer(name));
    names.length = 0;
    const maximum = Math.max(1, ...references.map(item => Number(item[metric]) || 0));
    references.forEach((reference, index) => {
      const value = Number(reference[metric]) || 0;
      const size = 28 + 18 * Math.sqrt(value / maximum);
      const iconContent = document.createElement('span');
      iconContent.className = 'terr-marker-value' + (metric === 'demandas' ? ' terr-marker-demand' : '') + (value === 0 ? ' terr-marker-zero' : '');
      iconContent.textContent = format.format(value);
      const marker = L.marker([reference.latitude, reference.longitude], {
        icon: L.divIcon({ className: 'terr-marker', html: iconContent.outerHTML, iconSize: [size, size], iconAnchor: [size / 2, size / 2] }),
        title: reference.nome + ' · ' + format.format(value) + ' ' + label(),
        alt: reference.nome + ' · ' + format.format(value),
        keyboard: true
      }).addTo(points);
      const tooltip = document.createElement('span');
      tooltip.textContent = reference.nome;
      marker.bindTooltip(tooltip, { direction: 'top', offset: [0, -size / 2] });
      const localName = document.createElement('span');
      localName.className = 'terr-locality-name';
      localName.textContent = reference.nome;
      const name = L.marker([reference.latitude, reference.longitude], {
        icon: L.divIcon({ className: 'terr-name-marker', html: localName.outerHTML, iconSize: [150, 20], iconAnchor: [75, -size / 2 - 3] }),
        interactive: false, keyboard: false, zIndexOffset: -100
      }).addTo(localityNames);
      names.push(name);
      marker.bindPopup(popup(reference), { maxWidth: Math.max(170, Math.min(270, element.clientWidth - 65)), autoPanPadding: [15, 15] });
      marker.on('click', () => { selected = index; updateSelection(); });
      markers.push(marker);
    });
    root.querySelector('[data-territorial-legenda]').textContent = format.format(totals[metric] || 0) + ' ' + label();
    root.querySelector('[data-territorial-cobertura]').textContent = format.format(mapped[metric] || 0) + ' registros associados às referências; ' + format.format(unmapped[metric] || 0) + ' registros somente na tabela.';
    const scale = root.querySelector('[data-territorial-escala]');
    if (scale) scale.textContent = 'O número em cada ponto corresponde ao indicador selecionado. Pontos com zero permanecem disponíveis para consulta.';
    updateSelection();
  }
  root.querySelectorAll('[data-metrica]').forEach(button => {
    button.addEventListener('click', () => {
      metric = button.dataset.metrica;
      root.querySelectorAll('[data-metrica]').forEach(item => item.setAttribute('aria-pressed', String(item === button)));
      draw();
    });
  });
  root.querySelectorAll('[data-referencia]').forEach(button => button.addEventListener('click', () => choose(Number(button.dataset.referencia))));
  root.querySelector('[data-territorial-ajustar]').addEventListener('click', fit);
  if (window.ResizeObserver) new ResizeObserver(() => {
    map.invalidateSize({ pan: false });
    markers.forEach(marker => { marker.getPopup().options.maxWidth = Math.max(170, Math.min(270, element.clientWidth - 65)); });
    if (imageBounds) map.setMinZoom(map.getBoundsZoom(imageBounds, true));
  }).observe(element);
  draw();
})();
