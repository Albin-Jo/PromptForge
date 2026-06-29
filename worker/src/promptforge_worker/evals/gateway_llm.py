"""Adapter LLMs that let ragas/deepeval call *our* gateway instead of a vendor directly.

Both frameworks need an LLM internally (their metrics are themselves LLM-judged). Left to
their defaults they'd construct their own OpenAI client and call the provider directly —
which violates CLAUDE.md part 5 (only the gateway talks to vendors). Each framework exposes a
"bring your own LLM" seam, so we implement that seam over :class:`LLMGateway` and keep the
one-throat-to-choke property (ADR 0011: route through the gateway when the hook cooperates —
both do, so no direct-call exception is needed).

Two thin wrappers, one per framework's interface:

- :class:`GatewayRagasLLM` implements ragas' ``BaseRagasLLM`` (langchain-shaped: a
  ``PromptValue`` in, an ``LLMResult`` out).
- :class:`GatewayDeepEvalLLM` implements deepeval's ``DeepEvalBaseLLM`` (plain string in,
  string out).

Both are async-first: our gateway is async, and the only scoring paths we drive
(``single_turn_ascore`` / ``a_measure``) are async, so they await the gateway directly. The
sync entry points exist only to satisfy the abstract base and delegate to the async one.
"""

from __future__ import annotations

import asyncio
from typing import Any

from deepeval.models.base_model import DeepEvalBaseLLM
from langchain_core.outputs import Generation, LLMResult
from langchain_core.prompt_values import PromptValue
from ragas.llms import BaseRagasLLM

from promptforge_api.gateway import LLMGateway, Message, ModelConfig


class GatewayRagasLLM(BaseRagasLLM):
    """ragas ``BaseRagasLLM`` backed by :class:`LLMGateway`.

    ragas hands us a ``PromptValue`` (its already-rendered prompt) and expects an
    ``LLMResult`` (langchain's container of generations). We flatten the prompt to a single
    user message, run it through the gateway, and wrap the text back up as the one generation
    ragas reads. ``temperature`` defaults low because metric prompts want determinism, not
    creativity — matching ragas' own default.
    """

    def __init__(self, gateway: LLMGateway, *, model: str) -> None:
        self._gateway = gateway
        self._model = model

    async def agenerate_text(
        self,
        prompt: PromptValue,
        n: int = 1,
        temperature: float | None = None,
        stop: list[str] | None = None,
        callbacks: Any = None,
    ) -> LLMResult:
        """Run one gateway completion for a ragas prompt; return it as an ``LLMResult``."""
        config = ModelConfig(model=self._model, temperature=temperature if temperature else 0.0)
        messages = [Message(role="user", content=prompt.to_string())]
        completion = await self._gateway.complete(config=config, messages=messages)
        return LLMResult(generations=[[Generation(text=completion.content)]])

    def generate_text(
        self,
        prompt: PromptValue,
        n: int = 1,
        temperature: float = 0.01,
        stop: list[str] | None = None,
        callbacks: Any = None,
    ) -> LLMResult:
        """Sync shim. We only ever drive ragas via its async ``single_turn_ascore``, so this
        runs the async path in a fresh loop; it must not be called from inside a running one.
        """
        return asyncio.run(
            self.agenerate_text(
                prompt, n=n, temperature=temperature, stop=stop, callbacks=callbacks
            )
        )

    def is_finished(self, response: LLMResult) -> bool:
        """ragas asks whether generation stopped cleanly; the gateway only returns finished
        completions (it doesn't surface partials), so a returned result is always complete.
        """
        return True


class GatewayDeepEvalLLM(DeepEvalBaseLLM):
    """deepeval ``DeepEvalBaseLLM`` backed by :class:`LLMGateway`.

    deepeval's interface is plain text: a prompt string in, a string out (its metrics prompt
    the model to emit JSON and parse it themselves). Some deepeval metrics pass a ``schema``
    keyword for native structured output; we don't implement structured output, so we accept
    and ignore it — deepeval falls back to parsing the JSON the metric prompt already asks for.
    """

    def __init__(self, gateway: LLMGateway, *, model: str) -> None:
        # DeepEvalBaseLLM.__init__ stores a model name/handle; we keep our own and call super
        # with the id so get_model_name()/load_model() have something coherent to return.
        self._gateway = gateway
        self._model = model
        super().__init__(model_name=model)

    def load_model(self, *args: Any, **kwargs: Any) -> Any:
        """deepeval calls this to obtain the underlying client; ours is the gateway itself."""
        return self._gateway

    async def a_generate(self, prompt: str, *args: Any, **kwargs: Any) -> str:
        """Run one gateway completion for a deepeval prompt and return its text."""
        config = ModelConfig(model=self._model, temperature=0.0)
        completion = await self._gateway.complete(
            config=config, messages=[Message(role="user", content=prompt)]
        )
        return completion.content

    def generate(self, prompt: str, *args: Any, **kwargs: Any) -> str:
        """Sync shim over :meth:`a_generate`; deepeval's GEval is driven via async ``a_measure``."""
        return asyncio.run(self.a_generate(prompt, *args, **kwargs))

    def get_model_name(self) -> str:
        return self._model
