from grocery_app import create_app

app = create_app()

if __name__ == "__main__":
    # Bind to 0.0.0.0 so it's reachable across your tailnet.
    app.run(host="0.0.0.0", port=5055, debug=True)
