from udp_socket import UDPSocket
from connection import Connection
from packet import Packet
import socket
import time
from typing import Dict
from ConnectionManager import ConnectionManager

def server(host: str = "127.0.0.1", port: int = 12345, backlog: int = 5) -> None:
    sock = None
    try:
        sock = UDPSocket(timeout=10.0)
        sock.bind(host, port)
        sock.listen(backlog)
        print(f"Server successfully bound to {host}:{port}")
        conn_manager = ConnectionManager(backlog=backlog, socket=sock)
        sock.connection_manager = conn_manager
        should_stop = False

        print(f"Server started, listening on {host}:{port}...")
        while sock.is_listening and not should_stop:
            try:
                data, addr = sock.sock.recvfrom(1024)
                print(f"Server received raw data from {addr}: {data}\n")
                MILLIS = int(time.time() * 1000)
                try:
                    packet = Packet.from_bytes(data)
                    print(f"[{MILLIS}] Parsed packet from {addr}: syn={packet.syn}, seq_num={packet.seq_num}, ack_num={packet.ack_num}, data={packet.data}\n")
                except ValueError as e:
                    print(f"Failed to parse packet from {addr}: {e}\n")
                    continue
                if packet.rst:
                    conn = conn_manager.find_connection(addr)
                    if conn:
                        conn.state = "CLOSED"
                        conn_manager.remove_connection(addr)
                        print(f"Received RST from {addr}, connection closed")
                    continue

                conn = conn_manager.find_connection(addr)
                if conn is None:
                    if packet.syn and sock.is_listening:
                        try:
                            if len(conn_manager.incomplete_connections) >= backlog:
                                print(f"backlog full, ignoring SYN from {addr}\n")
                                continue
                            conn = Connection(sock, addr, is_server=True, initial_packet=packet)
                            conn_manager.add_incomplete(conn)
                            conn.three_way_handshake()
                            conn_manager.move_to_completed(addr)
                            print(f"Connection with {addr} established and moved to completed buffer\n")
                        except (TimeoutError, RuntimeError) as e:
                            print(f"Failed to establish connection with {addr}: {e}\n")
                            conn_manager.remove_connection(addr)
                            continue
                    else:
                        print(f"Rejecting non-SYN packet or SYN packet while not listening from {addr}: {packet}\n")
                        continue
                else:
                    try:
                        if packet.fin:
                            if conn.state in ["ESTABLISHED", "CLOSE_WAIT", "LAST_ACK"]:
                                conn.handle_fin(packet)
                                if conn.state == "CLOSED":
                                    conn_manager.remove_connection(addr)
                                    print(f"Connection with {addr} closed\n")
                            else:
                                print(f"Ignoring FIN in state {conn.state} from {addr}\n")
                        elif packet.data:
                            print(f"Received data from {addr}: {packet.data}\n")
                            if conn.state in ["ESTABLISHED", "CLOSE_WAIT"]:
                                conn.buffer_data(packet)
                                buffered_data = conn.get_buffered_data()
                                for data in buffered_data:
                                    print(f"Processing buffered data from {addr}: {data}\n")
                                    sock.send(f"Server received: {data}", addr)
                            else:
                                print(f"Packet ignored in state {conn.state} from {addr}\n")
                        elif packet.ack and not packet.syn:
                            print(f"Received ACK from {addr}: seq_num={packet.seq_num}, ack_num={packet.ack_num}, window={packet.window}\n")
                            if conn.state == "LAST_ACK" and packet.ack_num == conn.seq_num:
                                conn.state = "CLOSED"
                                conn_manager.remove_connection(addr)
                                print(f"Connection with {addr} closed (duplicate ACK)\n")
                            elif conn.state == "SYN_RECEIVED" and packet.ack_num == conn.seq_num + 1:
                                conn.state = "ESTABLISHED"
                                conn_manager.move_to_completed(addr)
                                print(f"Connection with {addr} established (ACK received)\n")
                        else:
                            print(f"Ignoring unexpected packet from {addr}: {packet}\n")
                    except RuntimeError as e:
                        print(f"Error processing packet from {addr}: {e}\n")
                        conn_manager.remove_connection(addr)
                        print(f"Connection with {addr} terminated due to error\n")
            except socket.timeout:
                print("Socket timeout occurred, continuing to listen...")
                conn_manager.cleanup_closed()
                break
            except socket.error as e:
                print(f"Socket error: {e}")
                raise
            try:
                conn, addr = conn_manager.accept()
                sock.connection = conn
                print(f"Accepted connection from {addr}")
                buffered_data = conn.get_buffered_data()
                for data in buffered_data:
                    print(f"Processing buffered data from {addr}: {data}\n")
                    sock.send(f"Server received: {data}", addr)
            except RuntimeError:
                pass
            except Exception as e:
                print(f"Error in accept: {e}")

    except Exception as e:
        print(f"Server failed: {e}")
    finally:
        if sock:
            sock.close()
            print("Server socket closed\n")

if __name__ == "__main__":
    server()