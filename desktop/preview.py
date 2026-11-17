"""Preview local (CPython) do MESMO simulador e dashboard, sem Raspberry Pi."""
from http.server import BaseHTTPRequestHandler, HTTPServer
import json, os, sys, threading, time
BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, BASE)
from simulator import ColdRoom
from location import load as load_location
try:
    import config
except ImportError:
    config = None  # sem config.py usa valores por omissao
LOCATION, TOPIC = load_location(config)
sim=ColdRoom()
lock=threading.Lock()

def ticker():
    last=time.monotonic()
    while True:
        time.sleep(.25)
        now=time.monotonic()
        dt=min(2,now-last)*sim.speed
        last=now
        with lock:
            n=max(1,int(dt/.5)+1)
            for i in range(n):sim.step(dt/n)
threading.Thread(target=ticker,daemon=True).start()

class Handler(BaseHTTPRequestHandler):
    def respond(self, code, value, typ='application/json'):
        data=value if isinstance(value, bytes) else json.dumps(value).encode()
        self.send_response(code)
        self.send_header('Content-Type',typ)
        self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','no-store')
        self.end_headers()
        self.wfile.write(data)
    def do_GET(self):
        if self.path in ('/','/index.html'):
            with open(os.path.join(BASE,'index.html'),'rb') as f:self.respond(200,f.read(),'text/html; charset=utf-8')
        elif self.path=='/api/state':
            with lock:data=sim.snapshot()
            data['location']=LOCATION
            data['mqtt']={'enabled':False,'connected':False,'host':None,'topic':TOPIC}
            self.respond(200,data)
        else:self.respond(404,{'error':'Not found'})
    def do_POST(self):
        if self.path!='/api/action':return self.respond(404,{'error':'Not found'})
        try:
            n=int(self.headers.get('Content-Length','0'))
            if n<2 or n>512:raise ValueError('Request size')
            data=json.loads(self.rfile.read(n))
            with lock:sim.action(data)
            self.respond(200,{'ok':True})
        except (ValueError,TypeError) as e:self.respond(400,{'error':str(e)})

print('Preview: http://127.0.0.1:8766')
HTTPServer(('127.0.0.1',8766),Handler).serve_forever()
