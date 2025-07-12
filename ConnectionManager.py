from udp_socket import UDPSocket
from connection import Connection
from packet import Packet
import socket
import time
from typing import Dict, Optional

class ConnectionManager:
    def __init__(self, backlog: int):
        self.incomplete_connections: Dict[tuple[str, int], Connection] = {}  # SYN Queue
        self.completed_connections: Dict[tuple[str, int], Connection] = {}   # Accept Queue
        self.backlog = backlog

    def add_incomplete(self, conn: Connection):
        """Add a connection to the incomplete queue."""
        if len(self.incomplete_connections) >= self.backlog:
            raise RuntimeError("Incomplete connection queue is full")
        self.incomplete_connections[conn.addr] = conn

    def move_to_completed(self, addr: tuple[str, int]):
        """Move a connection from incomplete to completed queue."""
        if addr in self.incomplete_connections:
            conn = self.incomplete_connections.pop(addr)
            if len(self.completed_connections) >= self.backlog:
                raise RuntimeError("Completed connection queue is full")
            self.completed_connections[addr] = conn

    def find_connection(self, addr: tuple[str, int]) -> Optional[Connection]:
        """Find a connection in either queue."""
        return self.completed_connections.get(addr) or self.incomplete_connections.get(addr)

    def remove_connection(self, addr: tuple[str, int]):
        """Remove a connection from either queue."""
        self.incomplete_connections.pop(addr, None)
        self.completed_connections.pop(addr, None)

    def cleanup_closed(self):
        """Remove closed connections from both queues."""
        self.incomplete_connections = {
            addr: conn for addr, conn in self.incomplete_connections.items() if conn.state != "CLOSED"
        }
        self.completed_connections = {
            addr: conn for addr, conn in self.completed_connections.items() if conn.state != "CLOSED"
        }
