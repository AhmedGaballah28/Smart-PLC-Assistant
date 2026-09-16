import { createServer } from "node:http";
import { spawn } from "node:child_process";
import { readFile } from "node:fs/promises";
import { extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = fileURLToPath(new URL(".", import.meta.url));
const PROJECT_ROOT = join(__dirname, "..");
const BRIDGE_PATH = join(__dirname, "api_bridge.py");
const PORT = Number(process.env.PORT || 4173);

const contentTypes = new Map([
  [".html", "text/html; charset=utf-8"],
  [".css", "text/css; charset=utf-8"],
  [".js", "text/javascript; charset=utf-8"],
  [".json", "application/json; charset=utf-8"],
  [".svg", "image/svg+xml"],
]);

function sendJson(response, statusCode, payload) {
  response.writeHead(statusCode, {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store",
  });
  response.end(JSON.stringify(payload));
}

function readBody(request) {
  return new Promise((resolve, reject) => {
    let body = "";
    request.on("data", (chunk) => {
      body += chunk;
      if (body.length > 1_000_000) {
        request.destroy();
        reject(new Error("Request body is too large"));
      }
    });
    request.on("end", () => resolve(body));
    request.on("error", reject);
  });
}

function runBridge(action, payload = null) {
  return new Promise((resolve, reject) => {
    const child = spawn("py", [BRIDGE_PATH, action], {
      cwd: PROJECT_ROOT,
      stdio: ["pipe", "pipe", "pipe"],
      windowsHide: true,
    });
    let stdout = "";
    let stderr = "";

    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString();
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString();
    });
    child.on("error", reject);
    child.on("close", (code) => {
      if (code !== 0) {
        reject(new Error(stderr || `Bridge exited with code ${code}`));
        return;
      }
      try {
        resolve(JSON.parse(stdout || "{}"));
      } catch (error) {
        reject(error);
      }
    });

    if (payload) {
      child.stdin.write(JSON.stringify(payload));
    }
    child.stdin.end();
  });
}

const server = createServer(async (request, response) => {
  let url;
  try {
    url = new URL(request.url || "/", `http://${request.headers.host}`);

    if (url.pathname === "/api/dashboard" && request.method === "GET") {
      sendJson(response, 200, await runBridge("snapshot"));
      return;
    }

    if (url.pathname === "/api/human-decision" && request.method === "POST") {
      const body = await readBody(request);
      const payload = body ? JSON.parse(body) : {};
      sendJson(response, 200, await runBridge("decision", payload));
      return;
    }

    if (url.pathname === "/api/start-project" && request.method === "POST") {
      sendJson(response, 200, await runBridge("start_project"));
      return;
    }

    if (url.pathname === "/api/stop-project" && request.method === "POST") {
      sendJson(response, 200, await runBridge("stop_project"));
      return;
    }

    if (url.pathname === "/api/inject-fault" && request.method === "POST") {
      const body = await readBody(request);
      const payload = body ? JSON.parse(body) : {};
      sendJson(response, 200, await runBridge("inject_fault", payload));
      return;
    }

    const pathname = decodeURIComponent(url.pathname);
    const requestedPath = pathname === "/" ? "index.html" : normalize(pathname).replace(/^[/\\]+/, "");
    const filePath = join(__dirname, "public", requestedPath);
    const file = await readFile(filePath);

    response.writeHead(200, {
      "Content-Type": contentTypes.get(extname(filePath)) || "application/octet-stream",
      "Cache-Control": "no-store",
    });
    response.end(file);
  } catch (error) {
    if (url?.pathname?.startsWith("/api/")) {
      sendJson(response, 500, { ok: false, error: error.message || "Dashboard API error" });
      return;
    }
    response.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
    response.end("Not found");
  }
});

server.listen(PORT, () => {
  console.log(`Smart PLC dashboard running at http://localhost:${PORT}`);
});
