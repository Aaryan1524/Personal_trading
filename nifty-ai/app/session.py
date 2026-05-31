# Session management


class SessionManager:
    def __init__(self) -> None:
        self._history: dict[str, list[dict]] = {}
        self._system: dict[str, str] = {}

    def get_history(self, session_id: str) -> list[dict]:
        return self._history.setdefault(session_id, [])

    def add_message(self, session_id: str, role: str, content: str) -> None:
        history = self._history.setdefault(session_id, [])
        if role == "system":
            self._system[session_id] = content
            if history and history[0].get("role") == "system":
                history[0] = {"role": "system", "content": content}
            else:
                history.insert(0, {"role": "system", "content": content})
        else:
            history.append({"role": role, "content": content})

    def clear_session(self, session_id: str) -> None:
        prompt = self._system.get(session_id)
        if prompt is not None:
            self._history[session_id] = [{"role": "system", "content": prompt}]
        else:
            self._history[session_id] = []
