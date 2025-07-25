import json
from typing import Optional
import random
class Packet:
    def __init__(self, seq_num: int, ack_num: int = 0, data: str = "", syn: bool = False, ack: bool = False, fin: bool = False, rst: bool = False, src_port: int = None, dst_port: int = None, window: int = 0):
        self.seq_num = seq_num
        self.ack_num = ack_num
        self.data = data
        self.payload_length = len(data.encode('utf-8'))
        self.syn = syn
        self.ack = ack
        self.fin = fin
        self.rst = rst
        self.src_port = src_port
        self.dst_port = dst_port
        self.window = window  # Receiver window size (rwnd) 

    def to_bytes(self) -> bytes:
        packet_dict = {
            "seq_num": self.seq_num,
            "ack_num": self.ack_num,
            "data": self.data,
            "payload_length": self.payload_length,
            "syn": self.syn,
            "ack": self.ack,
            "fin": self.fin,
            "rst": self.rst,
            "src_port": self.src_port,
            "dst_port": self.dst_port,
            "window": self.window
        }
        return json.dumps(packet_dict).encode()

    @staticmethod
    def from_bytes(byte_data: bytes) -> 'Packet':
        try:
            packet_dict = json.loads(byte_data.decode())
            return Packet(
                seq_num=packet_dict["seq_num"],
                ack_num=packet_dict["ack_num"],
                data=packet_dict.get("data", ""),
                syn=bool(packet_dict["syn"]),
                ack=bool(packet_dict["ack"]),
                fin=bool(packet_dict["fin"]),
                rst=bool(packet_dict.get("rst", False)),
                src_port=packet_dict.get("src_port"),
                dst_port=packet_dict.get("dst_port"),
                window=packet_dict.get("window", 0)
            )
        except (json.JSONDecodeError, KeyError) as e:
            raise ValueError(f"Invalid packet format: {e}")
        
    def __str__(self) -> str:
        flags = []
        if self.syn: flags.append("SYN")
        if self.ack: flags.append("ACK")
        if self.fin: flags.append("FIN")
        if self.rst: flags.append("RST")
        flags_str = " | ".join(flags) if flags else "None"
        return (
            f"\n Packet Details:\n"
            f"------------------\n"
            f"Source port: {self.src_port or 'Unknown'}\n"
            f"Destination Port: {self.dst_port or 'Unknown'}\n"
            f"Sequence Number: {self.seq_num}\n"
            f"Acknowledgement Number: {self.ack_num}\n"
            f"Control Flags: {flags_str}\n"
            f"Window Size: {self.window}\n"
            f"Payload Length: {self.payload_length} Bytes\n"
            f"Data Payload: {self.data or 'None'}"
        )