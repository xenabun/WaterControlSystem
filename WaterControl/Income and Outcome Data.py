#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import struct
from datetime import datetime
from collections import deque
from pymongo import MongoClient

# -------------------- НАСТРОЙКИ --------------------
LOG_PATH = r"C:\Users\kolomsim\Desktop\Project\TERMINAL\Logs.log"
POLL_SECONDS = 1

MONGO_URI = "mongodb+srv://gmkolomiets_db_user:YnKyKslvTzHcVqNc@iot.04rdrbv.mongodb.net/?appName=IoT"
DB_NAME = "sens=ors_db"
COLLECTION_NAME = "sensor_readings"

AVG_EVERY_SECONDS = 15
AVG_LAST_FRAMES = 1000

SENSOR_NAME_BY_CH = {
    1: "uep_us_cm",
    2: "o2_ug_l",
    3: "na_ug_l",
    4: "ph",
    5: "no3_mg_l",
    6: "no2_mg_l",
    7: "nh4_ug_l",
}

DISPLAY_LABEL = {1: "УЭП", 2: "O2", 3: "Na", 4: "pH", 5: "NO3", 6: "NO2", 7: "NH4", 8: "Резерв"}
DISPLAY_UNIT  = {1: "uS/cm", 2: "ug/L", 3: "ug/L", 4: "", 5: "mg/L", 6: "mg/L", 7: "ug/L", 8: ""}

FRAME_ADDR = 0x01
FRAME_FUNC = 0x03
FRAME_LEN  = 0x56

# -------------------- CRC16 Modbus --------------------
def crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if (crc & 1) else (crc >> 1)
    return crc & 0xFFFF

def frame_crc_ok(frame: bytes) -> bool:
    if len(frame) < 5:
        return False
    crc_read = frame[-2] | (frame[-1] << 8)  # low, high
    return crc16_modbus(frame[:-2]) == crc_read

# -------------------- ДЕКОДЕРЫ --------------------
def u16(b: bytes) -> int:
    return struct.unpack(">H", b)[0]

def bcd_to_int(x: int) -> int:
    return ((x >> 4) & 0xF) * 10 + (x & 0xF)

def decode_time_bcd(header6: bytes):
    """YY MM DD HH MM SS (BCD)"""
    yy, mo, dd, hh, mm, ss = map(bcd_to_int, header6)
    try:
        return datetime(2000 + yy, mo, dd, hh, mm, ss)
    except ValueError:
        return None

def decode_temperature(temp_raw: int) -> float:
    return temp_raw / 10.0

def decode_ph(val_raw: int) -> float:
    return val_raw / 100.0

def decode_special(raw: int, n_bits: int) -> float:
    p = (raw >> 15) & 1
    k = (raw >> 12) & 0x7
    N = raw & ((1 << n_bits) - 1)
    exp = -k if p else k
    return N * (10 ** exp)

def decode_ion_mg_l(raw: int) -> float:
    return decode_special(raw, 10)

def decode_channel_value(ch: int, value_raw: int) -> float | None:
    if ch == 1:  # УЭП
        return float(value_raw)
    if ch == 2:  # O2 ug/L
        return float(value_raw)
    if ch == 4:  # pH
        return float(decode_ph(value_raw))
    if ch == 3:  # Na mg/L -> ug/L
        return float(decode_ion_mg_l(value_raw) * 1000.0)
    if ch == 7:  # NH4 mg/L -> ug/L
        return float(decode_ion_mg_l(value_raw) * 1000.0)
    if ch == 5:  # NO3 mg/L
        return float(decode_ion_mg_l(value_raw))
    if ch == 6:  # NO2 mg/L
        return float(decode_ion_mg_l(value_raw))
    return None

# -------------------- ОКРУГЛЕНИЕ ДЛЯ MONGO --------------------
def normalize_value_for_mongo(value: float) -> float:
    """
    Если значение целое — сохраняем без дробной части.
    Если нецелое — округляем до 2 знаков.
    В Mongo останется число (не строка).
    """
    if float(value).is_integer():
        return float(int(value))
    return round(float(value), 2)

