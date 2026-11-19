"""Cap the dollars one live loop invocation may spend on model requests.

One ModelBudget is shared by every role, repetition and retry. BudgetedModel reserves a
conservative upper bound before a request leaves, then settles against the usage the provider
returns. A failed call keeps its reservation because the provider may still have billed it.
Prices come from genai-prices, the table PydanticAI already uses to price its spans.
"""

from __future__ import annotations

import itertools
import threading
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Any, cast

from genai_prices import Usage, calc_price
from pydantic_ai import RunContext
from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter, ModelResponse
from pydantic_ai.models import ModelRequestParameters, StreamedResponse
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.settings import ModelSettings

DEFAULT_CAP_USD = Decimal("5.00")
# A reply may not exceed this, so the reservation stays bounded.
MAX_OUTPUT_TOKENS = 4096
# Serialized request bytes per token. English averages about 4, so 2 overestimates on purpose.
BYTES_PER_TOKEN = 2
# These models answer from code, cost nothing and need no ledger.
OFFLINE_SYSTEMS = frozenset({"test", "function"})


class BudgetExhaustedError(RuntimeError):
    """The next request cannot fit under the cap."""


class UnknownPricingError(ValueError):
    """The model has no price, so its cost cannot be bounded."""


class UnknownBillingError(ValueError):
    """The response carries no usable usage, so what it cost is unknown."""


def _dollars(value: Decimal | float | str) -> Decimal:
    return Decimal(str(value))


def request_price_bound(
    provider: str, model_name: str, input_tokens: int, output_tokens: int
) -> Decimal:
    """Upper bound in dollars; every input token is priced as a cache write, the dearest rate."""
    usage = Usage(
        input_tokens=input_tokens,
        cache_write_tokens=input_tokens,
        output_tokens=output_tokens,
    )
    try:
        price = calc_price(usage, model_name, provider_id=provider)
    except LookupError as error:
        raise UnknownPricingError(f"no price for {provider}:{model_name}") from error
    return price.total_price


def response_cost(response: ModelResponse, provider: str, model_name: str) -> Decimal:
    """Price the usage against the model that was asked, not the name the response echoes."""
    usage = response.usage
    if usage.unmeasured_requests or usage.total_tokens == 0:
        raise UnknownBillingError("the response reports no usable usage")
    priced = Usage(
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=usage.cache_read_tokens,
        cache_write_tokens=usage.cache_write_tokens,
    )
    try:
        price = calc_price(priced, model_name, provider_id=provider)
    except LookupError as error:
        raise UnknownBillingError(f"no price for {provider}:{model_name}") from error
    return price.total_price


class Reservation:
    def __init__(self, reservation_id: int, amount_usd: Decimal) -> None:
        self.reservation_id = reservation_id
        self.amount_usd = amount_usd


class ModelBudget:
    """Thread-safe ledger: settled spend plus open and kept reservations never exceed the cap."""

    def __init__(self, cap_usd: Decimal | float | str = DEFAULT_CAP_USD) -> None:
        cap = _dollars(cap_usd)
        if cap <= 0:
            raise ValueError(f"cap must be positive, got {cap}")
        self.cap_usd = cap
        self._lock = threading.Lock()
        self._ids = itertools.count(1)
        self._settled = Decimal(0)
        self._kept = Decimal(0)
        self._open: dict[int, Decimal] = {}

    @property
    def spent_usd(self) -> Decimal:
        with self._lock:
            return self._settled

    @property
    def committed_usd(self) -> Decimal:
        with self._lock:
            return self._committed()

    @property
    def remaining_usd(self) -> Decimal:
        with self._lock:
            return self.cap_usd - self._committed()

    def _committed(self) -> Decimal:
        return self._settled + self._kept + sum(self._open.values(), Decimal(0))

    def reserve(self, amount_usd: Decimal | float | str) -> Reservation:
        amount = _dollars(amount_usd)
        if amount < 0:
            raise ValueError(f"cannot reserve a negative amount: {amount}")
        with self._lock:
            committed = self._committed()
            if committed + amount > self.cap_usd:
                raise BudgetExhaustedError(
                    f"request needs up to ${amount} but only ${self.cap_usd - committed} "
                    f"of the ${self.cap_usd} cap is left"
                )
            reservation = Reservation(next(self._ids), amount)
            self._open[reservation.reservation_id] = amount
        return reservation

    def settle(
        self, reservation: Reservation, actual_usd: Decimal | float | str
    ) -> None:
        """Replace the reservation with the real cost, even when that overshoots the bound."""
        actual = _dollars(actual_usd)
        with self._lock:
            self._close(reservation)
            self._settled += actual

    def keep(self, reservation: Reservation) -> None:
        """Billing is unknown, so the full reservation counts as spent."""
        with self._lock:
            self._close(reservation)
            self._kept += reservation.amount_usd

    def _close(self, reservation: Reservation) -> None:
        if reservation.reservation_id not in self._open:
            raise ValueError(f"reservation {reservation.reservation_id} is not open")
        del self._open[reservation.reservation_id]


