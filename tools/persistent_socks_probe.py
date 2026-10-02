"""固定SOCKS同一TLS连接探针，无重连、无生成调用。"""
import http.client
import socket
import ssl
import struct


def receive(sock, count):
    data = b''
    while len(data) < count:
        chunk = sock.recv(count - len(data))
        if not chunk:
            raise ConnectionError('unexpected_eof')
        data += chunk
    return data


class PersistentProbe:
    def __init__(self, port=21012):
        self.sock = socket.create_connection(('127.0.0.1', port), timeout=6)
        try:
            self.sock.sendall(b'\x05\x01\x00')
            if receive(self.sock, 2) != b'\x05\x00':
                raise ConnectionError('socks_auth_failed')
            host = b'www.google.com'
            self.sock.sendall(b'\x05\x01\x00\x03' + bytes([len(host)]) + host + struct.pack('!H', 443))
            header = receive(self.sock, 4)
            if header[1] != 0:
                raise ConnectionError('socks_connect_failed')
            if header[3] == 1:
                receive(self.sock, 4)
            elif header[3] == 4:
                receive(self.sock, 16)
            elif header[3] == 3:
                receive(self.sock, receive(self.sock, 1)[0])
            else:
                raise ConnectionError('socks_address_invalid')
            receive(self.sock, 2)
            self.sock = ssl.create_default_context().wrap_socket(self.sock, server_hostname='www.google.com')
            self.identity = self.sock.getsockname()
        except Exception:
            self.sock.close()
            raise

    def request(self):
        self.sock.sendall(b'GET /generate_204 HTTP/1.1\r\nHost: www.google.com\r\nConnection: keep-alive\r\n\r\n')
        response = http.client.HTTPResponse(self.sock)
        response.begin()
        status = response.status
        close = response.will_close
        response.read()
        response.close()
        return {'ok': status == 204 and not close, 'http': status,
                'server_will_close': close, 'same_socket': self.sock.getsockname() == self.identity}

    def close(self):
        self.sock.close()
