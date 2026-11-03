import sqlite3
from typing import List, Dict, Tuple

DB_PATH = "pitwall.db"

def get_connection(path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn

def init_db(path: str = DB_PATH) -> None:
    with get_connection(path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                chat_id TEXT,
                user_id TEXT,
                user_name TEXT,
                score INTEGER DEFAULT 0,
                PRIMARY KEY (chat_id, user_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS votes (
                chat_id TEXT,
                user_id TEXT,
                round_id TEXT,
                choice TEXT,
                PRIMARY KEY (chat_id, user_id, round_id)
            )
        """)
        conn.commit()

def record_vote(chat_id: str, user_id: str, user_name: str, round_id: str, choice: str, path: str = DB_PATH) -> None:
    with get_connection(path) as conn:
        conn.execute("""
            INSERT INTO users (chat_id, user_id, user_name, score)
            VALUES (?, ?, ?, 0)
            ON CONFLICT(chat_id, user_id) DO UPDATE SET user_name = excluded.user_name
        """, (str(chat_id), str(user_id), user_name))
        conn.execute("""
            INSERT INTO votes (chat_id, user_id, round_id, choice)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(chat_id, user_id, round_id) DO UPDATE SET choice = excluded.choice
        """, (str(chat_id), str(user_id), str(round_id), choice))
        conn.commit()

def get_votes(chat_id: str, round_id: str, path: str = DB_PATH) -> List[Tuple[str, str, str]]:
    with get_connection(path) as conn:
        cursor = conn.execute("""
            SELECT u.user_id, u.user_name, v.choice
            FROM votes v
            JOIN users u ON v.chat_id = u.chat_id AND v.user_id = u.user_id
            WHERE v.chat_id = ? AND v.round_id = ?
        """, (str(chat_id), str(round_id)))
        return [(row["user_id"], row["user_name"], row["choice"]) for row in cursor.fetchall()]

def add_points(chat_id: str, user_id: str, user_name: str, points: int, path: str = DB_PATH) -> None:
    with get_connection(path) as conn:
        conn.execute("""
            INSERT INTO users (chat_id, user_id, user_name, score)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(chat_id, user_id) DO UPDATE SET
                score = users.score + excluded.score,
                user_name = excluded.user_name
        """, (str(chat_id), str(user_id), user_name, points))
        conn.commit()

def get_leaderboard(chat_id: str, path: str = DB_PATH) -> List[Dict[str, any]]:
    with get_connection(path) as conn:
        cursor = conn.execute("""
            SELECT user_name, score
            FROM users
            WHERE chat_id = ?
            ORDER BY score DESC, user_name ASC
        """, (str(chat_id),))
        return [{"name": row["user_name"], "score": row["score"]} for row in cursor.fetchall()]

def reset_chat(chat_id: str, path: str = DB_PATH) -> None:
    with get_connection(path) as conn:
        conn.execute("DELETE FROM users WHERE chat_id = ?", (str(chat_id),))
        conn.execute("DELETE FROM votes WHERE chat_id = ?", (str(chat_id),))
        conn.commit()
