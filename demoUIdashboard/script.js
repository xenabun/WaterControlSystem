/**
 * Конфигурация параметров согласно спецификации АТОН-801
 * norm: [min, max] - границы зеленой зоны
 */
const parameters = [
    { id: 'nh4', name: 'NH4+', unit: 'мг/л', norm: [0, 0.5] },
    { id: 'no3', name: 'NO3-', unit: 'мг/л', norm: [0, 20] },
    { id: 'no2', name: 'NO2-', unit: 'мг/л', norm: [0, 0.1] },
    { id: 'ph', name: 'pH', unit: '', norm: [6.5, 8.5] },
    { id: 'cond', name: 'УЭП', unit: 'мСм/см', norm: [200, 800] },
    { id: 'na', name: 'Na+', unit: 'мг/л', norm: [0, 50] },
    { id: 'o2', name: 'O2', unit: 'мг/л', norm: [7, 12] },
    { id: 'temp', name: 'T', unit: '°C', norm: [15, 25] }
];

// Глобальное состояние системы
let charts = {};
let activeParam = { inlet: 'o2', outlet: 'o2' };
let history = { inlet: {}, outlet: {}, labels: [] };
let lastStates = { inlet: {}, outlet: {} };
let isEmergency = false;

// Инициализация структур данных
parameters.forEach(p => {
    history.inlet[p.id] = [];
    history.outlet[p.id] = [];
    lastStates.inlet[p.id] = 'green';
    lastStates.outlet[p.id] = 'green';
});

/**
 * Инициализация дашборда
 */
function init() {
    ['inlet', 'outlet'].forEach(point => {
        const container = document.getElementById(`${point}-params`);
        
        parameters.forEach(p => {
            container.innerHTML += `
                <div class="param-item border-green" id="${point}-${p.id}-box" onclick="selectParam('${point}', '${p.id}')">
                    <div class="param-header">
                        <span class="param-label">${p.name}</span>
                        <span id="${point}-${p.id}-status" class="param-status-text" style="color: var(--green)">НОРМА</span>
                    </div>
                    <div class="param-value-row">
                        <span class="param-value" id="${point}-${p.id}-val">--</span>
                        <span class="unit">${p.unit}</span>
                    </div>
                </div>
            `;
        });

        setupChart(point);
        selectParam(point, activeParam[point]);
    });

    // Запуск цикла обновления данных (раз в 2 секунды)
    setInterval(tick, 2000);
    
    addLog("Система мониторинга АТОН-801 запущена. Связь с датчиками установлена.", "info");
}

/**
 * Создание объекта графика Chart.js
 */
function setupChart(point) {
    const ctx = document.getElementById(`chart-${point}`).getContext('2d');
    charts[point] = new Chart(ctx, {
        type: 'line',
        data: { 
            labels: history.labels, 
            datasets: [{ 
                label: '', 
                data: [], 
                borderColor: '#3498db', 
                backgroundColor: 'rgba(52, 152, 219, 0.1)', 
                fill: true, 
                tension: 0.3 
            }] 
        },
        options: { 
            responsive: true, 
            maintainAspectRatio: false,
            animation: { duration: 0 } // Отключаем анимацию для производительности при частом обновлении
        }
    });
}

/**
 * Обработка клика по карточке параметра
 */
function selectParam(point, id) {
    activeParam[point] = id;
    
    // Визуальное выделение активной карточки
    parameters.forEach(p => {
        document.getElementById(`${point}-${p.id}-box`).classList.remove('active');
    });
    document.getElementById(`${point}-${id}-box`).classList.add('active');
    
    // Обновление заголовка графика
    const pInfo = parameters.find(p => p.id === id);
    charts[point].data.datasets[0].label = `Тренд: ${pInfo.name} (${pInfo.unit})`;
    
    refreshChartDisplay(point);
}

/**
 * Основной цикл генерации моковых данных
 */
