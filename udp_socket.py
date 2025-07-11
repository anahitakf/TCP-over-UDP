import socket
from packet import Packet
from typing import Tuple, Optional

class UDPSocket:
    def __init__(self, timeout: float = 10.0):
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.settimeout(timeout)
            print("UDP socket created successfully")
        except socket.error as e:
            raise socket.error(f"Failed to create UDP socket: {e}")

    def bind(self, host: str, port: int) -> None:
        try:
            self.sock.bind((host, port))
            print(f"Socket bound to {host}:{port}")
        except socket.error as e:
            raise socket.error(f"Failed to bind socket to {host}:{port}: {e}")

    def send(self, packet: Packet, addr: Tuple[str, int]) -> None:
        if not isinstance(packet, Packet):
            raise ValueError("Packet must be an instance of Packet class")
        try:
            packet.src_port = self.sock.getsockname()[1]
            packet.dst_port = addr[1]
            print(f"Sending Packet to {addr}:\n{packet}")
            self.sock.sendto(packet.to_bytes(), addr)
        except socket.error as e:
            raise socket.error(f"Failed to send packet to {addr}: {e}")

    def receive(self) -> Tuple[Optional[Packet], Optional[Tuple[str, int]]]:
        try:
            data, addr = self.sock.recvfrom(1024)
            packet = Packet.from_bytes(data)
            print(f"Received from {addr}:\n{packet}")
            return packet, addr
        except socket.timeout:
            print(f"Receive timeout on socket")
            return None, None
        except socket.error as e:
            raise socket.error(f"Failed to receive packet: {e}")

    def close(self) -> None:
        try:
            self.sock.close()
            print("Socket closed successfully")
        except socket.error as e:
            print(f"Warning: Failed to close socket: {e}")