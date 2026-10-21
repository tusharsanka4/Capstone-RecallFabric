from abc import ABC, abstractmethod


class ProviderError(Exception):
    pass


class ProviderUnavailable(ProviderError):
    pass


class ProviderTimeout(ProviderError):
    pass


class ProviderBadResponse(ProviderError):
    pass


class ProviderResponse(str):
    name: str
    model: str
    text: str

    def __new__(cls, content: str, name: str = "", model: str = ""):
        instance = super().__new__(cls, content)
        instance.name = name
        instance.model = model
        instance.text = content
        return instance


class LLMProvider(ABC):
    name: str
    model: str

    @abstractmethod
    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.0,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> str:
        pass

    @abstractmethod
    def is_available(self) -> bool:
        pass
