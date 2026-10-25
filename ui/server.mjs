import fs from "node:fs";
import http from "node:http";
import https from "node:https";
import path from "node:path";
import { fileURLToPath } from "node:url";

const port = Number(process.env.PORT || 8842);
const root = path.resolve(process.env.STATIC_ROOT || path.join(path.dirname(fileURLToPath(import.meta.url)), "dist"));
const upstream = process.env.CONTROL_PLANE_URL || "http://127.0.0.1:8841";
const types = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".svg": "image/svg+xml",
  ".json": "application/json",
  ".woff2": "font/woff2",
  ".png": "image/png",
};

function sendFile(res, file) {
  fs.readFile(file, (error, data) => {
    if (error) {
      fs.readFile(path.join(root, "index.html"), (fallbackError, html) => {
        if (fallbackError) {
          res.writeHead(404);
          res.end("yok");
          return;
        }
        res.writeHead(200, { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-cache" });
        res.end(html);
      });
      return;
    }
    const ext = path.extname(file);
    res.writeHead(200, {
      "Content-Type": types[ext] || "application/octet-stream",
      "Cache-Control": ext === ".html" ? "no-cache" : "public, max-age=31536000, immutable",
    });
    res.end(data);
  });
}

function proxy(req, res) {
  const target = new URL(req.url.replace(/^\/backend/, "") || "/", upstream);
  const library = target.protocol === "https:" ? https : http;
  const headers = { ...req.headers, host: target.host };
  delete headers["accept-encoding"];
  const upstreamReq = library.request(
    target,
    { method: req.method, headers },
    (upstreamRes) => {
      res.writeHead(upstreamRes.statusCode || 502, upstreamRes.headers);
      upstreamRes.pipe(res);
    },
  );
  upstreamReq.on("error", () => {
    res.writeHead(502, { "Content-Type": "text/plain; charset=utf-8" });
    res.end("kontrol düzlemi yok");
  });
  req.pipe(upstreamReq);
}

const server = http.createServer((req, res) => {
  if (!req.url) {
    res.writeHead(400);
    res.end();
    return;
  }
  if (req.url.startsWith("/backend/")) {
    proxy(req, res);
    return;
  }
  const pathname = decodeURIComponent(req.url.split("?")[0]);
  const relative = pathname === "/" ? "index.html" : pathname.replace(/^\/+/, "");
  const file = path.normalize(path.join(root, relative));
  if (!file.startsWith(root)) {
    res.writeHead(403);
    res.end();
    return;
  }
  sendFile(res, file);
});

server.listen(port, "0.0.0.0");
