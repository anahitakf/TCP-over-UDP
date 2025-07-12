from udp_socket import UDPSocket
from connection import Connection
import time

def client(host: str = "127.0.0.1", port: int = 12345, max_retries: int = 3):
    sock = None
    try:
        sock = UDPSocket(timeout=10.0)
        sock.bind(host, 0)  # Bind to any available port
        print(f"Socket bound to {host}:{sock.sock.getsockname()[1]}")
        print("Client: Initializing connection...\n")
        
        conn = Connection(sock, (host, port))
        sock.connection = conn
        retries = 0
        while retries < max_retries:
            try:
                conn.three_way_handshake()
                print(f"Connection Established with {host}:{port}\n")
                break
            except (TimeoutError, OSError) as e:  
                retries += 1
                if retries == max_retries:
                    raise Exception(f"Failed to establish connection after {max_retries} attempts: {e}")
                print(f"Retry {retries}/{max_retries} due to: {e}")
                time.sleep(1)  # Wait before retrying
        
        data_to_send = "Hi from Client!"
        sock.send(data_to_send, (host, port))
        with conn.send_condition:
            while conn.send_buffer:
                conn.send_condition.wait()
        start_time = time.time()
        while time.time() - start_time < conn.timeout:
            packet, addr = sock.receive()
            if packet and addr == (host, port) and packet.ack and packet.ack_num == conn.seq_num:
                print(f"Received ACK for data from {addr}")
                break
        else:
            raise TimeoutError("Timeout waiting for ACK for data")

        conn.close()
    except Exception as e:
        print(f"Client error: {e}")
        raise
    finally:
        if sock is not None:
            sock.close()
            print("Socket closed successfully")

if __name__ == "__main__":
    client()