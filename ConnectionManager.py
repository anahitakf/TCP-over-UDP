from udp_socket import UDPSocket
from connection import Connection
from packet import Packet
import socket
import time
from typing import Dict, Optional
from typing import Tuple, Optional

class ConnectionManager:
    def __init__(self, backlog: int):
        self.incomplete_connections: Dict[tuple[str, int], Connection] = {}  # SYN Queue
        self.completed_connections: Dict[tuple[str, int], Connection] = {}   # Accept Queue
        self.backlog = backlog

    def add_incomplete(self, conn: Connection):
        if len(self.incomplete_connections) >= self.backlog:
            raise RuntimeError("Incomplete connection queue is full")
        self.incomplete_connections[conn.addr] = conn

    def move_to_completed(self, addr: tuple[str, int]):
        if addr in self.incomplete_connections:
            conn = self.incomplete_connections.pop(addr)
            if len(self.completed_connections) >= self.backlog:
                raise RuntimeError("Completed connection queue is full")
            self.completed_connections[addr] = conn

    def find_connection(self, addr: tuple[str, int]) -> Optional[Connection]:
        return self.completed_connections.get(addr) or self.incomplete_connections.get(addr)

    def remove_connection(self, addr: tuple[str, int]):
        self.incomplete_connections.pop(addr, None)
        self.completed_connections.pop(addr, None)

    def cleanup_closed(self) -> None:
        for addr in list(self.completed_connections.keys()):
            if self.completed_connections[addr].state == "CLOSED":
                self.completed_connections.pop(addr)

    def accept(self) -> Tuple[Connection, Tuple[str, int]]: 
        while True:
            if self.completed_connections:
                addr, conn = next(iter(self.completed_connections.items()))
                if conn.state == "ESTABLISHED":
                    return conn, addr
            print("No connections available, waiting for new connections...")
            time.sleep(1)
