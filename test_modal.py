import modal

app = modal.App("test")

@app.function()
def hello():
    return "Hello from Modal!"

@app.local_entrypoint()
def main():
    print(hello.remote())
