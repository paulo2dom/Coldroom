"""Cliente MQTT minimo para publicar (MQTT 3.1.1, QoS 0), sem dependencias.
Usa timeout no socket para que um broker desligado nao bloqueie o servidor web.
Funciona em MicroPython e CPython.
"""
import socket
import struct


def _str(value):
    if isinstance(value, str):
        value = value.encode()
    return struct.pack('!H', len(value)) + value


def _remaining_length(n):
    out = bytearray()
    while True:
        byte = n & 0x7F
        n >>= 7
        out.append(byte | 0x80 if n else byte)
        if not n:
            return bytes(out)


class MQTTPub:
    def __init__(self, client_id, host, port=1883, user=None, password=None,
                 keepalive=30, timeout=2.0):
        self.client_id = client_id
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.keepalive = keepalive
        self.timeout = timeout
        self.sock = None

    def connect(self, will_topic=None, will_msg='offline', will_retain=True):
        addr = socket.getaddrinfo(self.host, self.port)[0][-1]
        sock = socket.socket()
        sock.settimeout(self.timeout)
        try:
            sock.connect(addr)
            flags = 0x02  # clean session
            payload = _str(self.client_id)
            if will_topic:
                flags |= 0x04 | (0x20 if will_retain else 0)
                payload += _str(will_topic) + _str(will_msg)
            if self.user:
                flags |= 0x80
                payload += _str(self.user)
                if self.password:
                    flags |= 0x40
                    payload += _str(self.password)
            body = _str('MQTT') + bytes([4, flags]) + struct.pack('!H', self.keepalive) + payload
            sock.sendall(b'\x10' + _remaining_length(len(body)) + body)
            ack = b''
            while len(ack) < 4:
                part = sock.recv(4 - len(ack))
                if not part:
                    raise OSError('broker fechou a ligacao')
                ack += part
            if ack[0] != 0x20:
                raise OSError('resposta inesperada do broker')
            if ack[3] != 0:
                # 4 = utilizador/password errados, 5 = nao autorizado
                raise OSError('broker recusou a ligacao (codigo %d)' % ack[3])
        except Exception:
            sock.close()
            raise
        self.sock = sock

    def publish(self, topic, msg, retain=False):
        if isinstance(msg, str):
            msg = msg.encode()
        topic = _str(topic)
        header = 0x30 | (1 if retain else 0)
        self.sock.sendall(bytes([header]) + _remaining_length(len(topic) + len(msg)) + topic + msg)

    def disconnect(self):
        try:
            self.sock.sendall(b'\xe0\x00')
        finally:
            self.close()

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None
