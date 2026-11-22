import json
import os
import random
import socket
import sqlite3
import threading
import time


infect_spread = int(os.getenv("INFECT_SPREAD", "2")) # how many random nodes get pinged 
t = int(os.getenv("HEARTBEAT_INTERVAL", "2")) # time between heartbeats
max_missed = int(os.getenv("MAX_MISSED", "3")) # how many heartbeats can be missed before a node is considered dead
ttl = int(os.getenv("TTL", "3600")) # how long artwork stays around in seconds

def add_port(ip):
    ip = ip.split(":")[0]
    if ":" in ip: 
        return ip
    else:  
        return ip + ":8000"

class Gossip:
    def __init__(self, id, ip, peer_seeds, notify):
        self.id = id
        self.ip = add_port(ip)
        self.peer_seeds = peer_seeds
        self.notify = notify

        self.serverSocket = None
        self.heartbeat_sequence = 0
        self.time = time.time()
        self.alive = True
        self.lock = threading.Lock()
        
        self.peers = {}
        for p in peer_seeds:
            p = add_port(peer_seeds)
            if p != self.ip:
                self.peers[p] = {"id": "?", "last_heartbeat": time.time(), "alive": True}
        
        # failure detection
        self.whoisalive = {p: True for p in self.peer_seeds}
        self.missed_heartbeats = {p: 0 for p in self.peer_seeds}
        self.alive_lock = threading.Lock()
        
    # Start the server socket and listen for incoming connections        
    def start(self):
        # self.serverSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # self.serverSocket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # self.serverSocket.bind(("0.0.0.0", self.peer_port))
        # self.serverSocket.listen(5)
        
        print(f"self.ip: {self.ip}, peer_seeds: {list(self.peers)}")
        threading.Thread(target=self.heartbeat_sequence, daemon=True).start()
        
    def stop_gossiping(self):
        self.alive = False
        self.time = time.time()
        if self.serverSocket:
            peer_targets = [p for p in self.peers if self.peers[p]["alive"]]
            
            for p in peer_targets:
                self.peer_send(p, {"type": "leave", "id": self.id, "ip": self.ip, "heartbeat_sequence": self.heartbeat_sequence})
            print(f"{self.id}: is leaving gossip train")
            
    def connection(self):
        while True:
            try:
                clientSocket, addr = self.serverSocket.accept() # accept le connection
                print(f"connection from {addr} has been established") #get rid of later tis for debugging
                threading.Thread(target=self.listen_linda, args=(clientSocket, addr), daemon=True).start()
            
            except Exception as e:
                print(f"error occurred while accepting connection: {e}")
                break
            
    def listen_linda(self, clientSocket, text):
        data = b""
        
        try:
            while True: # while listening for a message
                data_chunk = clientSocket.recv(1024)
                
                if not data_chunk:
                    break
                
                data += data_chunk
                
                while b"\n" in data: # rip up the data into something we can read
                    line, data = data.split(b"\n", 1)
                    text = line.decode("utf-8").strip()
                    
                    if not text: 
                        continue
                    
                    try:
                        response = self.process_request(text) # send the response to the processing block
                    except ValueError:
                        response = json.dumps(create_error("BAD_REQUEST", "invalid JSON"))
                    
                    if response is None:
                        clientSocket.sendall((json.dumps({"status": "ok", "operation": "quit"}) + "\n" ).encode("utf-8"))
                        return
                    
                    clientSocket.sendall((response + "\n").encode("utf-8")) # take the response and send into the ether
                
        except socket.timeout:
            print("socket timeouted")
        
        except Exception as e:
            print(f"error occurred: {e}")
        
        finally:
            clientSocket.close()
    
    # Process the incoming request and return a response
    def process_request(self, text):
        message = json.loads(text)
        command = message.get("type", "").lower()
        wanted_id = {}
        
        if command == "ping":
            self.merge(message.get("peers", []))
            for id in message.get("ids", []):
                if id not in has_artwork(id):
                    wanted_id[id] = id
                return {
                    "type": "pong",
                    "from": self.id,
                    "sequence": message.get("sequence"),
                    "peers": self.current_peers(),
                    "wanted_ids": list(wanted_id.keys())
                }
        elif command == "takethis":
            stored_artwork = {}
            for art in message.get("artworks", []):
                new_art = store_artwork(art["artwork_id"], art["artist"], art["title"], art.get("created_at", time.time()), art.get("tags", []))
                
                if new_art:
                    self.notify(art["artwork_id"], art["artist"], art["title"])
                    stored_artwork.append(art["artwork_id"])
                    
            if stored_artwork:
                return {
                    "type": "ack",
                    "from": self.id,
                    "sequence": message.get("sequence"),
                    "stored_artworks": stored_artwork
                }
        elif command == "leave":
            leaving_ip = message.get("ip")
            with self.lock:
                if leaving_ip in self.peers:
                    self.peers[leaving_ip]["status"] = "left"
                    self.peers["heartbeat_sequence"] = message.get("heartbeat_sequence")
                
                print(f"{self.id}: {leaving_ip} has left the gossip train")
                return {"type": "ack", "from": self.id}
            
        raise ValueError("Unknown command: " + command)
    
    def current_peers(self):
        view = {self.ip: {"id": self.id, "last_heartbeat": time.time(), "alive": True}}
        with self.lock:
            for p, info in self.peers.items():
                view[p] = {"id": info["id"], "last_heartbeat": info["last_heartbeat"], "alive": info["alive"]}
        return view
    
    def merge(self, incoming_peers):
        now = time.time()
        with self.lock:
            for p, info in incoming_peers.items():
                if p == self.ip:
                    continue
                
                mine = self.peers.get(p)
                if p not in self.peers or info["last_heartbeat"] > self.peers[p]["last_heartbeat"]:
                    self.peers[p] = {"id": info["id"], "last_heartbeat": info["last_heartbeat"], "alive": True}
                    print (f"{self.id}: merged peer {p} with last heartbeat {info['last_heartbeat']}")
                    
                elif info["heartbeat_sequence"] > self.peers[p]["heartbeat_sequence"]:
                    if mine["status"] in ("left", "dead"):
                        print(f"{self.id}: ignoring heartbeat from {p} because it has left or is dead")
                    mine["id"] = info["id"]
                    mine["last_heartbeat"] = now
                    mine["status"] = "alive"
                    mine["heartbeat_sequence"] = info["heartbeat_sequence"]