from flask import Flask
app = Flask(_name_)

@app.route("/")
def home():
    return "Anime Vault Pro Bot is LIVE 24/7! 🚀"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
