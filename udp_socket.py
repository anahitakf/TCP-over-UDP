import socket
from packet import Packet
from typing import Tuple, Optional

class UDPSocket:
    def __init__(self, timeout: float = 10.0):
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.settimeout(timeout)
            self.backlog = None
            self.is_listening = False
            self.connection = None
            self.connection_manager = None
            print("UDP socket created successfully")
        except socket.error as e:
            raise socket.error(f"Failed to create UDP socket: {e}")
    
    def listen(self,backlog:int):
        self.backlog = backlog
        self.is_listening = True
        print(f"Socket is listening with backlog {backlog}")

    def bind(self, host: str, port: int) -> None:
        try:
            self.sock.bind((host, port))
            print(f"Socket bound to {host}:{port}")
        except socket.error as e:
            raise socket.error(f"Failed to bind socket to {host}:{port}: {e}")

    def send(self, arg, addr: Tuple[str, int]) -> None:
            if isinstance(arg, Packet):
                packet = arg
                packet.src_port = self.sock.getsockname()[1]
                packet.dst_port = addr[1]
                print(f"Sending Packet to {addr}:\n{packet}")
                self.sock.sendto(packet.to_bytes(), addr)
            elif isinstance(arg, str):
                if self.connection is None or self.connection.state != "ESTABLISHED":
                    raise RuntimeError("Connection not established")
                self.connection.send(arg)
            else:
                raise ValueError("Argument must be a Packet or a string")

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
        if self.is_listening:
            # server
            self.is_listening = False
            print("Server socket is closing. No new connections will be accepted.")
            if hasattr(self, 'connection_manager') and self.connection_manager:
                
                try:
                    self.connection_manager.close_incomplete_connections()
                    print("All incomplete connections closed.")
                except Exception as e:
                    print(f"Error closing incomplete connections: {e}")
                print("Completed connections remain valid.")
        else:
            #client
            if self.connection:
                try:
                    self.connection.close()
                    print("Client connection closed.")
                except Exception as e:
                    print(f"Error closing client connection: {e}")
        try:
            self.sock.close()
            print("Socket closed successfully")
        except socket.error as e:
            print(f"Warning: Failed to close socket: {e}")
