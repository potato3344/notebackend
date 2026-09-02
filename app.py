from flask import Flask, request, jsonify
from flask_cors import CORS
import hashlib
import json
import os
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor

app = Flask(__name__)
CORS(app)

# ============ 数据库连接 ============
def get_db():
    """从环境变量获取数据库连接"""
    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        # 本地测试用（如果用不着本地测试，可以留空或者报错）
        print("⚠️ 警告：未找到 DATABASE_URL 环境变量！正在尝试连接本地数据库...")
        return psycopg2.connect(
            host='localhost',
            database='notes_db',
            user='postgres',
            password='123456'
        )
    # 云端环境必须加上 sslmode='require'，否则 Railway 的安全策略会拒绝连接
    return psycopg2.connect(database_url, sslmode='require')

def init_db():
    """初始化数据库表"""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(100) UNIQUE NOT NULL,
                password VARCHAR(255) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS notes (
                id SERIAL PRIMARY KEY,
                username VARCHAR(100) NOT NULL,
                date VARCHAR(20) NOT NULL,
                content TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (username) REFERENCES users(username)
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS reminders (
                id SERIAL PRIMARY KEY,
                username VARCHAR(100) NOT NULL,
                target_date VARCHAR(20) NOT NULL,
                content TEXT NOT NULL,
                notified BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (username) REFERENCES users(username)
            )
        ''')
        conn.commit()
        cur.close()
        conn.close()
        print("✅ 数据库初始化成功")
    except Exception as e:
        print(f"⚠️ 数据库初始化失败: {e}")

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# ============ 用户 API ============
@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    
    if not username or not password:
        return jsonify({"success": False, "msg": "账号和密码不能为空"})
    if len(password) < 4:
        return jsonify({"success": False, "msg": "密码至少4位"})
    
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (username, password) VALUES (%s, %s)",
            (username, hash_password(password))
        )
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"success": True, "msg": "注册成功"})
    except psycopg2.IntegrityError:
        return jsonify({"success": False, "msg": "账号已存在"})
    except Exception as e:
        return jsonify({"success": False, "msg": f"注册失败: {str(e)}"})

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    
    if not username or not password:
        return jsonify({"success": False, "msg": "账号和密码不能为空"})
    
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            "SELECT * FROM users WHERE username = %s",
            (username,)
        )
        user = cur.fetchone()
        cur.close()
        conn.close()
        
        if not user:
            return jsonify({"success": False, "msg": "账号不存在"})
        if user['password'] != hash_password(password):
            return jsonify({"success": False, "msg": "密码错误"})
        
        # 获取该用户的便签
        notes = get_user_notes(username)
        reminders = get_user_reminders(username)
        
        return jsonify({
            "success": True,
            "msg": "登录成功",
            "data": {
                "username": username,
                "notes": notes,
                "reminders": reminders
            }
        })
    except Exception as e:
        return jsonify({"success": False, "msg": f"登录失败: {str(e)}"})

def get_user_notes(username):
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            "SELECT date, content, updated_at FROM notes WHERE username = %s ORDER BY updated_at DESC",
            (username,)
        )
        notes = cur.fetchall()
        cur.close()
        conn.close()
        return [dict(n) for n in notes]
    except Exception:
        return []

def get_user_reminders(username):
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            "SELECT target_date, content, notified FROM reminders WHERE username = %s ORDER BY target_date",
            (username,)
        )
        reminders = cur.fetchall()
        cur.close()
        conn.close()
        return [dict(r) for r in reminders]
    except Exception:
        return []

# ============ 数据同步 API ============
@app.route('/api/sync', methods=['POST'])
def sync():
    data = request.json
    username = data.get('username')
    notes = data.get('notes', [])
    reminders = data.get('reminders', [])
    
    if not username:
        return jsonify({"success": False, "msg": "未登录"})
    
    try:
        conn = get_db()
        cur = conn.cursor()
        
        # 删除旧的便签
        cur.execute("DELETE FROM notes WHERE username = %s", (username,))
        
        # 插入新的便签
        for note in notes:
            cur.execute(
                "INSERT INTO notes (username, date, content, updated_at) VALUES (%s, %s, %s, %s)",
                (username, note.get('date', ''), note.get('content', ''), note.get('updated_at', datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            )
        
        # 删除旧的提醒
        cur.execute("DELETE FROM reminders WHERE username = %s", (username,))
        
        # 插入新的提醒
        for reminder in reminders:
            cur.execute(
                "INSERT INTO reminders (username, target_date, content, notified) VALUES (%s, %s, %s, %s)",
                (username, reminder.get('target_date', ''), reminder.get('content', ''), reminder.get('notified', False))
            )
        
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify({
            "success": True,
            "msg": "同步成功",
            "data": {
                "notes": notes,
                "reminders": reminders
            }
        })
    except Exception as e:
        return jsonify({"success": False, "msg": f"同步失败: {str(e)}"})

@app.route('/api/get_data', methods=['POST'])
def get_data():
    data = request.json
    username = data.get('username')
    
    if not username:
        return jsonify({"success": False, "msg": "未登录"})
    
    notes = get_user_notes(username)
    reminders = get_user_reminders(username)
    
    return jsonify({
        "success": True,
        "data": {
            "username": username,
            "notes": notes,
            "reminders": reminders
        }
    })

if __name__ == '__main__':
    init_db()
    # 在 Railway 上，PORT 变量自动分配，本地默认 5000
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)