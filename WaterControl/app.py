import ctypes
import time
import struct
import threading
from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS

app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app)

COM_PORT = r"\\.\COM4"
REQUEST = bytes.fromhex("01 03 08 00 00 56 C7 94")  # Запрос на чтение 8 регистров
UPDATE_INTERVAL = 15

data_cache = {"inlet": {}, "outlet": {}, "timestamp": 0, "last_update_str": "—"}
lock = threading.Lock()
handle = None
kernel32 = None

# ============================================================
# ПРАВИЛЬНЫЙ ПАРСИНГ ДЛЯ ПОЛНОГО КАДРА 01 03 56
# ============================================================

def decode_special(raw_value, bits=10):
    """
    Декодирование специального формата для ионов
    Используется для: Na, NO3, NO2, NH4
    """
    p = (raw_value >> 15) & 1
    k = (raw_value >> 12) & 0x7
    N = raw_value & ((1 << bits) - 1)
    exp = -k if p else k
    return N * (10 ** exp)

def parse_full_frame(response_bytes):
    """
    Парсинг полного кадра 01 03 56 (86 байт данных)
    Возвращает словарь со значениями всех датчиков
    """
    if not response_bytes or len(response_bytes) < 10:
        return None
    
    # Проверяем заголовок
    if response_bytes[0] != 0x01 or response_bytes[1] != 0x03:
        return None
    
    data_len = response_bytes[2]  # Должно быть 0x56 = 86
    if data_len != 0x56:
        return None
    
    # Данные без заголовка и CRC
    data = response_bytes[3:3+data_len]
    
    # Пропускаем первые 6 байт (время в BCD)
    payload = data[6:]
    
    # Словарь для результатов
    result = {
        "source": "real_device",
        "raw_hex": response_bytes.hex(' ').upper(),
        "last_update_str": time.strftime("%H:%M:%S"),
        "channels": {}
    }
    
    # Парсим 8 каналов по 10 байт каждый
    offset = 0
    for ch_num in range(1, 9):
        if offset + 10 > len(payload):
            break
        
        ch = payload[offset]           # номер канала
        state = payload[offset + 1]    # статус
        value_raw = struct.unpack('>H', payload[offset+2:offset+4])[0]
        temp_raw = struct.unpack('>H', payload[offset+4:offset+6])[0]
        
        # Декодируем значение в зависимости от канала
        if ch == 1:  # УЭП
            value = float(value_raw)
            unit = "мкСм/см"
        elif ch == 2:  # O2 (мкг/л)
            value = float(value_raw)
            unit = "мкг/л"
        elif ch == 3:  # Na (мкг/л)
            value = decode_special(value_raw, 10) * 1000.0
            unit = "мкг/л"
        elif ch == 4:  # pH
            value = value_raw / 100.0
            unit = ""
        elif ch == 5:  # NO3 (мг/л)
            value = decode_special(value_raw, 10)
            unit = "мг/л"
        elif ch == 6:  # NO2 (мг/л)
            value = decode_special(value_raw, 10)
            unit = "мг/л"
        elif ch == 7:  # NH4 (мкг/л)
            value = decode_special(value_raw, 10) * 1000.0
            unit = "мкг/л"
        else:  # Резерв
            value = None
            unit = ""
        
        temp = temp_raw / 10.0
        
        result["channels"][ch] = {
            "channel": ch,
            "state": state,
            "value_raw": value_raw,
            "value": value,
            "unit": unit,
            "temp_c": temp
        }
        
        offset += 10
    
    return result

def parse_simple_response(response_bytes):
    """
    Старый парсер для короткого ответа (если устройство вернет короткий кадр)
    Оставлен для совместимости
    """
    if not response_bytes or len(response_bytes) < 10:
        return None
    
    # Если это полный кадр - используем новый парсер
    if len(response_bytes) > 10 and response_bytes[2] == 0x56:
        return parse_full_frame(response_bytes)
    
    # Старый парсинг для короткого ответа
    data = response_bytes[3:-2]
    
    def u16(i):
        return struct.unpack('>H', data[i:i+2])[0] if i+1 < len(data) else 0
    
    return {
        "source": "real_device",
        "raw_hex": response_bytes.hex(' ').upper(),
        "last_update_str": time.strftime("%H:%M:%S"),
        "channels": {
            1: {"value": round(u16(26) / 1.0, 2), "unit": "мкСм/см", "temp_c": round(u16(28) / 10.0, 1)},
            4: {"value": round(u16(30) / 100.0, 2), "unit": "", "temp_c": round(u16(28) / 10.0, 1)},
            5: {"value": round(u16(12) / 10.0, 2), "unit": "мг/л", "temp_c": round(u16(28) / 10.0, 1)},
            6: {"value": round(u16(10) / 100.0, 2), "unit": "мг/л", "temp_c": round(u16(28) / 10.0, 1)},
            7: {"value": round(u16(8) / 100.0, 2), "unit": "мкг/л", "temp_c": round(u16(28) / 10.0, 1)},
            3: {"value": round(u16(62) / 100.0, 2), "unit": "мкг/л", "temp_c": round(u16(28) / 10.0, 1)},
            2: {"value": round(u16(58) / 1000.0, 2), "unit": "мг/л", "temp_c": round(u16(28) / 10.0, 1)}
        }
    }

