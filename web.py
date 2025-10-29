from flask import Flask
app = Flask(__name__)

@app.route("/")
def home():
    return "Anime Vault Pro - 24/7 LIVE! 🚀"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
