# fake_llm.py is a scripted LLMClient for unit and E2E tests.
# It never opens a network connection; responses are looked up from caller-provided scripts.

from __future__ import annotations

import re
from typing import Mapping

from murphy.orchestrator.llm import (
    LLMRequest,
    LLMResponse,
    LLMResponseError,
    LLMUnavailableError,
)

_WHITESPACE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    return _WHITESPACE.sub(" ", text.strip().lower())


class FakeLLM:
    """Test double that implements LLMClient via exact / substring scripts."""

    def __init__(
        self,
        *,
        exact: Mapping[str, LLMResponse] | None = None, # exact match on normalized user text
        contains: Mapping[str, LLMResponse] | None = None, # map of substrings to responses (e.g. "prune" -> "please prune this docker mess")
        default: LLMResponse | None = None, # fallback response if no exact or substring match
        unavailable: bool = False, # if true pretend the LLM is down 
    ) -> None:
        self._exact = {_normalize(key): value for key, value in (exact or {}).items()} # keys are lowercased / whitespace-normalized
        self._contains = [
            (_normalize(key), value) for key, value in (contains or {}).items()
        ] # List of tuples (normalized substring, response) with same normalization
        self._default = default 
        self.unavailable = unavailable
        self.calls: list[LLMRequest] = [] # Log of every request so tests can assert that the planner called the LLM with the correct request

    # complete is the main method that implements the LLMClient interface
    # it takes a request and returns a scripted response; it doesn't actually call the LLM, just for testing
    def complete(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request) # Log the request for assertions

        if self.unavailable: # if the LLM is marked unavailable, raise an error
            raise LLMUnavailableError("fake LLM is marked unavailable")

        key = _normalize(request.user) # normalize the user text

        if key in self._exact: # if there is an exact match, return the response
            return self._exact[key]

        for needle, response in self._contains: # if there is a substring match, return the response
            if needle and needle in key: # if the substring is in the key, return the response
                return response

        if self._default is not None: # if there is a default response, return it
            return self._default

        raise LLMResponseError( # if there is no match, raise an error
            f"no fake response scripted for user text: {request.user!r}"
        )
