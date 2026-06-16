import sqlite3
import json
from datetime import datetime
import hashlib

class Database:
    def __init__(self, db_path='data/agent.db'):
        self.db_path = db_path
        self.init_db()
    
    def get_connection(self):
        return sqlite3.connect(self.db_path)
    
    def init_db(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Users table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_login TIMESTAMP
            )
        ''')
        
        # Chat history table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                session_id TEXT,
                message TEXT NOT NULL,
                is_user BOOLEAN NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')
        
        # Files table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                filename TEXT NOT NULL,
                filepath TEXT NOT NULL,
                file_type TEXT,
                size INTEGER,
                uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                analyzed BOOLEAN DEFAULT 0,
                analysis_data TEXT,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')
        
        # Agent sessions table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS agent_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                agent_name TEXT NOT NULL,
                agent_type TEXT DEFAULT 'chat',
                status TEXT DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_active TIMESTAMP,
                config_data TEXT,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')
        
        conn.commit()
        conn.close()
    
    # User methods
    def create_user(self, username, password):
        """Create a new user with hashed password"""
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                'INSERT INTO users (username, password_hash) VALUES (?, ?)',
                (username, password_hash)
            )
            user_id = cursor.lastrowid
            conn.commit()
            return user_id
        except sqlite3.IntegrityError:
            return None  # Username already exists
        finally:
            conn.close()
    
    def authenticate_user(self, username, password):
        """Authenticate user and return user data if successful"""
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            'SELECT id, username FROM users WHERE username = ? AND password_hash = ?',
            (username, password_hash)
        )
        
        user = cursor.fetchone()
        conn.close()
        
        if user:
            user_id, username = user
            self.update_last_login(user_id)
            return {'id': user_id, 'username': username}
        return None
    
    def update_last_login(self, user_id):
        """Update user's last login timestamp"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            'UPDATE users SET last_login = ? WHERE id = ?',
            (datetime.now().isoformat(), user_id)
        )
        
        conn.commit()
        conn.close()
    
    # Chat methods
    def save_chat_message(self, user_id, session_id, message, is_user=True):
        """Save a chat message to history"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            'INSERT INTO chat_history (user_id, session_id, message, is_user, timestamp) VALUES (?, ?, ?, ?, ?)',
            (user_id, session_id, message, is_user, datetime.now().isoformat())
        )
        
        conn.commit()
        conn.close()
    
    def get_chat_history(self, user_id, session_id=None, limit=50):
        """Get chat history for a user/session"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        if session_id:
            cursor.execute(
                '''SELECT message, is_user, timestamp FROM chat_history 
                   WHERE user_id = ? AND session_id = ? 
                   ORDER BY timestamp ASC LIMIT ?''',
                (user_id, session_id, limit)
            )
        else:
            cursor.execute(
                '''SELECT message, is_user, timestamp FROM chat_history 
                   WHERE user_id = ? 
                   ORDER BY timestamp DESC LIMIT ?''',
                (user_id, limit)
            )
        
        history = cursor.fetchall()
        conn.close()
        
        return [
            {
                'message': row[0],
                'is_user': bool(row[1]),
                'timestamp': row[2]
            }
            for row in history
        ]
    
    # File methods
    def save_file_record(self, user_id, filename, filepath, file_type, size):
        """Save file metadata to database"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            '''INSERT INTO files (user_id, filename, filepath, file_type, size) 
               VALUES (?, ?, ?, ?, ?)''',
            (user_id, filename, filepath, file_type, size)
        )
        
        file_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return file_id
    
    def update_file_analysis(self, file_id, analysis_data):
        """Update file with analysis results"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        analysis_json = json.dumps(analysis_data)
        
        cursor.execute(
            'UPDATE files SET analyzed = 1, analysis_data = ? WHERE id = ?',
            (analysis_json, file_id)
        )
        
        conn.commit()
        conn.close()
    
    def get_user_files(self, user_id):
        """Get all files for a user"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            'SELECT id, filename, file_type, size, uploaded_at, analyzed FROM files WHERE user_id = ? ORDER BY uploaded_at DESC',
            (user_id,)
        )
        
        files = cursor.fetchall()
        conn.close()
        
        return [
            {
                'id': row[0],
                'filename': row[1],
                'file_type': row[2],
                'size': row[3],
                'uploaded_at': row[4],
                'analyzed': bool(row[5])
            }
            for row in files
        ]
    
    # Agent session methods
    def create_agent_session(self, user_id, agent_name, agent_type='chat', config=None):
        """Create a new agent session"""
        session_id = f"{user_id}_{int(datetime.now().timestamp())}"
        config_json = json.dumps(config) if config else None
        
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            '''INSERT INTO agent_sessions (user_id, agent_name, agent_type, session_id, config_data) 
               VALUES (?, ?, ?, ?, ?)''',
            (user_id, agent_name, agent_type, session_id, config_json)
        )
        
        conn.commit()
        conn.close()
        
        return session_id
    
    def update_agent_session(self, session_id):
        """Update agent session last active time"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            'UPDATE agent_sessions SET last_active = ? WHERE session_id = ?',
            (datetime.now().isoformat(), session_id)
        )
        
        conn.commit()
        conn.close()