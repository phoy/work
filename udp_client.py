#!/usr/bin/env python3
"""
UDP file transfer client.
Auth: HMAC-SHA256 challenge-response
Encryption: ChaCha20-Poly1305
Traffic analysis resistance: fixed-size padding + configurable timing jitter

Usage:
  python3 udp_client.py --server <ip/host> --password <secret> --file <path>
                        [--port 4444] [--jitter-min 50] [--jitter-max 300]
"""
import socket, struct, os, sys, hashlib, hmac, time, argparse, secrets, random

from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
from cryptography.exceptions import InvalidTag

# ── constants ─────────────────────────────────────────────────────────────────
PT_HELLO     = 0x01
PT_CHALLENGE = 0x02
PT_AUTH      = 0x03
PT_AUTH_OK   = 0x04
PT_AUTH_FAIL = 0x05
PT_DATA      = 0x06
PT_END       = 0x07
PT_ACK       = 0x08

CHUNK_SIZE   = 512
NONCE_LEN    = 12
TOKEN_LEN    = 16
PADDED_SIZE  = 1024
TIMEOUT      = 4.0
MAX_RETRIES  = 4


# ── padding ───────────────────────────────────────────────────────────────────

def pad(data: bytes) -> bytes:
    assert len(data) <= PADDED_SIZE - 2, f"plaintext too large ({len(data)} bytes)"
    return struct.pack('!H', len(data)) + data + secrets.token_bytes(PADDED_SIZE - 2 - len(data))


# ── crypto ────────────────────────────────────────────────────────────────────

def derive_enc_key(session_token: bytes) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b'udp-file-transfer-v1',
        info=b'encryption-key',
    ).derive(session_token)


def encrypt_and_pad(enc_key: bytes, plaintext: bytes) -> bytes:
    nonce  = secrets.token_bytes(NONCE_LEN)
    padded = pad(plaintext)
    ct     = ChaCha20Poly1305(enc_key).encrypt(nonce, padded, None)
    return nonce + ct


# ── client ────────────────────────────────────────────────────────────────────

class UDPClient:
    def __init__(self, server: str, port: int, password: str, jitter_min: float, jitter_max: float):
        self.server      = server
        self.port        = port
        self.key         = password.encode()
        self.jitter_min  = jitter_min
        self.jitter_max  = jitter_max
        self.token       = None
        self.enc_key     = None
        self.sock        = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._last_send  = 0.0

    def _jitter_wait(self):
        elapsed = time.monotonic() - self._last_send
        target  = random.uniform(self.jitter_min, self.jitter_max)
        gap     = target - elapsed
        if gap > 0:
            time.sleep(gap)

    def _send_recv(self, payload: bytes, expected_type: int, timeout=TIMEOUT, jitter=True):
        if jitter:
            self._jitter_wait()

        deadline = time.monotonic() + timeout
        self.sock.settimeout(timeout)
        self.sock.sendto(payload, (self.server, self.port))
        self._last_send = time.monotonic()

        while time.monotonic() < deadline:
            try:
                data, _ = self.sock.recvfrom(65535)
            except socket.timeout:
                break

            if len(data) < 1:
                continue

            ptype = data[0]
            body  = data[1:]

            if ptype == PT_AUTH_FAIL:
                raise PermissionError(f"Server rejected: {body.decode(errors='replace')}")
            if ptype == expected_type:
                return body

        return None

    def _encrypted_packet(self, ptype: int, plaintext: bytes) -> bytes:
        blob = encrypt_and_pad(self.enc_key, plaintext)
        return bytes([ptype]) + self.token + blob

    def authenticate(self):
        print("[*] Sending HELLO…")
        body = self._send_recv(bytes([PT_HELLO]), PT_CHALLENGE, jitter=False)
        if body is None:
            raise ConnectionError("No response from server")

        nonce    = body[:16]
        response = hmac.new(self.key, nonce, hashlib.sha256).digest()

        print("[*] Sending AUTH…")
        token = self._send_recv(bytes([PT_AUTH]) + response, PT_AUTH_OK, jitter=False)
        if token is None:
            raise PermissionError("Authentication failed — wrong password?")

        self.token   = token[:TOKEN_LEN]
        self.enc_key = derive_enc_key(self.token)
        print(f"[+] Authenticated  session={self.token.hex()[:8]}…")

    def send_file(self, filepath: str):
        filename  = os.path.basename(filepath)
        fname_enc = filename.encode()
        with open(filepath, 'rb') as f:
            raw = f.read()

        chunks = [raw[i:i + CHUNK_SIZE] for i in range(0, len(raw), CHUNK_SIZE)]
        total  = len(chunks)
        sha256 = hashlib.sha256(raw).digest()

        wire_size = TOKEN_LEN + NONCE_LEN + PADDED_SIZE + 16
        print(f"[*] Sending '{filename}'  {len(raw):,} bytes  {total} chunks")
        print(f"[*] Wire size per packet: {wire_size} bytes (fixed)")
        print(f"[*] Jitter: {self.jitter_min*1000:.0f}–{self.jitter_max*1000:.0f} ms between sends")

        for i, chunk in enumerate(chunks):
            plain = struct.pack('!IIB', i, total, len(fname_enc)) + fname_enc + chunk
            pkt   = self._encrypted_packet(PT_DATA, plain)

            for attempt in range(MAX_RETRIES):
                reply = self._send_recv(pkt, PT_ACK)
                if reply and len(reply) >= 4 and struct.unpack('!I', reply[:4])[0] == i:
                    break
                print(f"  [~] chunk {i} retry {attempt + 1}/{MAX_RETRIES}")
            else:
                raise IOError(f"Failed to deliver chunk {i} after {MAX_RETRIES} retries")

            if i % 50 == 0 or i == total - 1:
                print(f"  {i + 1}/{total}  ({(i + 1) / total * 100:.0f}%)")

        pkt   = self._encrypted_packet(PT_END, sha256)
        reply = self._send_recv(pkt, PT_ACK, timeout=8.0)
        if reply == b'OK':
            print("[+] Transfer complete — server confirmed checksum.")
        else:
            print(f"[!] Server response: {reply}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--server',     required=True)
    p.add_argument('--password',   required=True)
    p.add_argument('--file',       required=True)
    p.add_argument('--port',       type=int, default=4444)
    p.add_argument('--jitter-min', type=float, default=50,
                   help='Minimum delay between sends in milliseconds (default: 50)')
    p.add_argument('--jitter-max', type=float, default=300,
                   help='Maximum delay between sends in milliseconds (default: 300)')
    args = p.parse_args()

    if not os.path.isfile(args.file):
        sys.exit(f"File not found: {args.file}")
    if args.jitter_min > args.jitter_max:
        sys.exit("--jitter-min must be <= --jitter-max")

    client = UDPClient(
        server      = args.server,
        port        = args.port,
        password    = args.password,
        jitter_min  = args.jitter_min / 1000,
        jitter_max  = args.jitter_max / 1000,
    )
    client.authenticate()
    client.send_file(args.file)


if __name__ == '__main__':
    main()
