import time
from typing import Tuple, Optional
from packet import Packet
from udp_socket import UDPSocket

class Connection:
    def __init__(self, socket: UDPSocket, addr: Tuple[str, int], is_server: bool = False, initial_packet: Optional[Packet] = None):
        self.socket = socket
        self.addr = addr
        self.is_server = is_server

        if is_server and initial_packet:
            self.seq_num = 3804222960  # Server’s initial sequence number
            self.ack_num = initial_packet.seq_num + 1
            self.state = "SYN_RECEIVED"
        else:
            self.seq_num = 1133012452 if not is_server else 3804222960
            self.ack_num = 0
            self.state = "CLOSED"
        self.timeout = 10.0
        self.data_buffer = []  # Buffer for received data

    def three_way_handshake(self) -> None:
        if self.is_server:
            if self.state != "SYN_RECEIVED":
                raise RuntimeError("Invalid state for server handshake")
            if not self.socket.is_listening:  # اصلاح: استفاده از self.socket به جای self.sock
                raise RuntimeError("Socket is not in listening mode")
            syn_ack_packet = Packet(seq_num=self.seq_num, ack_num=self.ack_num, syn=True, ack=True)
            self.socket.send(syn_ack_packet, self.addr)
            print(f"Server: Sent SYN-ACK to {self.addr}")
            self.seq_num += 1
            start_time = time.time()
            while True:
                if time.time() - start_time > self.timeout:
                    raise TimeoutError("Timeout waiting for ACK")
                packet, addr = self.socket.receive()
                if packet is None:
                    continue  # Timeout, keep waiting
                if addr == self.addr and packet.ack and packet.ack_num == self.seq_num:
                    self.state = "ESTABLISHED"
                    print(f"Server: Connection established with {self.addr}")
                    return
        else:
            syn_packet = Packet(seq_num=self.seq_num, syn=True)
            self.socket.send(syn_packet, self.addr)
            print(f"Client: Sent SYN to {self.addr}")
            self.state = "SYN_SENT"
            start_time = time.time()
            while True:
                if time.time() - start_time > self.timeout:
                    raise TimeoutError("Timeout waiting for SYN-ACK")
                packet, addr = self.socket.receive()
                if packet is None:
                    continue  # Timeout, keep waiting
                if addr == self.addr and packet.syn and packet.ack:
                    print(f"Client: Received SYN-ACK from {addr}")
                    self.ack_num = packet.seq_num + 1
                    self.seq_num += 1
                    ack_packet = Packet(seq_num=self.seq_num, ack_num=self.ack_num, ack=True)
                    self.socket.send(ack_packet, self.addr)
                    print(f"Client: Sent ACK to {self.addr}")
                    self.state = "ESTABLISHED"
                    print(f"Client: Connection Established with {self.addr}")
                    return

    def send_data(self, data: str) -> None:
        if self.state != "ESTABLISHED":
            raise RuntimeError("Connection not established")
        packet = Packet(seq_num=self.seq_num, ack_num=self.ack_num, data=data)
        self.socket.send(packet, self.addr)
        print(f"Sending data: {data}")
        start_time = time.time()
        while time.time() - start_time < self.timeout:
            recv_packet, addr = self.socket.receive()
            if recv_packet is None:
                continue  # Timeout, keep waiting
            if addr == self.addr and recv_packet.ack and recv_packet.ack_num == self.seq_num + len(data):
                print(f"Received ACK for data from {self.addr}")
                self.seq_num += len(data)
                return
        raise TimeoutError("Timeout waiting for ACK for data")

    def handle_fin(self, packet: Packet) -> None:
        if self.state == "ESTABLISHED":
            ack_packet = Packet(seq_num=self.seq_num, ack_num=packet.seq_num + 1, ack=True)
            self.socket.send(ack_packet, self.addr)
            print(f"Sending ACK for FIN to {self.addr}")
            self.ack_num = packet.seq_num + 1
            self.state = "CLOSE_WAIT"
            
            fin_packet = Packet(seq_num=self.seq_num, ack_num=self.ack_num, fin=True)
            max_retries = 5
            base_timeout = self.timeout
            for attempt in range(max_retries):
                self.socket.send(fin_packet, self.addr)
                print(f"Sending FIN to {self.addr} (attempt {attempt + 1}/{max_retries})")
                self.state = "LAST_ACK"
                start_time = time.time()
                while time.time() - start_time < base_timeout * (2 ** attempt):
                    packet, addr = self.socket.receive()
                    if packet is None:
                        continue
                    if addr == self.addr and packet.ack and packet.ack_num == self.seq_num + 1:
                        self.seq_num += 1
                        self.state = "CLOSED"
                        print(f"Received ACK for FIN from {self.addr}")
                        return
                print(f"Timeout waiting for ACK for FIN, retrying...")
            raise TimeoutError("Failed to close connection after maximum retries")
    
    def close(self) -> None:
        if self.state in ["ESTABLISHED", "CLOSE_WAIT"]:
            fin_packet = Packet(seq_num=self.seq_num, ack_num=self.ack_num, fin=True)
            self.socket.send(fin_packet, self.addr)
            print(f"Sending FIN to {self.addr}")  
            self.seq_num += 1
            if self.state == "ESTABLISHED":
                self.state = "FIN_WAIT_1"
            else:  # CLOSE_WAIT
                self.state = "LAST_ACK"
            start_time = time.time()
            while time.time() - start_time < self.timeout:
                packet, addr = self.socket.receive()
                if packet is None:
                    continue  # Timeout, keep waiting
                if addr == self.addr:
                    if packet.ack and self.state == "FIN_WAIT_1":
                        self.state = "FIN_WAIT_2"
                        print(f"Received ACK for FIN from {self.addr}")
                    elif packet.ack and self.state == "LAST_ACK":
                        self.state = "CLOSED"
                        print(f"Received ACK for FIN from {self.addr}")
                        return
                    elif packet.fin and self.state == "FIN_WAIT_2":
                        ack_packet = Packet(seq_num=self.seq_num, ack_num=packet.seq_num + 1, ack=True)
                        self.socket.send(ack_packet, self.addr)
                        print(f"Sending ACK for FIN to {self.addr}")
                        self.state = "TIME_WAIT"
                        time.sleep(2)  # Simulate TIME_WAIT
                        self.state = "CLOSED"
                        print(f"Connection closed with {self.addr}")
                        return
            raise TimeoutError("Timeout during connection close")

    def buffer_data(self, packet: Packet):
        """Store received data in buffer."""
        if packet.data:
            self.data_buffer.append(packet.data)

    def get_buffered_data(self):
        """Return and clear buffered data."""
        data = self.data_buffer.copy()
        self.data_buffer.clear()
        return data