import { WebSocketServer, WebSocket } from 'ws';

const PORT = 8080;
const wss = new WebSocketServer({ port: PORT });
let latestPos = null;

wss.on('connection', ws => {
  if (latestPos) ws.send(JSON.stringify(latestPos));

  ws.on('message', data => {
    let pos;
    try { pos = JSON.parse(data.toString()); } catch { return; }
    if (typeof pos.lat !== 'number' || typeof pos.lon !== 'number') return;
    latestPos = { lat: pos.lat, lon: pos.lon };
    for (const client of wss.clients) {
      if (client !== ws && client.readyState === WebSocket.OPEN) {
        client.send(JSON.stringify(latestPos));
      }
    }
  });
});

console.log(`GPS relay running on ws://0.0.0.0:${PORT}`);