function tick() {
    const now = new Date().toLocaleTimeString();
    history.labels.push(now);
    if (history.labels.length > 20) history.labels.shift();

    parameters.forEach(p => {
        ['inlet', 'outlet'].forEach(point => {
            let val;
            
            // Если включена авария, "портим" данные нитритов на выходе
            if (isEmergency && point === 'outlet' && p.id === 'no2') {
                val = (0.12 + Math.random() * 0.08).toFixed(3);
            } else {
                // Генерация случайных данных в пределах нормы с небольшими отклонениями
                const range = p.norm[1] - p.norm[0];
                val = (p.norm[0] + Math.random() * range).toFixed(2);
                
                // Иногда создаем легкое "желтое" отклонение для наглядности
                if (Math.random() > 0.95) val = (p.norm[1] * 1.05).toFixed(2);
            }
            
            history[point][p.id].push(val);
            if (history[point][p.id].length > 20) history[point][p.id].shift();
            
            updateUI(point, p, val);
        });
    });

    refreshChartDisplay('inlet');
    refreshChartDisplay('outlet');
}

/**
 * Обновление визуального состояния карточек
 */
function updateUI(point, param, val) {
    const box = document.getElementById(`${point}-${param.id}-box`);
    const valEl = document.getElementById(`${point}-${param.id}-val`);
    const statusEl = document.getElementById(`${point}-${param.id}-status`);
    
    valEl.innerText = val;
    
    let currentState = 'green';
    let statusText = 'НОРМА';

    // Определение зоны
    if (val > param.norm[1] * 1.2 || val < param.norm[0] * 0.8) {
        currentState = 'red';
        statusText = 'КРИТ';
    } else if (val > param.norm[1] || val < param.norm[0]) {
        currentState = 'yellow';
        statusText = 'ВНИМ';
    }

    // Логирование только при смене состояния
    if (lastStates[point][param.id] !== currentState) {
        logStateChange(point, param, val, currentState);
        lastStates[point][param.id] = currentState;
    }

    // Смена классов для левой грани
    box.classList.remove('border-green', 'border-yellow', 'border-red');
    box.classList.add(`border-${currentState}`);
    
    statusEl.innerText = statusText;
    statusEl.style.color = `var(--${currentState})`;
}

/**
 * Логика записи событий в журнал
 */
function logStateChange(point, param, val, newState) {
    const pointName = point === 'inlet' ? 'ВХОД' : 'ВЫХОД';
    
    if (newState === 'red') {
        addLog(`КРИТИЧЕСКАЯ ОШИБКА: ${param.name} на ${pointName} достиг ${val} ${param.unit}!`, 'red');
    } else if (newState === 'yellow') {
        addLog(`Предупреждение: ${param.name} на ${pointName} (${val}) вышел за границы нормы.`, 'yellow');
    } else if (newState === 'green') {
        addLog(`Параметр ${param.name} на ${pointName} стабилизирован.`, 'info');
    }
}

/**
 * Вывод сообщения в HTML-контейнер лога
 */
function addLog(msg, type = 'info') {
    const logContainer = document.getElementById('log-list');
    const time = new Date().toLocaleTimeString();
    
    const entry = document.createElement('div');
    entry.className = `log-entry ${type}`;
    entry.innerHTML = `<span class="log-time">[${time}]</span> ${msg}`;
    
    logContainer.prepend(entry); // Добавляем новые записи сверху
}

/**
 * Перерисовка текущего графика
 */
function refreshChartDisplay(point) {
    const id = activeParam[point];
    charts[point].data.datasets[0].data = history[point][id];
    charts[point].update('none');
}

/**
 * Управление симуляцией
 */
function toggleEmergency() {
    isEmergency = true;
    addLog("Запущена ручная симуляция: Нарушение работы биофильтра (Нитриты)", "info");
    // Автоматически переключаем график на проблемный датчик для наглядности
    selectParam('outlet', 'no2');
}

function resetSystem() {
    isEmergency = false;
    addLog("Система переведена в штатный режим. Очистка восстановлена.", "info");
}

// Старт
window.onload = init;