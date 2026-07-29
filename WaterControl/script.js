const parameters = [
	{ id: 'uep', name: 'УЭП', unit: 'мкСм/см', min: 0, max: 3000, warn: 2000 },
	{ id: 'o2', name: 'O₂', unit: 'мг/л', min: 0, max: 20, warn: 15, convert: v => v / 1000 }, // мкг/л → мг/л
	{ id: 'na', name: 'Na⁺', unit: 'мг/л', min: 0, max: 100, warn: 80, convert: v => v / 1000 }, // мкг/л → мг/л
	{ id: 'ph', name: 'pH', unit: '', min: 0, max: 14, warn: 9, convert: v => v },
	{ id: 'no3', name: 'NO₃⁻', unit: 'мг/л', min: 0, max: 100, warn: 50, convert: v => v },
	{ id: 'no2', name: 'NO₂⁻', unit: 'мг/л', min: 0, max: 2, warn: 0.5, convert: v => v },
	{ id: 'nh4', name: 'NH₄⁺', unit: 'мг/л', min: 0, max: 10, warn: 2.0, convert: v => v / 1000 }, // мкг/л → мг/л
	{ id: 'temp', name: 'T°', unit: '°C', min: 0, max: 50, warn: 40, convert: v => v },
]

let charts = {}
let history = { inlet: {}, outlet: {}, labels: [] }
let selectedParam = { inlet: 'uep', outlet: 'uep' } // по умолчанию УЭП

// Инициализация
function init() {
	;['inlet', 'outlet'].forEach(point => {
		const container = document.getElementById(`${point}-params`)
		container.innerHTML = ''

		parameters.forEach(p => {
			// Получаем значение для отображения в боксе
			const displayId = p.id
			container.innerHTML += `
                <div class="param-item" id="${point}-${p.id}-box" onclick="selectParam('${point}', '${p.id}')">
                    <div class="param-header">
                        <span class="param-label">${p.name}</span>
                        <span id="${point}-${p.id}-status" class="param-status-text">—</span>
                    </div>
                    <div>
                        <span class="param-value" id="${point}-${p.id}-val">—</span>
                        <span class="unit">${p.unit}</span>
                    </div>
                </div>
            `
		})

		setupChart(point)
	})

	setInterval(fetchRealData, 2000)
	fetchRealData()

	addLog('✅ Система запущена. Получение данных от АТОН-801...', 'info')
}

// Получение реальных данных
async function fetchRealData() {
	try {
		const res = await fetch('http://127.0.0.1:5000/api/data')
		const data = await res.json()

		const now = new Date().toLocaleTimeString()
		history.labels.push(now)
		if (history.labels.length > 30) history.labels.shift()

		parameters.forEach(param => {
			;['inlet', 'outlet'].forEach(point => {
				// Получаем сырое значение от бекенда
				let rawValue = data[point]?.[param.id]
				if (rawValue === undefined || rawValue === null) {
					rawValue = 0
				}

				// Применяем преобразование если есть (мкг/л → мг/л)
				let value = param.convert ? param.convert(Number(rawValue)) : Number(rawValue)

				// Если значение слишком большое для O2, Na, NH4 - возможно ошибка парсинга
				if (param.id === 'o2' && value > 20) {
					value = Number(rawValue) / 1000 // пробуем пересчитать
				}

				if (!history[point][param.id]) history[point][param.id] = []
				history[point][param.id].push(value)
				if (history[point][param.id].length > 30) history[point][param.id].shift()

				updateUI(point, param, value)
			})
		})

		if (data.last_update_str) {
			document.getElementById('inlet-status').textContent = `Обновлено: ${data.last_update_str}`
			document.getElementById('outlet-status').textContent = `Обновлено: ${data.last_update_str}`
		}

		refreshChartDisplay('inlet')
		refreshChartDisplay('outlet')
	} catch (e) {
		console.error(e)
		addLog('⚠️ Нет связи с сервером', 'red')
	}
}

