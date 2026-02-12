import os
import yaml
import aiosqlite
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from typing import List, Optional
from datetime import datetime

DB_PATH = "sns_api.db"
OPENAPI_PATH = os.path.join(os.path.dirname(__file__), "../openapi.yaml")

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

# Allow CORS from everywhere
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Database Init ---
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS posts (
            id TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            content TEXT NOT NULL,
            createdAt TEXT NOT NULL,
            updatedAt TEXT NOT NULL,
            likes INTEGER NOT NULL DEFAULT 0,
            comments INTEGER NOT NULL DEFAULT 0
        )
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS comments (
            id TEXT PRIMARY KEY,
            postId TEXT NOT NULL,
            username TEXT NOT NULL,
            content TEXT NOT NULL,
            createdAt TEXT NOT NULL,
            updatedAt TEXT NOT NULL
        )
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS likes (
            postId TEXT NOT NULL,
            username TEXT NOT NULL,
            PRIMARY KEY (postId, username)
        )
        """)
        await db.commit()

@app.on_event("startup")
async def on_startup():
    await init_db()

# --- Swagger UI ---
@app.get("/docs", include_in_schema=False)
def custom_swagger_ui_html():
    return get_swagger_ui_html(openapi_url="/openapi.json", title="API Docs")

# --- Serve OpenAPI YAML as JSON ---
@app.get("/openapi.json", include_in_schema=False)
def openapi_json():
    with open(OPENAPI_PATH, "r") as f:
        spec = yaml.safe_load(f)
    return JSONResponse(spec)

# --- Serve OpenAPI YAML as YAML ---
@app.get("/openapi.yaml", include_in_schema=False)
def openapi_yaml():
    with open(OPENAPI_PATH, "r") as f:
        return Response(f.read(), media_type="application/yaml")

# --- API Implementation ---
import uuid

# Helper functions
def now_iso():
    return datetime.utcnow().isoformat() + 'Z'

# --- POSTS ---
@app.get("/posts", response_model=List[dict])
async def list_posts():
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT * FROM posts")
        rows = await cursor.fetchall()
        posts = [dict(zip([c[0] for c in cursor.description], row)) for row in rows]
        return posts

@app.post("/posts", status_code=201, response_model=dict)
async def create_post(body: dict):
    if not body.get("username") or not body.get("content"):
        raise HTTPException(status_code=400, detail="Invalid input")
    post_id = str(uuid.uuid4())
    now = now_iso()
    post = {
        "id": post_id,
        "username": body["username"],
        "content": body["content"],
        "createdAt": now,
        "updatedAt": now,
        "likes": 0,
        "comments": 0
    }
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO posts (id, username, content, createdAt, updatedAt, likes, comments) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (post["id"], post["username"], post["content"], post["createdAt"], post["updatedAt"], post["likes"], post["comments"])
        )
        await db.commit()
    return post

@app.get("/posts/{postId}", response_model=dict)
async def get_post(postId: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT * FROM posts WHERE id = ?", (postId,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Post not found")
        return dict(zip([c[0] for c in cursor.description], row))

@app.patch("/posts/{postId}", response_model=dict)
async def update_post(postId: str, body: dict):
    if not body.get("username") or not body.get("content"):
        raise HTTPException(status_code=400, detail="Invalid input")
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT * FROM posts WHERE id = ?", (postId,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Post not found")
        now = now_iso()
        await db.execute(
            "UPDATE posts SET username = ?, content = ?, updatedAt = ? WHERE id = ?",
            (body["username"], body["content"], now, postId)
        )
        await db.commit()
        cursor = await db.execute("SELECT * FROM posts WHERE id = ?", (postId,))
        row = await cursor.fetchone()
        return dict(zip([c[0] for c in cursor.description], row))

@app.delete("/posts/{postId}", status_code=204)
async def delete_post(postId: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT * FROM posts WHERE id = ?", (postId,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Post not found")
        await db.execute("DELETE FROM posts WHERE id = ?", (postId,))
        await db.execute("DELETE FROM comments WHERE postId = ?", (postId,))
        await db.execute("DELETE FROM likes WHERE postId = ?", (postId,))
        await db.commit()
    return Response(status_code=204)

# --- COMMENTS ---
@app.get("/posts/{postId}/comments", response_model=List[dict])
async def list_comments(postId: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT * FROM posts WHERE id = ?", (postId,))
        if not await cursor.fetchone():
            raise HTTPException(status_code=404, detail="Post not found")
        cursor = await db.execute("SELECT * FROM comments WHERE postId = ?", (postId,))
        rows = await cursor.fetchall()
        return [dict(zip([c[0] for c in cursor.description], row)) for row in rows]

@app.post("/posts/{postId}/comments", status_code=201, response_model=dict)
async def create_comment(postId: str, body: dict):
    if not body.get("username") or not body.get("content"):
        raise HTTPException(status_code=400, detail="Invalid input")
    comment_id = str(uuid.uuid4())
    now = now_iso()
    comment = {
        "id": comment_id,
        "postId": postId,
        "username": body["username"],
        "content": body["content"],
        "createdAt": now,
        "updatedAt": now
    }
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT * FROM posts WHERE id = ?", (postId,))
        if not await cursor.fetchone():
            raise HTTPException(status_code=404, detail="Post not found")
        await db.execute(
            "INSERT INTO comments (id, postId, username, content, createdAt, updatedAt) VALUES (?, ?, ?, ?, ?, ?)",
            (comment["id"], comment["postId"], comment["username"], comment["content"], comment["createdAt"], comment["updatedAt"])
        )
        await db.execute("UPDATE posts SET comments = comments + 1 WHERE id = ?", (postId,))
        await db.commit()
    return comment

@app.get("/posts/{postId}/comments/{commentId}", response_model=dict)
async def get_comment(postId: str, commentId: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT * FROM comments WHERE id = ? AND postId = ?", (commentId, postId))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Comment not found")
        return dict(zip([c[0] for c in cursor.description], row))

@app.patch("/posts/{postId}/comments/{commentId}", response_model=dict)
async def update_comment(postId: str, commentId: str, body: dict):
    if not body.get("username") or not body.get("content"):
        raise HTTPException(status_code=400, detail="Invalid input")
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT * FROM comments WHERE id = ? AND postId = ?", (commentId, postId))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Comment not found")
        now = now_iso()
        await db.execute(
            "UPDATE comments SET username = ?, content = ?, updatedAt = ? WHERE id = ? AND postId = ?",
            (body["username"], body["content"], now, commentId, postId)
        )
        await db.commit()
        cursor = await db.execute("SELECT * FROM comments WHERE id = ? AND postId = ?", (commentId, postId))
        row = await cursor.fetchone()
        return dict(zip([c[0] for c in cursor.description], row))

@app.delete("/posts/{postId}/comments/{commentId}", status_code=204)
async def delete_comment(postId: str, commentId: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT * FROM comments WHERE id = ? AND postId = ?", (commentId, postId))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Comment not found")
        await db.execute("DELETE FROM comments WHERE id = ? AND postId = ?", (commentId, postId))
        await db.execute("UPDATE posts SET comments = comments - 1 WHERE id = ? AND comments > 0", (postId,))
        await db.commit()
    return Response(status_code=204)

# --- LIKES ---
@app.post("/posts/{postId}/likes", status_code=201)
async def like_post(postId: str, body: dict):
    if not body.get("username"):
        raise HTTPException(status_code=400, detail="Invalid input")
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT * FROM posts WHERE id = ?", (postId,))
        if not await cursor.fetchone():
            raise HTTPException(status_code=404, detail="Post not found")
        try:
            await db.execute("INSERT INTO likes (postId, username) VALUES (?, ?)", (postId, body["username"]))
            await db.execute("UPDATE posts SET likes = likes + 1 WHERE id = ?", (postId,))
            await db.commit()
        except aiosqlite.IntegrityError:
            pass  # Ignore duplicate like
    return Response(status_code=201)

@app.delete("/posts/{postId}/likes", status_code=204)
async def unlike_post(postId: str, body: dict):
    if not body.get("username"):
        raise HTTPException(status_code=400, detail="Invalid input")
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT * FROM posts WHERE id = ?", (postId,))
        if not await cursor.fetchone():
            raise HTTPException(status_code=404, detail="Post not found")
        cursor = await db.execute("SELECT * FROM likes WHERE postId = ? AND username = ?", (postId, body["username"]))
        if not await cursor.fetchone():
            return Response(status_code=204)
        await db.execute("DELETE FROM likes WHERE postId = ? AND username = ?", (postId, body["username"]))
        await db.execute("UPDATE posts SET likes = likes - 1 WHERE id = ? AND likes > 0", (postId,))
        await db.commit()
    return Response(status_code=204)
