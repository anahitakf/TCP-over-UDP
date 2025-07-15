import time
import threading
from typing import Tuple, Optional
from packet import Packet
from udp_socket import UDPSocket
import random
from collections import deque

MSS = 512  # Maximum Segment Size
TIMEOUT = 5.0  # Timeout for retransmissions
RECEIVER_BUFFER_SIZE = 10  # Max packets in receiver buffer

class Connection:
    def __init__(self, socket: UDPSocket, addr: Tuple[str, int], is_server: bool = False, initial_packet: Optional[Packet] = None):
        self.socket = socket
        self.addr = addr
        self.is_server = is_server

        if is_server and initial_packet:
            self.seq_num = random.randint(1000000000, 4000000000)
            self.ack_num = initial_packet.seq_num + 1
            self.state = "SYN_RECEIVED"
        else:
            self.seq_num = random.randint(1000000000, 4000000000)
            self.ack_num = 0
            self.state = "CLOSED"

        self.timeout = 10.0
        self.cwnd = 1  # Congestion window in MSS units
        self.rwnd = RECEIVER_BUFFER_SIZE  # Receiver window (updated by ACKs)
        self.receiver_buffer = deque(maxlen=RECEIVER_BUFFER_SIZE)  # Limited receiver buffer
        self.send_buffer = []  # Buffer for data to send
        self.sent_packets = {}  # seq_num -> (packet, timestamp)
        self.ack_counts = {}  # seq_num -> count of duplicate ACKs
        self.recv_buffer = {}  # Out-of-order packets
        self.expected_seq_num = self.ack_num
        self.window_base = self.seq_num

        self.send_lock = threading.Lock()
        self.send_condition = threading.Condition(self.send_lock)
        self._stop_thread = threading.Event()

        # Threads
        self.buffer_thread = threading.Thread(target=self._buffer_manager_thread)
        self.buffer_thread.daemon = True
        self.buffer_thread.start()
        self.check_thread = threading.Thread(target=self._check_receiver_buffer)
        self.check_thread.daemon = True
        self.check_thread.start()

    def _is_packet_valid(self, packet: Packet) -> bool:
        if self.state == "CLOSED":
            return packet.syn and not (packet.ack or packet.fin or packet.data)
        elif self.state == "SYN_SENT":
            return packet.syn and packet.ack and packet.ack_num == self.seq_num + 1
        elif self.state == "SYN_RECEIVED":
            return packet.ack and not (packet.syn or packet.fin or packet.data) and packet.ack_num == self.seq_num
        elif self.state == "ESTABLISHED":
            if packet.data:
                return packet.seq_num >= self.expected_seq_num
            if packet.ack:
                return packet.ack_num >= self.window_base
            if packet.fin:
                return True
            return False
        elif self.state in ["FIN_WAIT_1", "FIN_WAIT_2", "CLOSE_WAIT", "LAST_ACK"]:
            return (packet.ack and packet.ack_num >= self.seq_num) or packet.fin or (packet.ack and not packet.data)
        return False

    def _send_rst(self, packet: Packet = None) -> None:
        rst_packet = Packet(
            seq_num=self.seq_num,
            ack_num=self.ack_num if packet and packet.data else 0,
            rst=True,
            src_port=self.socket.sock.getsockname()[1],
            dst_port=self.addr[1]
        )
        self.socket.send(rst_packet, self.addr)
        print(f"Sent RST to {self.addr} due to invalid packet")

    def three_way_handshake(self) -> None:
        if self.is_server:
            if self.state != "SYN_RECEIVED":
                raise RuntimeError("Invalid state for server handshake")
            if not self.socket.is_listening:
                raise RuntimeError("Socket is not in listening mode")
            syn_ack_packet = Packet(seq_num=self.seq_num, ack_num=self.ack_num, syn=True, ack=True, window=self.rwnd)
            self.socket.send(syn_ack_packet, self.addr)
            print(f"Server: Sent SYN-ACK to {self.addr} with window={self.rwnd}")
            self.seq_num += 1
            start_time = time.time()
            while True:
                if time.time() - start_time > self.timeout:
                    raise TimeoutError("Timeout waiting for ACK")
                packet, addr = self.socket.receive()
                if packet is None:
                    continue
                if addr != self.addr:
                    continue
                if packet.rst:
                    self.state = "CLOSED"
                    self._stop_thread.set()
                    self.send_condition.notify_all()
                    raise RuntimeError("Received RST during handshake, connection closed")
                if packet.ack and packet.ack_num == self.seq_num:
                    self.state = "ESTABLISHED"
                    print(f"Server: Connection established with {self.addr}")
                    return
        else:
            syn_packet = Packet(seq_num=self.seq_num, syn=True, window=self.rwnd)
            self.socket.send(syn_packet, self.addr)
            print(f"Client: Sent SYN to {self.addr} with window={self.rwnd}")
            self.state = "SYN_SENT"
            start_time = time.time()
            while True:
                if time.time() - start_time > self.timeout:
                    raise TimeoutError("Timeout waiting for SYN-ACK")
                packet, addr = self.socket.receive()
                if packet is None:
                    continue
                if addr != self.addr:
                    continue
                if packet.rst:
                    self.state = "CLOSED"
                    self._stop_thread.set()
                    self.send_condition.notify_all()
                    raise RuntimeError("Received RST during handshake, connection closed")
                if not self._is_packet_valid(packet):
                    self._send_rst(packet)
                    continue
                if packet.syn and packet.ack:
                    print(f"Client: Received SYN-ACK from {addr} with window={packet.window}")
                    self.ack_num = packet.seq_num + 1
                    self.seq_num += 1
                    self.rwnd = packet.window  # Update rwnd from SYN-ACK
                    ack_packet = Packet(seq_num=self.seq_num, ack_num=self.ack_num, ack=True, window=self.rwnd)
                    self.socket.send(ack_packet, self.addr)
                    print(f"Client: Sent ACK to {self.addr} with window={self.rwnd}")
                    self.state = "ESTABLISHED"
                    print(f"Client: Connection Established with {self.addr}")
                    return

    def send_data(self, data: str) -> None:
        if self.state != "ESTABLISHED":
            raise RuntimeError("Connection not established")
        segments = [data[i:i + MSS] for i in range(0, len(data), MSS)]
        with self.send_lock:
            for segment in segments:
                self.send_buffer.append(segment)
                print(f"Data added to send buffer: {segment}")
            self.send_condition.notify_all()

    def _send_packet(self, packet: Packet) -> None:
        with self.send_lock:
            current_window_size = min(self.cwnd * MSS, self.rwnd * MSS)
            if len(self.sent_packets) * MSS < current_window_size:
                self.socket.send(packet, self.addr)
                self.sent_packets[packet.seq_num] = (packet, time.time())
                print(f"Sent packet with seq_num={packet.seq_num}, cwnd={self.cwnd}, rwnd={self.rwnd}")
            else:
                self.send_buffer.insert(0, packet.data)
                print(f"Window full, buffering data: {packet.data}")

    def _process_ack(self, packet: Packet) -> None:
        with self.send_lock:
            self.rwnd = packet.window  # Update receiver window
            if packet.ack_num > self.window_base:
                for seq_num in list(self.sent_packets.keys()):
                    if seq_num + len(self.sent_packets[seq_num][0].data.encode('utf-8')) <= packet.ack_num:
                        del self.sent_packets[seq_num]
                self.window_base = packet.ack_num
                self.cwnd += 1  # Increase cwnd by 1 MSS on new ACK
                print(f"ACK processed, new cwnd={self.cwnd}, window_base={self.window_base}")
                self.send_condition.notify_all()
            if packet.ack_num in self.ack_counts:
                self.ack_counts[packet.ack_num] += 1
                if self.ack_counts[packet.ack_num] >= 3:
                    self.cwnd = max(self.cwnd // 2, 1)  # Halve cwnd on 3 duplicate ACKs
                    self._retransmit(packet.ack_num)
                    print(f"3 duplicate ACKs, cwnd halved to {self.cwnd}")
            else:
                self.ack_counts[packet.ack_num] = 1

    def _retransmit(self, seq_num: int) -> None:
        with self.send_lock:
            if seq_num in self.sent_packets:
                packet, _ = self.sent_packets[seq_num]
                self.socket.send(packet, self.addr)
                self.sent_packets[seq_num] = (packet, time.time())
                print(f"Retransmitted packet with seq_num={seq_num}")

    def handle_fin(self, packet: Packet) -> None:
        if packet.rst:
            self.state = "CLOSED"
            self._stop_thread.set()
            self.send_condition.notify_all()
            print(f"Received RST from {self.addr}, connection closed")
            return
        if self.state == "ESTABLISHED":
            if not self._is_packet_valid(packet):
                self._send_rst(packet)
                return
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
                    if addr != self.addr:
                        continue
                    if packet.rst:
                        self.state = "CLOSED"
                        raise RuntimeError("Received RST during FIN handling")
                    if not self._is_packet_valid(packet):
                        self._send_rst(packet)
                        continue
                    if packet.ack and packet.ack_num == self.seq_num + 1:
                        self.seq_num += 1
                        self.state = "CLOSED"
                        print(f"Received ACK for FIN from {self.addr}")
                        return
                print(f"Timeout waiting for ACK for FIN, retrying...")
            raise TimeoutError("Failed to close connection after maximum retries")
    
    def close(self) -> None:
        if self.state not in ["ESTABLISHED", "CLOSE_WAIT"]:
            return
        self._stop_thread.set()
        with self.send_lock:
            self.send_condition.notify_all()
        fin_packet = Packet(seq_num=self.seq_num, ack_num=self.ack_num, fin=True)
        self.socket.send(fin_packet, self.addr)
        print(f"Sending FIN to {self.addr}")
        self.seq_num += 1
        self.state = "FIN_WAIT_1" if self.state == "ESTABLISHED" else "LAST_ACK"
        start_time = time.time()
        while time.time() - start_time < self.timeout:
            packet, addr = self.socket.receive()
            if packet is None:
                continue
            if addr != self.addr:
                continue
            if packet.rst:
                self.state = "CLOSED"
                self._stop_thread.set()
                self.send_condition.notify_all()
                print(f"Received RST from {self.addr}, connection closed")
                return
            if not self._is_packet_valid(packet):
                self._send_rst(packet)
                continue
            if packet.ack and self.state == "FIN_WAIT_1":
                self.state = "FIN_WAIT_2"
                print(f"Received ACK for FIN from {self.addr}")
            elif packet.fin and self.state == "FIN_WAIT_2":
                ack_packet = Packet(seq_num=self.seq_num, ack_num=packet.seq_num + 1, ack=True)
                self.socket.send(ack_packet, self.addr)
                print(f"Sending ACK for FIN to {self.addr}")
                self.state = "TIME_WAIT"
                time.sleep(2)
                self.state = "CLOSED"
                print(f"Connection closed with {self.addr}")
                return
            elif packet.ack and self.state == "LAST_ACK":
                self.state = "CLOSED"
                print(f"Received ACK for FIN from {self.addr}")
                return
        raise TimeoutError("Timeout during connection close")

    def buffer_data(self, packet: Packet) -> None:
        if packet.rst:
            self._send_rst(packet)
            return
        if not self._is_packet_valid(packet):
            self._send_rst(packet)
            return
        if packet.data:
            with self.send_lock:
                remaining_space = RECEIVER_BUFFER_SIZE - len(self.receiver_buffer)
                if packet.seq_num == self.expected_seq_num:
                    if remaining_space > 0:
                        self.receiver_buffer.append(packet.data)
                        self.expected_seq_num += len(packet.data.encode('utf-8'))
                        ack_packet = Packet(
                            seq_num=self.seq_num,
                            ack_num=self.expected_seq_num,
                            ack=True,
                            window=remaining_space
                        )
                        self.socket.send(ack_packet, self.addr)
                        print(f"Buffered data, sent ACK with seq_num={self.seq_num}, ack_num={self.expected_seq_num}, window={remaining_space}")
                    else:
                        ack_packet = Packet(
                            seq_num=self.seq_num,
                            ack_num=self.expected_seq_num,
                            ack=True,
                            window=0
                        )
                        self.socket.send(ack_packet, self.addr)
                        print(f"Buffer full, sent ACK with seq_num={self.seq_num}, ack_num={self.expected_seq_num}, window=0")
                elif packet.seq_num > self.expected_seq_num:
                    self.recv_buffer[packet.seq_num] = packet.data
                    ack_packet = Packet(
                        seq_num=self.seq_num,
                        ack_num=self.expected_seq_num,
                        ack=True,
                        window=remaining_space
                    )
                    self.socket.send(ack_packet, self.addr)
                    print(f"Stored out-of-order packet seq_num={packet.seq_num}, sent ACK with seq_num={self.seq_num}, ack_num={self.expected_seq_num}, window={remaining_space}")
                elif packet.seq_num < self.expected_seq_num:
                    ack_packet = Packet(
                        seq_num=self.seq_num,
                        ack_num=self.expected_seq_num,
                        ack=True,
                        window=remaining_space
                    )
                    self.socket.send(ack_packet, self.addr)
                    print(f"Ignored duplicate packet seq_num={packet.seq_num}, sent ACK with seq_num={self.seq_num}, ack_num={self.expected_seq_num}, window={remaining_space}")

    def _buffer_manager_thread(self):
        while not self._stop_thread.is_set():
            if self.state != "ESTABLISHED":
                time.sleep(0.1)
                continue
            print(f"Checking send_buffer: {len(self.send_buffer)} items")
            with self.send_lock:
                # Send buffered data proactively
                while self.send_buffer and len(self.sent_packets) * MSS < min(self.cwnd * MSS, self.rwnd * MSS):
                    data = self.send_buffer.pop(0)
                    packet = Packet(seq_num=self.seq_num, ack_num=self.ack_num, data=data, window=self.rwnd)
                    self.socket.send(packet, self.addr)
                    self.sent_packets[packet.seq_num] = (packet, time.time())
                    print(f"Sent packet with seq_num={packet.seq_num}, data={data}, cwnd={self.cwnd}, rwnd={self.rwnd}")
                    self.seq_num += len(data.encode('utf-8'))
                # Handle timeouts
                current_time = time.time()
                for seq_num, (packet, timestamp) in list(self.sent_packets.items()):
                    if current_time - timestamp > TIMEOUT:
                        self.cwnd = 1
                        self.socket.send(packet, self.addr)
                        self.sent_packets[seq_num] = (packet, current_time)
                        print(f"Timeout, retransmitted seq_num={seq_num}, cwnd reset to {self.cwnd}")
                # Process out-of-order packets
                while self.expected_seq_num in self.recv_buffer:
                    self.receiver_buffer.append(self.recv_buffer.pop(self.expected_seq_num))
                    self.expected_seq_num += len(self.receiver_buffer[-1].encode('utf-8'))
                    remaining_space = RECEIVER_BUFFER_SIZE - len(self.receiver_buffer)
                    ack_packet = Packet(seq_num=self.seq_num, ack_num=self.expected_seq_num, ack=True, window=remaining_space)
                    self.socket.send(ack_packet, self.addr)
                    print(f"Processed out-of-order data, sent ACK for seq_num={self.seq_num}, ack_num={self.expected_seq_num}, window={remaining_space}")
            # Process incoming packets
            packet, addr = self.socket.receive()
            if packet and addr == self.addr:
                if packet.rst:
                    self.state = "CLOSED"
                    self._stop_thread.set()
                    self.send_condition.notify_all()
                    print(f"Received RST from {self.addr}, connection closed")
                    return
                if not self._is_packet_valid(packet):
                    self._send_rst(packet)
                    continue
                if packet.ack:
                    self._process_ack(packet)
                if packet.data:
                    self.buffer_data(packet)
            time.sleep(0.1)

    def _check_receiver_buffer(self):
        while not self._stop_thread.is_set():
            if self.rwnd == 0:
                probe_packet = Packet(seq_num=self.seq_num, data="", window=0)
                self.socket.send(probe_packet, self.addr)
                print(f"Sent probe packet to check receiver buffer")
            time.sleep(2)

    def get_buffered_data(self):
        with self.send_lock:
            data = list(self.receiver_buffer)
            self.receiver_buffer.clear()
            return data

    def send(self, data: str) -> None:
        if self.state != "ESTABLISHED":
            raise RuntimeError("Connection not established")
        segments = [data[i:i + MSS] for i in range(0, len(data), MSS)]
        with self.send_lock:
            for segment in segments:
                self.send_buffer.append(segment)
                print(f"Data added to send buffer: {segment}")
            self.send_condition.notify_all()