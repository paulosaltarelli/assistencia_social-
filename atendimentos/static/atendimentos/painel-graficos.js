/* As tabelas de cada gráfico permanecem disponíveis sem JavaScript. */
(function () {
  'use strict';

  const colors = ['#2368aa', '#138875', '#b67b25', '#6d64ab', '#428d9d', '#a96078'];
  const numberFormat = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 2 });
  const moneyFormat = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' });
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  document.querySelectorAll('.social-chart').forEach(function (card) {
    const source = card.querySelector('script[type="application/json"]');
    const canvas = card.querySelector('canvas');
    const empty = card.querySelector('.social-chart-empty');
    let rows;
    try {
      rows = JSON.parse(source.textContent);
    } catch (error) {
      card.querySelector('details').open = true;
      canvas.hidden = true;
      return;
    }
    const labels = rows.map(function (row) { return String(row[0]); });
    const values = rows.map(function (row) { return Number(row[1]); });
    const monetary = card.querySelector('.social-chart-unit').textContent.includes('R$');
    const format = monetary ? moneyFormat : numberFormat;
    if (values.every(Number.isFinite)) {
      const total = values.reduce(function (sum, value) { return sum + value; }, 0);
      card.querySelector('.social-chart-total').textContent = format.format(total);
    }
    if (!rows.length) {
      canvas.hidden = true;
      empty.hidden = false;
      return;
    }
    if (!window.Chart || !values.every(Number.isFinite)) {
      card.querySelector('details').open = true;
      canvas.hidden = true;
      return;
    }
    const monthly = labels.every(function (label) { return /^\d{2}\/\d{4}$/.test(label); });
    const horizontal = !monthly;
    const description = labels.map(function (label, index) { return label + ': ' + format.format(values[index]); }).join('; ');
    canvas.setAttribute('aria-label', card.querySelector('h3').textContent + '. ' + description);
    // Políticas de acesso e agregação são aplicadas no servidor. O navegador só recebe a série autorizada.
    new window.Chart(canvas, {
      type: monthly ? 'line' : 'bar',
      data: {
        labels: labels,
        datasets: [{
          data: values,
          label: card.querySelector('.social-chart-unit').textContent,
          borderColor: colors[0],
          backgroundColor: monthly ? 'rgba(35, 104, 170, 0.10)' : colors,
          borderWidth: monthly ? 2.5 : 0,
          borderRadius: 4,
          maxBarThickness: 24,
          tension: 0.25,
          fill: monthly,
          pointRadius: 3,
          pointHoverRadius: 5,
          pointBackgroundColor: '#ffffff',
          pointBorderWidth: 2
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: reducedMotion ? false : { duration: 250 },
        indexAxis: horizontal ? 'y' : 'x',
        interaction: { intersect: false, mode: 'index' },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: '#17324d',
            padding: 12,
            displayColors: false,
            callbacks: { label: function (item) { return format.format(horizontal ? item.parsed.x : item.parsed.y); } }
          }
        },
        scales: {
          x: {
            beginAtZero: horizontal,
            border: { display: false },
            grid: { display: horizontal, color: '#e8eef4', drawTicks: false },
            ticks: {
              color: '#62758a', padding: 9, maxRotation: 0, autoSkip: true,
              font: { size: 10, family: 'Inter, system-ui, sans-serif' },
              callback: horizontal ? function (value) { return format.format(value); } : function (value) { return this.getLabelForValue(value); }
            }
          },
          y: {
            beginAtZero: true,
            border: { display: false },
            grid: { display: !horizontal, color: '#e8eef4', drawTicks: false },
            ticks: {
              color: '#62758a', padding: 9,
              font: { size: 10, family: 'Inter, system-ui, sans-serif' },
              precision: monetary ? undefined : 0,
              callback: horizontal ? function (value) {
                const label = this.getLabelForValue(value);
                return label.length > 25 ? label.slice(0, 24) + '…' : label;
              } : function (value) { return format.format(value); }
            }
          }
        }
      }
    });
  });
})();
