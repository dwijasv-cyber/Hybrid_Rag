import requests

SERVER_URL = "http://YOUR_PC_LAN_IP:8000/ask_jarvis"
USER_ID = "Dwijas"


def ask_jarvis(query):
    try:
        response = requests.post(
            SERVER_URL,
            json={"user_id": USER_ID, "text": query},
            timeout=60
        )
        response.raise_for_status()
        return response.json().get("answer", "No answer in response.")
    except requests.exceptions.ConnectionError:
        return "ERROR: Cannot reach the server."
    except requests.exceptions.HTTPError as e:
        return f"HTTP ERROR {e.response.status_code}: {e.response.text}"
    except Exception as e:
        return f"Unexpected error: {e}"


def main():
    print("=== Jarvis Mobile Client ===")
    print(f"Server: {SERVER_URL}")
    print("Type 'exit' to quit.\n")
    while True:
        query = input("You: ").strip()
        if query.lower() in ("exit", "quit", "q"):
            print("Goodbye, Sir.")
            break
        if not query:
            continue
        print(f"\nJarvis: {ask_jarvis(query)}\n")


if __name__ == "__main__":
    main()
