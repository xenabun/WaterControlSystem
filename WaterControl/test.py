import ctypes
import time

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
OPEN_EXISTING = 3

handle = kernel32.CreateFileW(
    r"\\.\COM4",
    GENERIC_READ | GENERIC_WRITE,
    0,
    None,
    OPEN_EXISTING,
    0,
    None
)

if handle == -1:
    raise ctypes.WinError(ctypes.get_last_error())

print("PORT OPEN")

# ----------------------------------------
# НИКАКОГО SetCommState !!!
# ----------------------------------------

request = bytes.fromhex(
    "01 03 08 00 00 56 C7 94"
)

written = ctypes.c_ulong()

ok = kernel32.WriteFile(
    handle,
    request,
    len(request),
    ctypes.byref(written),
    None
)

if not ok:
    raise ctypes.WinError(ctypes.get_last_error())

print("REQUEST SENT")

time.sleep(1)

buffer = ctypes.create_string_buffer(512)

read = ctypes.c_ulong()

ok = kernel32.ReadFile(
    handle,
    buffer,
    512,
    ctypes.byref(read),
    None
)

if not ok:
    raise ctypes.WinError(ctypes.get_last_error())

data = buffer.raw[:read.value]

print("RESPONSE:")
print(data.hex(' ').upper())

kernel32.CloseHandle(handle)

