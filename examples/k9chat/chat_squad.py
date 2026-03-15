from chat_agent import ChatAgent


class ChatSquad:
    """
    Minimal squad coordinating the ChatAgent
    """

    def __init__(self):
        self.agent = ChatAgent()

    def run(self, text: str):

        request = {"text": text}

        result = self.agent.execute(request)

        return result["response"]