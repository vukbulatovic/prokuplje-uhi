// ==========================
// MAPA
// ==========================
var map = L.map('map').setView([43.2333, 21.5833], 13);

L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 19,
  attribution: '© OpenStreetMap contributors'
}).addTo(map);

// ==========================
// GLOBALNE VARIJABLE
// ==========================
var tileLayers = { lst: null, ndvi: null, uhi: null, zones: null };
var zoneChart  = null;
var lstChart   = null;

// ==========================
// UI ELEMENTI
// ==========================
var cloudSlider = document.getElementById('cloud-slider');
var cloudVal    = document.getElementById('cloud-val');
var runBtn      = document.getElementById('run-btn');
var status      = document.getElementById('status');
var statsPanel  = document.getElementById('stats-panel');
var lstPanel    = document.getElementById('lst-panel');
var layerToggles = document.getElementById('layer-toggles');

cloudSlider.addEventListener('input', function() {
  cloudVal.textContent = this.value;
});

document.getElementById('lst-close').addEventListener('click', function() {
  lstPanel.style.display = 'none';
});

// ==========================
// TOGGLE SLOJEVI
// ==========================
function setupToggles() {
  document.getElementById('tog-zones').addEventListener('change', function() {
    if (tileLayers.zones) {
      this.checked ? map.addLayer(tileLayers.zones) : map.removeLayer(tileLayers.zones);
    }
  });
  document.getElementById('tog-lst').addEventListener('change', function() {
    if (tileLayers.lst) {
      this.checked ? map.addLayer(tileLayers.lst) : map.removeLayer(tileLayers.lst);
    }
  });
  document.getElementById('tog-uhi').addEventListener('change', function() {
    if (tileLayers.uhi) {
      this.checked ? map.addLayer(tileLayers.uhi) : map.removeLayer(tileLayers.uhi);
    }
  });
  document.getElementById('tog-ndvi').addEventListener('change', function() {
    if (tileLayers.ndvi) {
      this.checked ? map.addLayer(tileLayers.ndvi) : map.removeLayer(tileLayers.ndvi);
    }
  });
}
setupToggles();

// ==========================
// GRAFIK ZONA
// ==========================
function renderZoneChart(zoneStats) {
  var labels = zoneStats.map(function(z) { return z.label; });
  var areas  = zoneStats.map(function(z) { return z.area; });
  var colors = zoneStats.map(function(z) { return z.color; });
  var annots = zoneStats.map(function(z) { return z.lst ? z.lst + ' °C' : ''; });

  if (zoneChart) zoneChart.destroy();

  zoneChart = new Chart(document.getElementById('zone-chart'), {
    type: 'bar',
    data: {
      labels:   labels,
      datasets: [{
        data:            areas,
        backgroundColor: colors,
        borderWidth:     0
      }]
    },
    options: {
      responsive: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            afterLabel: function(ctx) {
              return 'LST: ' + annots[ctx.dataIndex];
            }
          }
        }
      },
      scales: {
        y: {
          title: { display: true, text: 'Površina (ha)', font: { size: 11 } },
          beginAtZero: true
        },
        x: {
          ticks: { font: { size: 9 }, maxRotation: 35 }
        }
      }
    }
  });
}

// ==========================
// GLAVNA ANALIZA
// ==========================
runBtn.addEventListener('click', function() {
  var start = document.getElementById('start-date').value;
  var end   = document.getElementById('end-date').value;
  var cloud = parseInt(cloudSlider.value);

  runBtn.disabled    = true;
  runBtn.textContent = '⏳ Analiza u toku...';
  status.textContent = 'Status: učitavanje podataka...';
  statsPanel.style.display  = 'none';
  lstPanel.style.display    = 'none';
  layerToggles.style.display = 'none';

  // Ukloni stare slojeve
  Object.values(tileLayers).forEach(function(l) {
    if (l) map.removeLayer(l);
  });
  tileLayers = { lst: null, ndvi: null, uhi: null, zones: null };

  fetch('/analyze', {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify({ start: start, end: end, cloud: cloud })
  })
  .then(function(res) { return res.json(); })
  .then(function(data) {
    if (!data.success) {
      status.textContent = 'GREŠKA: ' + data.error;
      runBtn.disabled    = false;
      runBtn.textContent = '▶ Pokreni analizu';
      return;
    }

    // Dodaj tile slojeve
    tileLayers.lst = L.tileLayer(data.tiles.lst,   { opacity: 0.7 });
    tileLayers.ndvi = L.tileLayer(data.tiles.ndvi, { opacity: 0.7 });
    tileLayers.uhi  = L.tileLayer(data.tiles.uhi,  { opacity: 0.7 });
    tileLayers.zones = L.tileLayer(data.tiles.zones, { opacity: 0.8 });

    // Podrazumevano prikaži samo zone
    map.addLayer(tileLayers.zones);

    // Reset checkbox-ovi
    document.getElementById('tog-zones').checked = true;
    document.getElementById('tog-lst').checked   = false;
    document.getElementById('tog-uhi').checked   = false;
    document.getElementById('tog-ndvi').checked  = false;

    // Prikaži statistike
    renderZoneChart(data.zone_stats);
    statsPanel.style.display   = 'block';
    layerToggles.style.display = 'block';

    status.textContent = 'Status: ✅ analiza završena';
    runBtn.disabled    = false;
    runBtn.textContent = '▶ Pokreni analizu';
  })
  .catch(function(err) {
    status.textContent = 'GREŠKA: ' + err.message;
    runBtn.disabled    = false;
    runBtn.textContent = '▶ Pokreni analizu';
  });
});

// ==========================
// KLIK NA MAPU – LST GRAFIK
// ==========================
map.on('click', function(e) {
  lstPanel.style.display = 'block';
  document.getElementById('lst-info').textContent = 'Učitavam...';

  var canvas = document.getElementById('lst-chart');
  canvas.style.display = 'none';

  fetch('/lst_series', {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify({ lat: e.latlng.lat, lon: e.latlng.lng })
  })
  .then(function(res) { return res.json(); })
  .then(function(data) {
    if (!data.success) {
      document.getElementById('lst-info').textContent = 'Nema podataka za ovu lokaciju.';
      return;
    }

    document.getElementById('lst-info').textContent = '';
    canvas.style.display = 'block';

    if (lstChart) lstChart.destroy();

    lstChart = new Chart(canvas, {
      type: 'line',
      data: {
        labels:   data.dates,
        datasets: [{
          label:           'LST (°C)',
          data:            data.values,
          borderColor:     '#c0392b',
          backgroundColor: 'rgba(192,57,43,0.1)',
          borderWidth:     2,
          pointRadius:     4,
          tension:         0.3
        }]
      },
      options: {
        responsive: false,
        plugins: { legend: { display: false } },
        scales: {
          y: { title: { display: true, text: '°C', font: { size: 11 } } },
          x: { ticks: { font: { size: 10 }, maxRotation: 35 } }
        }
      }
    });
  })
  .catch(function() {
    document.getElementById('lst-info').textContent = 'Greška pri učitavanju.';
  });
});