from __future__ import annotations

import base64
import binascii
import hashlib
import time

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

class AESCipher:
    def __init__(self, key):
        self.block_size = 16
        self.cipher = Cipher(algorithms.AES(key), modes.ECB(), default_backend())

    def encrypt(self, raw, use_base64=True):
        enc = self.cipher.encryptor()
        out = enc.update(self._pad(raw)) + enc.finalize()
        return base64.b64encode(out) if use_base64 else out

    def decrypt(self, enc, use_base64=True):
        if use_base64:
            enc = base64.b64decode(enc)
        dec = self.cipher.decryptor()
        return self._unpad(dec.update(enc) + dec.finalize())

    def _pad(self, data):
        n = self.block_size - len(data) % self.block_size
        return data + n * chr(n).encode()

    @staticmethod
    def _unpad(data):
        return data[:-ord(data[len(data)-1:])]

def _xor64(arr, value):
    for i in range(64):
        arr[i] ^= value
    return arr

def generate_working_key(arr, i):
    arr2 = bytearray(72)
    arr2[:len(arr)] = arr
    arr2 = _xor64(arr2, 0x36)
    for off in (71, 70, 69, 68):
        arr2[off] = i & 0xFF
        i >>= 8
    arr2sha1 = hashlib.sha1(arr2).digest()

    arr3 = bytearray(84)
    arr3[:len(arr)] = arr
    arr3 = _xor64(arr3, 0x5C)
    arr3[64:84] = arr2sha1
    return hashlib.sha1(arr3).digest()

def generate_psw_v2(arr):
    out = bytearray(8)
    for i in range(4):
        b = arr[i + 16]
        out[i*2] = arr[(b >> 4) & 15]
        out[i*2 + 1] = arr[b & 15]
    return out

def generate_signature_v2(key, i, arr):
    n = len(arr)
    arr2 = bytearray(n + 68)
    arr2[:20] = key[:20]
    arr2 = _xor64(arr2, 0x36)
    arr2[64:64+n] = arr
    for off in (n+67, n+66, n+65, n+64):
        arr2[off] = i & 0xFF
        i >>= 8
    inner = hashlib.sha1(arr2).digest()

    arr3 = bytearray(84)
    arr3[:20] = key[:20]
    arr3 = _xor64(arr3, 0x5C)
    arr3[64:84] = inner
    return generate_psw_v2(hashlib.sha1(arr3).digest())

def checksum(arr, start, end):
    return sum(arr[start:end]) & 0xFF

class AirbnkCodesGenerator:
    def __init__(self):
        self.manufacturer_key = b""
        self.binding_key = b""
        self.system_time = 0

    def decrypt_keys(self, new_sn_info, app_key):
        dec = base64.b64decode(new_sn_info)
        encrypted = dec[:-10]
        key = app_key[:-4]
        dec = AESCipher(key.encode("utf-8")).decrypt(encrypted, False)
        lock_sn = dec[:16].decode("utf-8").rstrip("\x00")
        lock_model = dec[80:88].decode("utf-8").rstrip("\x00")
        manufacturer = dec[16:48]
        binding = dec[48:80]
        digest = hashlib.sha1((lock_sn + app_key).encode()).hexdigest()
        key2 = bytes.fromhex(digest[:32])
        self.manufacturer_key = AESCipher(key2).decrypt(manufacturer, False)
        self.binding_key = AESCipher(key2).decrypt(binding, False)
        return {"lockSn": lock_sn, "lockModel": lock_model}

    def operation_code(self, lock_dir, lock_events):
        self.system_time = int(round(time.time()))
        code = bytearray(36)
        code[0:5] = bytes([0xAA, 0x10, 0x1A, 3, 3])
        code[5] = 16 + lock_dir
        code[8] = 1
        ts = self.system_time
        code[9] = ts & 0xFF
        ts >>= 8; code[10] = ts & 0xFF
        ts >>= 8; code[11] = ts & 0xFF
        ts >>= 8; code[12] = ts & 0xFF
        encrypted = AESCipher(self.manufacturer_key[:16]).encrypt(code[4:18], False)
        code[4:20] = encrypted
        working = generate_working_key(self.binding_key, 0)
        sig = generate_signature_v2(working, lock_events, code[3:20])
        code[20:20+len(sig)] = sig
        code[20+len(sig)] = checksum(code, 3, 28)
        return binascii.hexlify(code).upper()
