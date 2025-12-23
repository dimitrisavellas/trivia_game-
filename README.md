🎮 Real-Time Multiplayer Trivia Game

A Flask-based multiplayer guessing game where teams compete in real-time to score points by revealing answers strategically. Built with WebSockets for instant synchronization across all players.
✨ Features

    Real-time multiplayer using Flask-SocketIO for live gameplay

    Team-based competition with customizable team names and colors

    Round-robin gameplay where teams take turns guessing while others control answer reveals

    Dynamic scoring system with difficulty-based points

    Lobby system with shareable game codes for easy joining

    PostgreSQL integration for question/answer management

    Configurable difficulty levels (Easy, Medium, Hard)

    Responsive UI with gradient design and smooth animations

🛠️ Tech Stack

    Backend: Flask, Flask-SocketIO, Eventlet

    Database: PostgreSQL (Neon serverless)

    Frontend: Vanilla JavaScript, Socket.IO client

    Deployment: Railway (serverless mode)

🚀 Quick Start

Clone, install dependencies, set DATABASE_URL in .env, and run with python app.py. Perfect for game nights with 2-4 teams!
