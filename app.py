from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room
import psycopg2
import os
from dotenv import load_dotenv
import secrets

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', secrets.token_hex(16))
socketio = SocketIO(app, cors_allowed_origins="*")

# In-memory game storage
games = {}

def get_db():
    """Get database connection with retry"""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            return psycopg2.connect(os.getenv("DATABASE_URL"))
        except psycopg2.OperationalError as e:
            if attempt == max_retries - 1:
                raise e
    return None


class GameSession:
    def __init__(self, game_id, num_teams, team_names, team_colors, difficulties, total_rounds):
        self.game_id = game_id
        self.num_teams = num_teams
        self.team_names = team_names[:num_teams]

        # base fallback colors
        base_colors = ["#3498db", "#e74c3c", "#f39c12", "#27ae60"]
        colors = (team_colors or [])[:num_teams]
        while len(colors) < num_teams:
            colors.append(base_colors[len(colors)])
        # keep length 4 so UI that loops 0..3 is safe
        self.team_colors = colors + base_colors[len(colors):]

        self.team_scores = [0, 0, 0, 0]

        # question counter across the whole game (1,2,3,...)
        self.question_num = 0

        # rounds: how many times each team should get a turn
        self.total_rounds = total_rounds or 5

        # difficulties filter
        self.difficulties = difficulties

        self.question_text = ""
        self.answers = []
        self.revealed = []

        # derived per-question: whose turn is it
        self.current_team = 0

        self.players = {}  # socket_id -> team_index
        self.started = False
        
    def to_dict(self):
        return {
            'game_id': self.game_id,
            'num_teams': self.num_teams,
            'team_names': self.team_names,
            'team_colors': self.team_colors,
            'team_scores': self.team_scores,
            'current_team': self.current_team,
            'question_num': self.question_num,
            'total_rounds': self.total_rounds,
            'question_text': self.question_text,
            'answers': self.answers,
            'revealed': self.revealed,
            'started': self.started
        }


# ===== ROUTES =====

@app.route('/')
def index():
    """Landing/Lobby page"""
    return render_template('index.html')

@app.route('/game/<game_id>')
def game(game_id):
    """Game room page"""
    return render_template('game.html', game_id=game_id)


# ===== SOCKET EVENTS =====

@socketio.on('create_game')
def handle_create_game(data):
    """Create new game and return game code"""
    game_id = secrets.token_urlsafe(6)
    num_teams = data['num_teams']
    team_names = data['team_names']
    team_colors = data.get('team_colors', [])
    difficulties = data['difficulties']
    total_rounds = data.get('total_rounds', 5)
    
    game = GameSession(game_id, num_teams, team_names, team_colors, difficulties, total_rounds)
    games[game_id] = game
    
    # Creator joins as Team 0
    join_room(game_id)
    game.players[request.sid] = 0
    
    emit('game_created', {
        'game_id': game_id,
        'team_index': 0,
        'state': game.to_dict()
    })
    print(f'✅ Game created: {game_id}')

@socketio.on('join_game')
def handle_join_game(data):
    """Join existing game by code"""
    game_id = data['game_id']
    
    if game_id not in games:
        emit('error', {'message': 'Game not found'})
        return
    
    game = games[game_id]
    join_room(game_id)
    
    # Assign to next available team
    assigned_teams = list(game.players.values())
    team_index = None
    for i in range(game.num_teams):
        if i not in assigned_teams:
            team_index = i
            break
    
    if team_index is None:
        # All teams full, assign to team 0
        team_index = 0
    
    game.players[request.sid] = team_index
    
    emit('joined_game', {
        'game_id': game_id,
        'team_index': team_index,
        'state': game.to_dict()
    })
    
    # Notify others
    socketio.emit('player_joined', {
        'team_index': team_index,
        'team_name': game.team_names[team_index],
        'players': {i: game.team_names[i] for i in set(game.players.values())}
    }, room=game_id)
    
    print(f'👥 Player joined {game_id} as Team {team_index}')

@socketio.on('start_game')
def handle_start_game(data):
    """Start game and load first question"""
    game_id = data['game_id']
    
    if game_id not in games:
        return
    
    game = games[game_id]
    game.started = True
    
    load_next_question(game)
    socketio.emit('game_started', game.to_dict(), room=game_id)
    print(f'🎮 Game {game_id} started')

@socketio.on('restart_game')
def handle_restart_game(data):
    """Restart game with same teams/settings"""
    game_id = data['game_id']
    if game_id not in games:
        return
    
    game = games[game_id]
    game.team_scores = [0, 0, 0, 0]
    game.question_num = 0
    game.current_team = 0
    game.question_text = ""
    game.answers = []
    game.revealed = []
    game.started = True
    
    load_next_question(game)
    socketio.emit('game_started', game.to_dict(), room=game_id)
    print(f'🔁 Game {game_id} restarted')

@socketio.on('reveal_answer')
def handle_reveal_answer(data):
    """Reveal answer and award points"""
    game_id = data['game_id']
    answer_index = data['answer_index']
    
    if game_id not in games:
        return
    
    game = games[game_id]
    my_team = game.players.get(request.sid, 0)
    
    # Guesser can't click
    if game.current_team == my_team:
        return
    
    if answer_index in game.revealed or answer_index >= len(game.answers):
        return
    
    # Reveal
    game.revealed.append(answer_index)
    pts = game.answers[answer_index][1]
    game.team_scores[game.current_team] += pts
    
    socketio.emit('answer_revealed', {
        'answer_index': answer_index,
        'points': pts,
        'state': game.to_dict()
    }, room=game_id)

@socketio.on('next_question')
def handle_next_question(data):
    """Load next question"""
    game_id = data['game_id']
    
    if game_id not in games:
        return
    
    game = games[game_id]
    my_team = game.players.get(request.sid, 0)
    
    # Guesser can't advance
    if game.current_team == my_team:
        return
    
    load_next_question(game)
    
    # total questions in game = rounds * teams
    total_questions = game.total_rounds * game.num_teams
    if game.question_num > total_questions:
        socketio.emit('game_over', game.to_dict(), room=game_id)
    else:
        socketio.emit('question_loaded', game.to_dict(), room=game_id)


def load_next_question(game):
    """Load question from database"""
    game.question_num += 1

    # total questions in game = rounds * teams
    total_questions = game.total_rounds * game.num_teams
    if game.question_num > total_questions:
        return
    
    # team index cycles 0,1,...,num_teams-1 in round-robin
    game.current_team = (game.question_num - 1) % game.num_teams
    
    try:
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute(
            """
            SELECT id, question_text
            FROM questions
            WHERE difficulty_label = ANY(%s)
            ORDER BY RANDOM()
            LIMIT 1
            """,
            (game.difficulties,),
        )
        qrow = cur.fetchone()
        
        if not qrow:
            cur.close()
            conn.close()
            return
        
        qid, qtext = qrow
        
        cur.execute(
            """
            SELECT answer_text, difficulty_score
            FROM answers
            WHERE question_id = %s
            ORDER BY display_order
            """,
            (qid,),
        )
        answers = cur.fetchall()
        
        cur.close()
        conn.close()
        
        game.question_text = qtext
        game.answers = answers
        game.revealed = []
        
    except Exception as e:
        print(f'❌ Database error: {e}')


if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port, debug=False)
