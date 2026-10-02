import asyncio
from collections import defaultdict, deque
from contextlib import asynccontextmanager
import logging
import time

from fastapi import Depends, FastAPI, Header, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from .config import Settings
from .game import Forbidden, Game, Unauthorized
from .schemas import CharacterInput, Credentials, Intent, LocationInput, PublishItem, RollbackInput


log = logging.getLogger("worldforge")


class RateLimiter:
    def __init__(self):
        self.entries = defaultdict(deque)

    def check(self, key, count=80, window=60):
        now = time.monotonic()
        q = self.entries[key]
        while q and q[0] <= now-window:
            q.popleft()
        if len(q) >= count:
            return False
        q.append(now)
        if len(self.entries) > 10000:
            self.entries = defaultdict(deque, {k: v for k, v in self.entries.items() if v and v[-1] > now-window})
        return True


class Hub:
    def __init__(self, game):
        self.game = game
        self.clients = {}
        self.locks = {}

    async def send(self, ws, message):
        try:
            async with self.locks[ws]:
                await asyncio.wait_for(ws.send_json(message), timeout=4)
        except (RuntimeError, WebSocketDisconnect, TimeoutError, KeyError):
            self.clients.pop(ws, None)
            self.locks.pop(ws, None)
            try:
                await ws.close()
            except RuntimeError:
                pass

    async def broadcast_content(self, revision):
        await asyncio.gather(*(self.send(ws, {"type": "content_changed", "revision": revision}) for ws in list(self.clients)))

    async def snapshots(self):
        payloads = {}
        for ws, (uid, token) in list(self.clients.items()):
            try:
                self.game.authenticate(token)
            except Unauthorized:
                await ws.close(code=4401)
                self.clients.pop(ws, None)
                self.locks.pop(ws, None)
                continue
            if uid not in payloads:
                payloads[uid] = self.game.snapshot(uid)
            await self.send(ws, {"type": "snapshot", "data": payloads[uid]})


def create_app(settings=None):
    settings = settings or Settings.from_env()
    game = Game(settings)
    hub = Hub(game)
    limits = RateLimiter()

    async def ticker():
        while True:
            await asyncio.sleep(settings.tick_seconds)
            try:
                game.tick()
                await hub.snapshots()
            except Exception:
                log.exception("World tick failed; no client-supplied outcome is accepted")

    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(ticker())
        yield
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        for ws in list(hub.clients):
            try:
                await ws.close(code=1001)
            except RuntimeError:
                pass
        game.db.close()

    app = FastAPI(title="World shard API", version="0.1.0", lifespan=lifespan)
    app.state.game = game
    app.state.hub = hub

    @app.exception_handler(ValueError)
    async def bad_intent(request, exc):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(Unauthorized)
    async def unauthenticated(request, exc):
        return JSONResponse(status_code=401, content={"detail": str(exc)})

    @app.exception_handler(Forbidden)
    async def forbidden(request, exc):
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    @app.middleware("http")
    async def request_limits(request: Request, call_next):
        if int(request.headers.get("content-length", "0")) > 65536:
            return JSONResponse(status_code=413, content={"detail": "Request exceeds the size limit"})
        host = request.client.host if request.client else "unknown"
        auth = request.url.path.startswith("/v1/auth")
        if not limits.check((host, "auth" if auth else "api"), count=30 if auth else 600):
            return JSONResponse(status_code=429, content={"detail": "Too many requests; try again shortly"})
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    def user(authorization: str = Header(default="")):
        if not authorization.startswith("Bearer "):
            raise Unauthorized("Sign in to continue")
        return game.authenticate(authorization[7:])

    def owner(actor=Depends(user)):
        if actor["role"] != "OWNER":
            raise Forbidden("This operation requires OWNER")
        return actor

    @app.get("/health")
    async def health():
        game.db.one("SELECT 1")
        return {"status": "ok", "protocol": 1, "content_revision": game.catalog["revision"]}

    @app.post("/v1/auth/register")
    async def register(data: Credentials):
        return await asyncio.to_thread(game.register, data)

    @app.post("/v1/auth/login")
    async def login(data: Credentials):
        return await asyncio.to_thread(game.login, data)

    @app.post("/v1/auth/logout")
    async def logout(authorization: str = Header(default=""), actor=Depends(user)):
        from .security import token_hash
        with game.db.transaction() as c:
            c.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash(authorization[7:]),))
        return {"message": "Signed out"}

    @app.post("/v1/character")
    async def character(data: CharacterInput, actor=Depends(user)):
        return game.create_character(actor["id"], data)

    @app.post("/v1/location")
    async def location(data: LocationInput, actor=Depends(user)):
        return game.update_location(actor["id"], data)

    @app.get("/v1/state")
    async def state(actor=Depends(user)):
        return game.snapshot(actor["id"])

    @app.post("/v1/intent")
    async def intent(data: Intent, actor=Depends(user)):
        return game.intent(actor["id"], data)

    @app.get("/v1/content")
    async def content():
        return game.catalog

    @app.post("/v1/admin/items")
    async def publish(data: PublishItem, actor=Depends(owner)):
        with game.lock:
            result = game.content.publish_item(actor["id"], data.definition, data.reason)
            game.catalog = game.content.manifest()
        await hub.broadcast_content(result["revision"])
        return result

    @app.get("/v1/admin/history")
    async def history(actor=Depends(owner)):
        return game.content.history()

    @app.get("/v1/admin/items/{item_id}/versions")
    async def versions(item_id: str, actor=Depends(owner)):
        return game.content.versions(item_id)

    @app.post("/v1/admin/rollback")
    async def rollback(data: RollbackInput, actor=Depends(owner)):
        with game.lock:
            result = game.content.rollback(actor["id"], data.id, data.version, data.reason)
            game.catalog = game.content.manifest()
        await hub.broadcast_content(result["revision"])
        return result

    @app.websocket("/v1/live")
    async def live(ws: WebSocket):
        await ws.accept()
        try:
            message = await asyncio.wait_for(ws.receive_json(), timeout=10)
            if message.get("type") != "auth" or not isinstance(message.get("token"), str):
                raise Unauthorized("Session authentication required")
            actor = game.authenticate(message["token"])
            hub.clients[ws] = (actor["id"], message["token"])
            hub.locks[ws] = asyncio.Lock()
            await hub.send(ws, {"type": "snapshot", "data": game.snapshot(actor["id"])})
            while True:
                message = await asyncio.wait_for(ws.receive_json(), timeout=65)
                if not limits.check((actor["id"], "ws"), count=30, window=10):
                    await ws.close(code=4429)
                    break
                if message.get("type") == "ping":
                    game.authenticate(hub.clients[ws][1])
                    await hub.send(ws, {"type": "pong", "server_time": time.time()})
        except (Unauthorized, TimeoutError, ValueError, KeyError):
            await ws.close(code=4401)
        except WebSocketDisconnect:
            pass
        finally:
            hub.clients.pop(ws, None)
            hub.locks.pop(ws, None)

    return app
