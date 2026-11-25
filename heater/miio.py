"""Minimal Xiaomi miIO / MIoT LAN protocol client (UDP 54321)."""
import hashlib
import json
import random
import socket
import struct
import threading
import time

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

PORT = 54321
HELLO = bytes.fromhex("21310020" + "ff" * 28)


class MiioError(Exception):
    pass


class MiioTimeout(MiioError):
    pass


def _md5(data: bytes) -> bytes:
    return hashlib.md5(data).digest()


class MiioDevice:
    def __init__(self, ip: str, token: str, timeout: float = 3.0):
        self.ip = ip
        self.token = bytes.fromhex(token.strip())
        if len(self.token) != 16:
            raise MiioError("Token must be 32 hexadecimal characters")
        self.key = _md5(self.token)
        self.iv = _md5(self.key + self.token)
        self.timeout = timeout
        self.devid = None
        self.stamp = 0
        self.stamp_at = 0.0
        self.msg_id = random.randint(1000, 9000)
        self.lock = threading.Lock()

    # --- crypto -----------------------------------------------------------
    def _encrypt(self, plain: bytes) -> bytes:
        padder = padding.PKCS7(128).padder()
        data = padder.update(plain) + padder.finalize()
        enc = Cipher(algorithms.AES(self.key), modes.CBC(self.iv)).encryptor()
        return enc.update(data) + enc.finalize()

    def _decrypt(self, data: bytes) -> bytes:
        dec = Cipher(algorithms.AES(self.key), modes.CBC(self.iv)).decryptor()
        plain = dec.update(data) + dec.finalize()
        unpadder = padding.PKCS7(128).unpadder()
        try:
            return unpadder.update(plain) + unpadder.finalize()
        except ValueError:
            return plain

    # --- transport --------------------------------------------------------
    def _sock(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(self.timeout)
        return s

    def handshake(self):
        with self._sock() as s:
            s.sendto(HELLO, (self.ip, PORT))
            try:
                data, _ = s.recvfrom(1024)
            except (socket.timeout, ConnectionResetError):
                raise MiioTimeout(f"Heater at {self.ip} did not answer the handshake")
        self.devid = struct.unpack(">I", data[8:12])[0]
        self.stamp = struct.unpack(">I", data[12:16])[0]
        self.stamp_at = time.monotonic()

    def send(self, method: str, params=None, retries: int = 2):
        with self.lock:
            last_err = None
            for attempt in range(retries + 1):
                try:
                    if self.devid is None or attempt > 0:
                        self.handshake()
                    return self._send_once(method, params)
                except MiioTimeout as e:
                    last_err = e
            raise MiioTimeout(
                "No reply from the heater. Check that the token is correct "
                "and the heater is online."
            ) from last_err

    def _send_once(self, method, params):
        self.msg_id = (self.msg_id + 1) % 0x7FFFFFFF
        req_id = self.msg_id
        payload = json.dumps(
            {"id": req_id, "method": method, "params": params if params is not None else []},
            separators=(",", ":"),
        ).encode()
        enc = self._encrypt(payload)
        stamp = self.stamp + int(time.monotonic() - self.stamp_at)
        header = struct.pack(">HHIII", 0x2131, 32 + len(enc), 0, self.devid, stamp)
        checksum = _md5(header + self.token + enc)
        packet = header + checksum + enc

        with self._sock() as s:
            s.sendto(packet, (self.ip, PORT))
            deadline = time.monotonic() + self.timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise MiioTimeout("timeout")
                s.settimeout(remaining)
                try:
                    data, _ = s.recvfrom(4096)
                except (socket.timeout, ConnectionResetError):
                    raise MiioTimeout("timeout")
                if len(data) <= 32:
                    continue
                plain = self._decrypt(data[32:]).rstrip(b"\x00")
                try:
                    resp = json.loads(plain.decode("utf-8", "replace"))
                except json.JSONDecodeError:
                    continue
                if resp.get("id") != req_id:
                    continue  # stale reply to an earlier request
                if "error" in resp:
                    err = resp["error"]
                    raise MiioError(f"Device error: {err.get('message', err)}")
                return resp.get("result")

    # --- MIoT helpers -----------------------------------------------------
    def info(self):
        return self.send("miIO.info")

    def get_properties(self, pairs):
        """pairs: list of (siid, piid). Returns {(siid, piid): value or None}."""
        out = {}
        for i in range(0, len(pairs), 12):  # devices cap request size
            chunk = pairs[i : i + 12]
            params = [{"did": f"{s}-{p}", "siid": s, "piid": p} for s, p in chunk]
            for r in self.send("get_properties", params) or []:
                key = (r.get("siid"), r.get("piid"))
                out[key] = r.get("value") if r.get("code", 0) == 0 else None
        return out

    def set_property(self, siid, piid, value):
        res = self.send(
            "set_properties", [{"did": f"{siid}-{piid}", "siid": siid, "piid": piid, "value": value}]
        )
        if res and res[0].get("code", 0) != 0:
            raise MiioError(f"Heater rejected the change (code {res[0].get('code')})")
        return res

    def action(self, siid, aiid, args=None):
        return self.send("action", {"did": f"{siid}-{aiid}", "siid": siid, "aiid": aiid, "in": args or []})