# ============================================================
# ИНИЦИАЛИЗАЦИЯ ПОРТА
# ============================================================

def init_port():
    global handle, kernel32
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.CreateFileW(
        COM_PORT, 
        0xC0000000,  # GENERIC_READ | GENERIC_WRITE
        0,           # exclusive access
        None, 
        3,           # OPEN_EXISTING
        0, 
        None
    )
    if handle == -1:
        raise ctypes.WinError(ctypes.get_last_error())
    print(f"✅ Порт {COM_PORT} открыт")
    return True

# ============================================================
# ЧТЕНИЕ УСТРОЙСТВА
# ============================================================

def read_device():
    global handle
    try:
        # Отправка запроса
        written = ctypes.c_ulong()
        kernel32.WriteFile(handle, REQUEST, len(REQUEST), ctypes.byref(written), None)
        
        # Ожидание ответа
        time.sleep(0.9)
        
        # Чтение ответа
        buffer = ctypes.create_string_buffer(512)
        read = ctypes.c_ulong()
        kernel32.ReadFile(handle, buffer, 512, ctypes.byref(read), None)
        
        return buffer.raw[:read.value]
    except Exception as e:
        print(f"❌ Ошибка чтения: {e}")
        return None

# ============================================================
# ФОНОВЫЙ ПОТОК
# ============================================================

def background_reader():
    while True:
        response = read_device()
        parsed = parse_simple_response(response)
        
        with lock:
            if parsed:
                # Формируем данные для инлета и аутлета
                channels = parsed.get("channels", {})
                
                data_cache["inlet"] = {
                    "source": parsed.get("source"),
                    "raw_hex": parsed.get("raw_hex"),
                    "last_update_str": parsed.get("last_update_str"),
                    # Основные показатели
                    "uep": channels.get(1, {}).get("value", 0),
                    "o2": channels.get(2, {}).get("value", 0),
                    "na": channels.get(3, {}).get("value", 0),
                    "ph": channels.get(4, {}).get("value", 0),
                    "no3": channels.get(5, {}).get("value", 0),
                    "no2": channels.get(6, {}).get("value", 0),
                    "nh4": channels.get(7, {}).get("value", 0),
                    "temp": channels.get(1, {}).get("temp_c", 0),
                    # Детальная информация по каналам
                    "channels": channels
                }
                
                # Копируем в outlet (пока одинаковые)
                data_cache["outlet"] = data_cache["inlet"].copy()
                data_cache["timestamp"] = time.time()
                data_cache["last_update_str"] = parsed.get("last_update_str")
                
                print(f"✅ Данные обновлены {data_cache['last_update_str']}")
                print(f"   УЭП: {channels.get(1, {}).get('value', 0)} мкСм/см")
                print(f"   pH: {channels.get(4, {}).get('value', 0)}")
                print(f"   Температура: {channels.get(1, {}).get('temp_c', 0)}°C")
            else:
                print("❌ Ошибка парсинга ответа")
        
        time.sleep(UPDATE_INTERVAL)

# ============================================================
# FLASK РОУТЫ
# ============================================================

@app.route('/api/data')
def get_data():
    with lock:
        return jsonify(data_cache)

@app.route('/api/raw')
def get_raw():
    """Возвращает сырые данные с устройства"""
    with lock:
        return jsonify({
            "raw_hex": data_cache.get("inlet", {}).get("raw_hex", ""),
            "timestamp": data_cache.get("timestamp", 0)
        })

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

# ============================================================
# ЗАПУСК
# ============================================================

if __name__ == '__main__':
    init_port()
    threading.Thread(target=background_reader, daemon=True).start()
    print("🚀 Сервер запущен → http://127.0.0.1:5000")
    app.run(host='0.0.0.0', port=5000, debug=False)