# -------------------- ИЗВЛЕЧЕНИЕ / ПАРСИНГ --------------------
def extract_frames(buf: bytes):
    """Достаёт все валидные кадры 01 03 <len> ... <CRC>"""
    frames = []
    i = 0
    n = len(buf)

    while i + 3 <= n:
        if buf[i] == FRAME_ADDR and buf[i + 1] == FRAME_FUNC:
            ln = buf[i + 2]
            total = 3 + ln + 2
            if i + total <= n:
                fr = buf[i:i + total]
                if frame_crc_ok(fr):
                    frames.append(fr)
                    i += total
                else:
                    i += 1
            else:
                return frames, buf[i:]
        else:
            i += 1

    return frames, b""

def parse_frame_0103_56(frame: bytes):
    """Разбор кадра 01 03 56"""
    if frame[:3] != bytes([FRAME_ADDR, FRAME_FUNC, FRAME_LEN]):
        return None

    data = frame[3:3 + FRAME_LEN]
    if len(data) != FRAME_LEN:
        return None

    header6 = data[:6]
    payload = data[6:]
    ts_dev = decode_time_bcd(header6)

    channels = []
    off = 0
    for _ in range(8):
        blk = payload[off:off + 10]
        off += 10
        if len(blk) < 10:
            break

        ch = blk[0]
        state = blk[1]
        value_raw = u16(blk[2:4])
        temp_raw = u16(blk[4:6])

        channels.append({
            "ch": ch,
            "state": state,
            "value_raw": value_raw,
            "temp_c": decode_temperature(temp_raw),
            "value": decode_channel_value(ch, value_raw),
        })

    return ts_dev, channels

# -------------------- MongoDB --------------------
def mongo_connect():
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    coll = db[COLLECTION_NAME]
    return client, coll

def save_frame_to_mongo(coll, ts: datetime, channels: list[dict]):
    docs = []
    for c in channels:
        ch = c["ch"]
        if ch not in SENSOR_NAME_BY_CH:
            continue
        value = c["value"]
        if value is None:
            continue

        docs.append({
            "date": ts,
            "name_of_sensor": SENSOR_NAME_BY_CH[ch],
            "value": normalize_value_for_mongo(float(value)),
        })

    if docs:
        coll.insert_many(docs)

# -------------------- ПЕЧАТЬ --------------------
def print_frame(ts: datetime, channels: list[dict], tag: str = ""):
    ts_str = ts.strftime("%Y-%m-%d %H:%M:%S")
    head = f"🕒 {ts_str}"
    if tag:
        head += f"   [{tag}]"
    print("\n" + head)

    by_ch = {c["ch"]: c for c in channels}
    for ch in range(1, 9):
        c = by_ch.get(ch)
        label = DISPLAY_LABEL.get(ch, f"CH{ch}")
        unit = DISPLAY_UNIT.get(ch, "")

        if c is None:
            print(f"  {ch} {label:<6}: —")
            continue

        state = c["state"]
        temp = c["temp_c"]
        val = c["value"]

        if val is None or ch == 8:
            val_str = "—"
        else:
            # печать: целые без .00, дробные с 2 знаками
            vv = float(val)
            val_str = f"{int(vv)}" if vv.is_integer() else f"{vv:.2f}"

        u = f" {unit}" if unit else ""
        print(f"  {ch} {label:<6}: {val_str:<10}{u:<7}  T={temp:.1f} °C  state=0x{state:02X}")

# -------------------- ДЕДУП --------------------
def semantic_key(ts_dev: datetime | None, channels: list[dict]):
    ch_key = tuple(sorted((c["ch"], c["value_raw"], int(c["temp_c"] * 10)) for c in channels))
    return (ts_dev, ch_key)

# -------------------- AVG по последним N кадрам --------------------
def compute_avg_last_frames(last_frames: deque):
    sums_val, sums_temp, sums_state, cnt = {}, {}, {}, {}

    for channels in last_frames:
        for c in channels:
            ch = c["ch"]
            if ch not in SENSOR_NAME_BY_CH:
                continue
            if c["value"] is None:
                continue

            sums_val[ch] = sums_val.get(ch, 0.0) + float(c["value"])
            sums_temp[ch] = sums_temp.get(ch, 0.0) + float(c["temp_c"])
            sums_state[ch] = sums_state.get(ch, 0) + int(c["state"])
            cnt[ch] = cnt.get(ch, 0) + 1

    out = []
    for ch in range(1, 9):
        if ch in SENSOR_NAME_BY_CH and cnt.get(ch, 0) > 0:
            out.append({
                "ch": ch,
                "state": int(round(sums_state[ch] / cnt[ch])) & 0xFF,
                "value_raw": 0,
                "temp_c": sums_temp[ch] / cnt[ch],
                "value": sums_val[ch] / cnt[ch],
            })
        else:
            out.append({
                "ch": ch,
                "state": 0x03 if ch == 8 else 0x00,
                "value_raw": 0,
                "temp_c": 0.0,
                "value": None,
            })
    return out