function updateUI(point, param, value) {
	const valEl = document.getElementById(`${point}-${param.id}-val`)
	const statusEl = document.getElementById(`${point}-${param.id}-status`)
	const boxEl = document.getElementById(`${point}-${param.id}-box`)

	if (valEl) {
		if (param.id === 'temp') valEl.textContent = value.toFixed(1)
		else if (param.id === 'ph') valEl.textContent = value.toFixed(2)
		else if (param.id === 'uep') valEl.textContent = value.toFixed(0)
		else valEl.textContent = value.toFixed(2)
	}

	if (statusEl && boxEl) {
		let status = 'НОРМА'
		let color = 'var(--green)'

		if (value > param.warn) {
			status = 'ПРЕДУПРЕЖДЕНИЕ'
			color = 'var(--yellow)'
		}
		if (value > param.max) {
			status = 'АВАРИЯ'
			color = 'var(--red)'
		}

		statusEl.textContent = status
		statusEl.style.color = color
		boxEl.style.borderLeftColor = color
	}
}

function setupChart(point) {
	const ctx = document.getElementById(`chart-${point}`).getContext('2d')
	charts[point] = new Chart(ctx, {
		type: 'line',
		data: {
			labels: [],
			datasets: [
				{
					label: '',
					data: [],
					borderColor: '#3498db',
					backgroundColor: 'rgba(52, 152, 219, 0.1)',
					tension: 0.3,
					fill: true,
				},
			],
		},
		options: {
			responsive: true,
			maintainAspectRatio: false,
			scales: {
				y: {
					beginAtZero: true,
					grid: { color: 'rgba(255,255,255,0.1)' },
				},
				x: {
					grid: { display: false },
				},
			},
			plugins: {
				legend: {
					labels: { color: '#e0e0e0' },
				},
			},
		},
	})
}

function refreshChartDisplay(point) {
	const paramId = selectedParam[point] || 'uep'
	const param = parameters.find(p => p.id === paramId)
	if (!param || !charts[point]) return

	const data = history[point][paramId] || []

	// Если данных мало, заполняем нулями
	while (data.length < history.labels.length) {
		data.unshift(0)
	}

	charts[point].data.labels = history.labels
	charts[point].data.datasets[0].data = data.slice(-30)
	charts[point].data.datasets[0].label = param.name + ' ' + param.unit

	// Динамический диапазон для графика
	if (param.min !== undefined && param.max !== undefined) {
		charts[point].options.scales.y.min = param.min
		charts[point].options.scales.y.max = param.max
	}

	// Цвет линии в зависимости от параметра
	const colors = {
		uep: '#3498db',
		o2: '#2ecc71',
		na: '#e67e22',
		ph: '#9b59b6',
		no3: '#1abc9c',
		no2: '#e74c3c',
		nh4: '#f1c40f',
		temp: '#e74c3c',
	}
	charts[point].data.datasets[0].borderColor = colors[paramId] || '#3498db'
	charts[point].data.datasets[0].backgroundColor = colors[paramId] + '33' || 'rgba(52, 152, 219, 0.1)'

	charts[point].update()
}

function selectParam(point, paramId) {
	console.log(`Выбран параметр: ${paramId} для ${point}`)
	selectedParam[point] = paramId
	refreshChartDisplay(point)

	// Подсветка выбранного бокса
	document.querySelectorAll(`#${point}-params .param-item`).forEach(el => {
		el.style.borderLeftColor = 'transparent'
	})
	const box = document.getElementById(`${point}-${paramId}-box`)
	if (box) {
		box.style.borderLeftColor = '#3498db'
	}
}

function addLog(msg, type = 'info') {
	const log = document.getElementById('log-list')
	const entry = document.createElement('div')
	entry.className = `log-entry log-${type}`
	entry.innerHTML = `<span class="log-time">${new Date().toLocaleTimeString()}</span> — ${msg}`
	log.insertBefore(entry, log.firstChild)
	if (log.children.length > 50) log.lastChild.remove()
}

function toggleEmergency() {
	addLog('🚨 СИГНАЛ АВАРИИ!', 'red')
}

function resetSystem() {
	history = { inlet: {}, outlet: {}, labels: [] }
	;['inlet', 'outlet'].forEach(point => {
		Object.keys(history[point]).forEach(key => {
			history[point][key] = []
		})
	})
	addLog('🔄 Графики сброшены', 'info')
}

window.onload = init