class BudgetedModel(WrapperModel):
    """Charge every request of the wrapped model to one shared ModelBudget."""

    def __init__(self, wrapped: Any, budget: ModelBudget) -> None:
        super().__init__(wrapped)
        self.budget = budget

    @property
    def _offline(self) -> bool:
        return self.wrapped.system in OFFLINE_SYSTEMS

    def _bounded_settings(self, model_settings: ModelSettings | None) -> ModelSettings:
        merged = dict(self.wrapped.settings or {})
        merged.update(model_settings or {})
        requested = cast("int | None", merged.get("max_tokens"))
        merged["max_tokens"] = min(requested or MAX_OUTPUT_TOKENS, MAX_OUTPUT_TOKENS)
        return cast(ModelSettings, merged)

    def _reserve(
        self,
        messages: list[ModelMessage],
        settings: ModelSettings,
        parameters: ModelRequestParameters,
    ) -> Reservation:
        payload = ModelMessagesTypeAdapter.dump_json(messages)
        size = len(payload) + len(repr(parameters))
        input_tokens = size // BYTES_PER_TOKEN + 1
        output_tokens = cast("int", settings.get("max_tokens", MAX_OUTPUT_TOKENS))
        bound = request_price_bound(
            self.wrapped.system, self.wrapped.model_name, input_tokens, output_tokens
        )
        return self.budget.reserve(bound)

    def _settle(self, reservation: Reservation, response: ModelResponse) -> None:
        try:
            cost = response_cost(response, self.wrapped.system, self.wrapped.model_name)
        except UnknownBillingError:
            self.budget.keep(reservation)
            return
        self.budget.settle(reservation, cost)

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        if self._offline:
            return await self.wrapped.request(
                messages, model_settings, model_request_parameters
            )
        settings = self._bounded_settings(model_settings)
        reservation = self._reserve(messages, settings, model_request_parameters)
        try:
            response = await self.wrapped.request(
                messages, settings, model_request_parameters
            )
        except BaseException:
            self.budget.keep(reservation)
            raise
        self._settle(reservation, response)
        return response

    @asynccontextmanager
    async def request_stream(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
        run_context: RunContext[Any] | None = None,
    ) -> AsyncGenerator[StreamedResponse]:
        if self._offline:
            async with self.wrapped.request_stream(
                messages, model_settings, model_request_parameters, run_context
            ) as offline_stream:
                yield offline_stream
            return
        settings = self._bounded_settings(model_settings)
        reservation = self._reserve(messages, settings, model_request_parameters)
        settled = False
        try:
            async with self.wrapped.request_stream(
                messages, settings, model_request_parameters, run_context
            ) as stream:
                yield stream
                settled = True
                self._settle(reservation, stream.get())
        except BaseException:
            if not settled:
                self.budget.keep(reservation)
            raise