# -------------------- Обработка кадров --------------------
def handle_frames(buf: bytes, coll, seen: set, last_frames: deque, add_to_avg_buffer: bool):
    frames, leftover = extract_frames(buf)
    new_cnt = 0

    for fr in frames:
        parsed = parse_frame_0103_56(fr)
        if not parsed:
            continue

        ts_dev, channels = parsed
        key = semantic_key(ts_dev, channels)
        if key in seen:
            continue
        seen.add(key)

        ts_normal = ts_dev if ts_dev else datetime.now()

        print_frame(ts_normal, channels, tag="NEW")
        save_frame_to_mongo(coll, ts_normal, channels)
        print("  ✅ отправлено в MongoDB")

        if add_to_avg_buffer:
            last_frames.append(channels)

        new_cnt += 1

    return leftover, new_cnt

def main():
    print("▶ АТОН-801 МП: импорт + онлайн → MongoDB")
    print(f"▶ Файл: {LOG_PATH}")
    print(f"▶ Интервал опроса: {POLL_SECONDS} сек")

    client, coll = mongo_connect()
    seen = set()
    carry = b""
    last_pos = 0

    # буфер последних N кадров для AVG (ИЗ ИМПОРТА + НОВЫХ)
    last_frames = deque(maxlen=AVG_LAST_FRAMES)

    next_avg_ts = None

    try:
        # 1) старт: читаем весь файл, печатаем/шлём кадры, и НАПОЛНЯЕМ буфер AVG
        if os.path.exists(LOG_PATH):
            with open(LOG_PATH, "rb") as f:
                data = f.read()
            last_pos = len(data)

            carry, _ = handle_frames(data, coll, seen, last_frames, add_to_avg_buffer=True)
            print("\n▶ Стартовый импорт завершён.")
        else:
            print("⚠️ Файл логов не найден. Жду появления...")

        next_avg_ts = time.time() + AVG_EVERY_SECONDS

        # 2) онлайн: новые кадры + AVG
        while True:
            now = time.time()

            # --- AVG (по времени ноутбука), по последним N кадрам ---
            if next_avg_ts is not None and now >= next_avg_ts:
                if len(last_frames) > 0:
                    avg_channels = compute_avg_last_frames(last_frames)
                    ts_avg = datetime.now()
                    print_frame(ts_avg, avg_channels, tag="NEW")  # как обычный "новый"
                    save_frame_to_mongo(coll, ts_avg, avg_channels)
                    print("  ✅ отправлено в MongoDB")
                else:
                    print("\n🕒 " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                    print("  (в логе ещё нет ни одного кадра)")

                next_avg_ts = now + AVG_EVERY_SECONDS

            # --- чтение новых данных из файла ---
            try:
                size = os.path.getsize(LOG_PATH)

                # файл перезаписали/обнулили
                if size < last_pos:
                    print("\n⚠️ Лог перезаписан/обнулён — читаю заново\n")
                    seen.clear()
                    carry = b""
                    last_pos = 0
                    last_frames.clear()

                    with open(LOG_PATH, "rb") as f:
                        data = f.read()
                    last_pos = len(data)

                    carry, _ = handle_frames(data, coll, seen, last_frames, add_to_avg_buffer=True)
                    print("\n▶ Повторный импорт завершён.")

                    next_avg_ts = time.time() + AVG_EVERY_SECONDS

                if size > last_pos:
                    with open(LOG_PATH, "rb") as f:
                        f.seek(last_pos)
                        chunk = f.read(size - last_pos)
                    last_pos = size

                    buf = carry + chunk
                    carry, cnt = handle_frames(buf, coll, seen, last_frames, add_to_avg_buffer=True)

                    if cnt:
                        print(f"\n▶ Новых кадров за цикл: {cnt}\n")

            except FileNotFoundError:
                print("Файл логов не найден, жду...")
                last_pos = 0
                carry = b""
                last_frames.clear()
                next_avg_ts = time.time() + AVG_EVERY_SECONDS

            time.sleep(POLL_SECONDS)

    except KeyboardInterrupt:
        print("\nОстановлено пользователем.")
    finally:
        client.close()

if __name__ == "__main__":
    main()
