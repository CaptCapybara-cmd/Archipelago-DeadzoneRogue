"""Read the running game's GMalloc vtable and disassemble each entry, to work out FMalloc's real layout."""
import ctypes, ctypes.wintypes as wt, subprocess, sys
from capstone import Cs, CS_ARCH_X86, CS_MODE_64

GMALLOC_VAR = int(sys.argv[1], 16)  # address of the GMalloc global, from UE4SS.log (same game run)
SLOTS = int(sys.argv[2]) if len(sys.argv) > 2 else 30

pid = int(subprocess.check_output(["powershell", "-NoProfile", "-c",
      "(Get-Process DeadzoneSteam-Win64-Shipping).Id"]).strip())
base = int(subprocess.check_output(["powershell", "-NoProfile", "-c",
      "[int64](Get-Process DeadzoneSteam-Win64-Shipping).MainModule.BaseAddress"]).strip())
k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.OpenProcess.restype = wt.HANDLE
h = k32.OpenProcess(0x0010 | 0x0400, False, pid)  # VM_READ | QUERY_INFORMATION


def read(addr, n):
    buf = ctypes.create_string_buffer(n)
    got = ctypes.c_size_t()
    if not k32.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, n, ctypes.byref(got)):
        raise OSError(f"read {addr:#x} failed: {ctypes.get_last_error()}")
    return buf.raw[:got.value]


q = lambda a: int.from_bytes(read(a, 8), "little")
md = Cs(CS_ARCH_X86, CS_MODE_64)
obj = q(GMALLOC_VAR)
vt = q(obj)
print(f"pid {pid} base {base:#x}  GMalloc obj {obj:#x}  vtable {vt:#x} (rva {vt - base:#x})")
for i in range(SLOTS):
    fn = q(vt + i * 8)
    code = read(fn, 64)
    ins = [f"{x.mnemonic} {x.op_str}" for x in md.disasm(code, fn)][:7]
    print(f"[{i:2}] +{i*8:#04x} rva {fn - base:#x}: " + " ; ".join(ins))
