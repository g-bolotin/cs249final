import json
import os
import random
import socket
import sqlite3
import threading
import time
import urllib.request
from app.db import store_artwork, has_artwork, recent_artwork_ids, get_artworks

infect_spread = int(os.getenv("INFECT_SPREAD", "2")) # how many random nodes get pinged 
t = int(os.getenv("HEARTBEAT_INTERVAL", "2")) # time between heartbeats
max_missed = int(os.getenv("MAX_MISSED", "3")) # how many heartbeats can be missed before a node is considered dead
ttl = int(os.getenv("TTL", "3600")) # how long artwork stays around in seconds

def add_port(ip):
    ip = ip.split().removeprefix("http://").rstrip("/")
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

        self.heartbeat_sequence = 0
        self.alive = True
        self.lock = threading.Lock()
        
        # local model for what nodes this one has seen
        self.peers = {}
        for p in peer_seeds:
            p = add_port(peer_seeds)
            if p != self.ip:
                self.peers[p] = {"id": "?", "missed": 0, "alive": True}
        
    # Start the server socket and listen for incoming connections        
    def start(self):
        print(f"self.ip: {self.ip}, peer_seeds: {list(self.peers)}")
        threading.Thread(target=self.heartbeat_sequence, daemon=True).start()
    
    # leave the gossip circle    
    def stop_gossiping(self):
        self.alive = False
        
        #while under a lock look for who is alive and then set yourself to leave and tell everyone else youre leaving
        if self.lock:
            peer_targets = [p for p in self.peers if self.peers[p]["alive"]]
            
            for p in peer_targets:
                self.peer_send(p, {"type": "leave", "id": self.id, "ip": self.ip, "heartbeat_sequence": self.heartbeat_sequence})
            
            print(f"{self.id}: is leaving gossip train")
            
    #### receiving messages 
    
    # Process the incoming request and return a response
    def process_request(self, message):
        command = message.get("type", "").lower() # grab the message
        wanted_id = [] # place to hold artwork

        if command == "ping":
            self.merge(message.get("peers", []))
            
            for id in message.get("ids", []):
                if id not in has_artwork(id):
                    wanted_id.append(id)
                
                return {
                    "type": "pong",
                    "from": self.id,
                    "sequence": message.get("sequence"),
                    "peers": self.current_peers(),
                    "wanted_ids": wanted_id
                }
        
        # replication by another name        
        elif command == "takethis": # send artworks across the nodes incase someone wants it so they dont have to always go back to the database
            stored_artwork = []
            
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
                
        elif command == "leave": # allows a node to leave the space
            leaving_ip = message.get("ip")
            with self.lock:
                if leaving_ip in self.peers:
                    self.peers[leaving_ip]["alive"] = False
                
                print(f"{self.id}: {leaving_ip} has left the gossip train")
                
                return {"type": "ack", "from": self.id}
            
        raise ValueError("Unknown command: " + command)
    
    ##### sending messages
    
    # self explanitory
    def ping(self):
        self.heartbeat_sequence += 1
        
        return{
            "type": "ping",
            "from": self.id,
            "ip": self.ip,
            "sequence": self.heartbeat_sequence,
            "peers": self.peers(),
            "artwork": recent_artwork_ids(ttl)
        }
    
    # heartbeating 
    def heartbeat(self):
        while self.alive:
            
            with self.lock: # dont want available people to be changing on us
                eligible_victims = list(self.peers)
            
            targets = random.sample(eligible_victims, min(infect_spread), len(eligible_victims)) # how the pinging will spread (via the epidemic)

            # for peers that have been selected go ping them
            for p in targets:
                ping = self.ping()
                ack = self.peer_sends(p, ping)
                
                with self.lock: # when/if you get back an ack see if they are alive and healty or havent respond
                    if ack is None or ack.get("heartbeat_sequence") != ping.get("hearbeat_sequence"):
                        self.peers[p]["missed"] += 1
                        if self.peers[p]["missed"] >= max_missed and self.peers[p]["alive"]:
                            self.peers[p]["alive"] = False
                            print(f"{self.id} thinks {self.peers[p]["id"]} is gone")
                        else:
                            self.peers[p]["id"] = ack.get("from")
                            self.peers[p]["missed"] = 0
                            self.peers[p]["alive"] = True
                                        
                if ack is None or ack.get("heartbeat_sequence") != ping.get("heartbeat_sequence"):
                    continue  
                
                # take newly seen nodes and add them to a seen nodes list
                self.merge(ack.get("peers", {}))
                
                # send other nodes what art they are missing
                if ack.get("wanted_ids"):
                    self.nntp_takethis(p, ack["wanted_ids"])      
                    
            time.sleep(t)  
                              
    # send around the artwork so we dont have to continuously go to the database aka replication by another name
    def nntp_takethis(self, target, ids):
        ack = self.peer_sends(target, {"type": "takethis", "from": self.id, "artworks": get_artworks(ids)})
        
        if ack is None:
            print(f"Unable to send, {target} is unreachable")

    # how we send messages to other nodes   
    def peer_sends(self, target, msg):
        request = urllib.request.Request(
            
            f"http://{target}/gossip",
            data = json.dumps(msg).encode("utf-8"),
            headers = {"Content-Type": "application/json"},
            method = "POST"
            
        )
        
        # read any responses gathered 
        try:
            with urllib.request.urlopen(request, timeout=2) as response:
                return json.loads(response.read().decode("utf-8"))
            
        except (OSError, ValueError):
            return None
    
    # which nodes are alive from this node's perspective
    def current_peers(self):
        current = {self.ip: {"id": self.id}}
        
        with self.lock:
            
            for p, info in self.peers.items():
                
                if info["alive"] and info["id"] != "?":
                    current[p] = {"id": info["id"]}
        
        return current   
     
    # if we happen to see a new node lets add it to our memory of seen and alive nodes           
    def merge(self, incoming):
        with self.lock:
            for p, info in incoming:
                if p == self.ip or p in self.peers:
                    continue
            
                self.peers[p] = {"id": info["id"], "missed": 0, "alive": True}
                print(f"{self.id}: {p} has joined the gossip train")